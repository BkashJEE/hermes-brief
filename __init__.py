"""Hermes Brief: save pages, X posts and videos from Chrome; Hermes reads each one and writes you a brief.

Pieces:
- extension/   Chrome extension: save button, right-click "Save link to Hermes", a watched "Hermes" bookmarks
               folder, and a side panel to ask Hermes about the page you're on.
- service.py   routes on the Hermes API server the extension talks to + the background brief worker.
- tools.py     brief_save / brief_search / brief_get for any chat.
- desktop/     the Briefs page in Hermes Desktop.
"""

from __future__ import annotations

import logging

from . import service
from .store import Store
from .tools import SCHEMA_DIGEST, SCHEMA_GET, SCHEMA_SAVE, SCHEMA_SEARCH, Tools

logger = logging.getLogger(__name__)

_store = None


def _open_store() -> Store:
    """One library for all your profiles: a link saved from Chrome is there whichever bot you ask.

    It lives in the root profile's plugin data (<hermes root>/plugin-data/hermes-brief/library.db), because on a
    multiplexed gateway the API server the extension talks to belongs to the default profile while chats run in
    any profile. Falls back to this profile's plugin_db() when the root can't be resolved.
    """
    global _store
    if _store is None:
        try:
            import sqlite3
            from hermes_constants import get_default_hermes_root
            folder = get_default_hermes_root() / "plugin-data" / service.PLUGIN
            folder.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(folder / "library.db"), check_same_thread=False, timeout=15)
            conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            from plugins.plugin_storage import plugin_db
            conn = plugin_db(service.PLUGIN)
        _store = Store(conn)
    return _store


def _config(ctx, key, default):
    try:
        return ctx.get_config(key, default=default)
    except Exception:
        return default


def register(ctx) -> None:
    llm_getter = lambda: getattr(ctx, "llm", None)
    tools = Tools(_open_store, llm_getter)
    ctx.register_tool(name="brief_save", toolset=service.PLUGIN, schema=SCHEMA_SAVE, handler=tools.save,
                      description=SCHEMA_SAVE["description"], emoji="🔖")
    ctx.register_tool(name="brief_search", toolset=service.PLUGIN, schema=SCHEMA_SEARCH, handler=tools.search,
                      description=SCHEMA_SEARCH["description"], emoji="🔎")
    ctx.register_tool(name="brief_digest", toolset=service.PLUGIN, schema=SCHEMA_DIGEST, handler=tools.digest,
                      description=SCHEMA_DIGEST["description"], emoji="🗞️")
    ctx.register_tool(name="brief_get", toolset=service.PLUGIN, schema=SCHEMA_GET, handler=tools.get,
                      description=SCHEMA_GET["description"], emoji="📰")

    register_platform = getattr(ctx, "register_platform_handler", None)
    if not callable(register_platform):
        return
    profile = getattr(ctx, "profile_name", "default") or "default"

    def wire(native, adapter) -> None:
        router = getattr(native, "router", None)
        if router is None:
            return
        store = _open_store()
        scope_fn = getattr(adapter, "_profile_scope", None)
        dispatch = getattr(ctx, "dispatch_tool", None)
        worker = service.Worker(store, llm_getter, scope=(lambda: scope_fn(None)) if callable(scope_fn) else None,
                                dispatch=(lambda name, args: dispatch(name, args)) if callable(dispatch) else None,
                                x_enabled=lambda: bool(_config(ctx, "what_x_says", True)),
                                x_scope=(lambda: scope_fn(str(_config(ctx, "x_search_profile", "") or "").strip() or None)) if callable(scope_fn) else None,
                                x_profile=lambda: str(_config(ctx, "x_search_profile", "") or "").strip())
        service.wire_routes(router, adapter, store, worker, profile)

        async def start(_app):
            worker.start()

        async def stop(_app):
            await worker.stop()

        try:
            native.on_startup.append(start)
            native.on_cleanup.append(stop)
        except Exception:  # app already running: start on the running loop
            try:
                worker.start()
            except Exception:
                logger.info("hermes-brief: worker not started", exc_info=True)

    try:
        register_platform("api_server", wire)
    except Exception as exc:  # e.g. plugin host isolation refuses platform handlers
        logger.info("hermes-brief: API routes not registered (%s); chat tools still work", exc)
