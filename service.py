"""The part that runs in the gateway: API-server routes for the extension and Desktop, and the brief worker.

Routes (all under /api/plugins/hermes-brief). Every route except /pair needs either the API server's own auth (its
API key) or a device token this plugin issued to the Chrome extension through pairing:

    POST   /pair                      {code, name} -> {token}. The only unauthenticated route: it needs a 6-digit
                                      code shown on the Desktop Briefs page, valid 5 minutes, used once; five wrong
                                      codes cancel all open codes.
    GET    /status                    plugin version, profile, counts
    POST   /items                     save {url, title?, folder?, kind?, content?, selection?, note?, source?, meta?}
    GET    /items?q=&folder=&days=    search saved items (newest first)
    GET    /lookup?url=               the item saved for this URL, or null
    GET    /items/{id}                one item with its brief
    POST   /items/{id}/rebrief        read and brief it again
    POST   /items/{id}/move           {folder}
    POST   /items/{id}/xsays          look up what X says about it (Grok x_search)
    DELETE /items/{id}
    GET    /folders                   folder names with counts
    GET    /digest?hours=24           what you saved in the last N hours, one line each, by folder

The worker briefs anything with status 'new': it reads the link itself when the browser sent no text, then makes
one ctx.llm call. It polls the database, so items saved by a CLI tool call in another process get briefed too.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Optional

from . import readers, xsays
from .brief import digest_markdown, write_brief
from .store import Store

logger = logging.getLogger(__name__)

PLUGIN = "hermes-brief"
BASE = f"/api/plugins/{PLUGIN}"
POLL_SECONDS = 8
MAX_BODY = 1_500_000
KINDS = {"page", "x_post", "youtube", "video", "pdf", "article"}


def plugin_version() -> str:
    try:
        for line in (Path(__file__).parent / "plugin.yaml").read_text().splitlines():
            if line.startswith("version:"):
                return line.split(":", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "0"


class Worker:
    def __init__(self, store: Store, llm_getter: Callable[[], Any], scope: Optional[Callable[[], Any]] = None,
                 dispatch: Optional[Callable[[str, dict], str]] = None, x_enabled: Callable[[], bool] = lambda: False,
                 x_scope: Optional[Callable[[], Any]] = None, x_profile: Callable[[], str] = lambda: ""):
        self.store = store
        self.llm_getter = llm_getter
        self.dispatch = dispatch          # ctx.dispatch_tool, for Grok's x_search ("What X says")
        self.x_enabled = x_enabled
        # x_search reads Grok credentials from the active profile scope. The user may point it at the profile that
        # has their Grok sign-in (config x_search_profile); otherwise it runs in the API server's own profile.
        self.x_scope = x_scope
        self.x_profile = x_profile
        self.wake = asyncio.Event()
        self.task: Optional[asyncio.Task] = None
        # On a multiplexed gateway a model call needs a profile's runtime scope (credentials and config are
        # per profile). The API server enters it around every request; the worker runs between requests, so it
        # copies the context of the latest request (remember_scope) or, before any request, opens the server's
        # default-profile scope itself.
        self.request_context: Optional[contextvars.Context] = None
        self.scope = scope

    def remember_scope(self) -> None:
        self.request_context = contextvars.copy_context()

    def start(self) -> None:
        if not self.task:
            self.task = asyncio.get_event_loop().create_task(self.run())

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            self.task = None

    def poke(self) -> None:
        self.wake.set()

    async def run(self) -> None:
        # Anything left mid-brief by a restart starts over.
        for item in self.store.pending(200):
            if item["status"] == "briefing":
                self.store.set_status(item["id"], "new")
        while True:
            try:
                for item in self.store.pending(5):
                    await self.brief_scoped(item)
                for item in self.store.x_pending(3):
                    await self.x_scoped(self.x_one, item)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("hermes-brief worker pass failed")
            self.wake.clear()
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=POLL_SECONDS)
            except asyncio.TimeoutError:
                pass

    async def brief_scoped(self, item: dict) -> None:
        await self.scoped(self.brief_one, item)

    async def scoped(self, fn, item: dict) -> None:
        if self.request_context is not None:
            await asyncio.get_running_loop().create_task(fn(item), context=self.request_context.copy())
            return
        cm = contextlib.nullcontext()
        if self.scope is not None:
            try:
                cm = self.scope() or contextlib.nullcontext()
            except Exception:
                cm = contextlib.nullcontext()
        with cm:
            await fn(item)

    async def brief_one(self, item: dict) -> None:
        self.store.set_status(item["id"], "briefing")
        try:
            no_transcript = item.get("kind") in ("youtube", "video") and (item.get("meta") or {}).get("transcript") == "none"
            if len(item.get("content") or "") < 200 or no_transcript:
                got = await asyncio.to_thread(readers.read, item["url"])
                if got.get("text"):
                    self.store.set_content(item["id"], content=got["text"], title=item.get("title") or got.get("title", ""),
                                           kind=got.get("kind", ""), meta=got.get("meta"))
                    item = self.store.get(item["id"], with_content=True) or item
                elif got.get("meta", {}).get("read_error"):
                    self.store.set_content(item["id"], content=item.get("content") or "", meta=got["meta"])
            llm = self.llm_getter()
            if llm is None:
                raise RuntimeError("Hermes did not give this plugin model access (ctx.llm missing)")
            brief, model = await write_brief(llm, item)
            self.store.set_brief(item["id"], brief, model=model)
            if self.dispatch is not None and self.x_enabled() and not item.get("x_status"):
                self.store.set_x(item["id"], "new")
        except Exception as exc:
            logger.info("hermes-brief: brief failed for %s: %s", item.get("url"), exc)
            self.store.set_status(item["id"], "error", error=str(exc)[:300])


    def _x_cm(self):
        try:
            return (self.x_scope() if self.x_scope is not None else None) or contextlib.nullcontext()
        except Exception:
            return contextlib.nullcontext()

    async def x_scoped(self, fn, item: dict) -> None:
        with self._x_cm():
            await fn(item)

    def x_available(self) -> dict:
        """Whether Grok's x_search can run where this worker runs; shown on /status and the Desktop card."""
        if self.dispatch is None or not self.x_enabled():
            return {"available": False, "profile": self.x_profile() or "", "reason": "off" if self.dispatch is not None else "no tool dispatch"}
        try:
            with self._x_cm():
                return {"available": xsays.available(), "profile": self.x_profile() or ""}
        except Exception as exc:
            return {"available": False, "profile": self.x_profile() or "", "reason": str(exc)[:120]}

    async def x_one(self, item: dict) -> None:
        if self.dispatch is None:
            self.store.set_x(item["id"], "unavailable", {"error": "This Hermes can't call tools from plugins."})
            return
        status, x = await asyncio.to_thread(xsays.run, self.dispatch, item["url"], item.get("title") or "")
        self.store.set_x(item["id"], status, x)


def _authorize(adapter: Any, request: Any, store: Optional[Store] = None):
    from aiohttp import web

    refuse = web.json_response({"error": "Not authorized"}, status=401, headers={"Cache-Control": "no-store"})
    if store is not None:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer hb_") and store.device_for(auth[7:].strip()):
            return None
    check = getattr(adapter, "_check_auth", None)
    if not callable(check):
        return refuse
    try:
        return check(request)
    except Exception:
        return refuse


def wire_routes(router: Any, adapter: Any, store: Store, worker: Worker, profile: str) -> None:
    from aiohttp import web

    def guarded(fn):
        async def handler(request):
            denied = _authorize(adapter, request, store)
            if denied is not None:
                return denied
            worker.remember_scope()
            try:
                out = await fn(request)
            except web.HTTPException:
                raise
            except ValueError as exc:
                return web.json_response({"error": str(exc)}, status=400)
            except Exception as exc:
                logger.exception("hermes-brief route failed")
                return web.json_response({"error": f"{type(exc).__name__}"}, status=500)
            return out if isinstance(out, web.StreamResponse) else web.json_response(out, headers={"Cache-Control": "no-store"})
        return handler

    async def status(_req):
        folders = store.folders()
        return {"plugin": PLUGIN, "version": plugin_version(), "profile": profile,
                "items": sum(f["count"] for f in folders), "folders": folders, "time": time.time(),
                "x_search": worker.x_available()}

    async def save(req):
        if (req.content_length or 0) > MAX_BODY:
            raise ValueError("too large")
        body = await req.json()
        url = str(body.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError("url must be an http(s) link")
        kind = str(body.get("kind") or readers.kind_of(url))
        meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
        for k in ("selection", "note"):
            if body.get(k):
                meta[k] = str(body[k])[:4000]
        item = store.save(url=url, title=str(body.get("title") or "")[:300], kind=kind if kind in KINDS else "page",
                          folder=str(body.get("folder") or ""), source=str(body.get("source") or "button")[:20],
                          content=str(body.get("content") or ""), meta=meta)
        worker.poke()
        return item

    async def search(req):
        q = req.query
        days = float(q.get("days") or 0)
        since = time.time() - days * 86400 if days > 0 else 0
        return {"items": store.search(query=q.get("q", ""), folder=q.get("folder", ""), since=since, limit=int(q.get("limit") or 50))}

    async def lookup(req):
        item = store.by_url(req.query.get("url", ""))
        return {"item": item}

    async def one(req):
        item = store.get(req.match_info["id"])
        if not item:
            raise web.HTTPNotFound()
        return item

    async def rebrief(req):
        item_id = req.match_info["id"]
        if not store.get(item_id):
            raise web.HTTPNotFound()
        store.set_status(item_id, "new")
        worker.poke()
        return store.get(item_id)

    async def ask_x(req):
        item_id = req.match_info["id"]
        if not store.get(item_id):
            raise web.HTTPNotFound()
        store.set_x(item_id, "new")
        worker.poke()
        return store.get(item_id)

    async def move(req):
        body = await req.json()
        item = store.move(req.match_info["id"], str(body.get("folder") or ""))
        if not item:
            raise web.HTTPNotFound()
        return item

    async def delete(req):
        return {"deleted": store.delete(req.match_info["id"])}

    async def folders(_req):
        return {"folders": store.folders()}

    async def pair(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        token = store.finish_pairing(str(body.get("code") or ""), str(body.get("name") or "Chrome"))
        if not token:
            return web.json_response({"error": "That code is wrong or expired. Get a new one on the Briefs page."}, status=403)
        return web.json_response({"token": token}, headers={"Cache-Control": "no-store"})

    async def digest(req):
        hours = float(req.query.get("hours") or 24)
        items = store.search(since=time.time() - hours * 3600, limit=100)
        return {"hours": hours, "count": len(items), "markdown": digest_markdown(items, hours)}

    router.add_post(f"{BASE}/pair", pair)
    router.add_get(f"{BASE}/digest", guarded(digest))
    router.add_get(f"{BASE}/status", guarded(status))
    router.add_post(f"{BASE}/items", guarded(save))
    router.add_get(f"{BASE}/items", guarded(search))
    router.add_get(f"{BASE}/lookup", guarded(lookup))
    router.add_get(f"{BASE}/items/{{id}}", guarded(one))
    router.add_post(f"{BASE}/items/{{id}}/rebrief", guarded(rebrief))
    router.add_post(f"{BASE}/items/{{id}}/move", guarded(move))
    router.add_post(f"{BASE}/items/{{id}}/xsays", guarded(ask_x))
    router.add_delete(f"{BASE}/items/{{id}}", guarded(delete))
    router.add_get(f"{BASE}/folders", guarded(folders))
