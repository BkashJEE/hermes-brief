"""Chat tools: save a link and get its brief, search what you saved, read one brief."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from . import readers
from .brief import brief_markdown, build_input, BRIEF_SCHEMA, INSTRUCTIONS

SCHEMA_SAVE = {
    "name": "brief_save",
    "description": "Save a link (web page, X post, YouTube or other video) to Hermes Brief and return its brief. "
                   "Use when the user shares a link and wants it saved, summarised or kept for later.",
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The http(s) link."},
            "folder": {"type": "string", "description": "Folder to save into, e.g. 'AI & agents'. Default: Inbox."},
            "note": {"type": "string", "description": "Optional note from the user about why they saved it."},
        },
        "required": ["url"],
        "additionalProperties": False,
    },
}

SCHEMA_SEARCH = {
    "name": "brief_search",
    "description": "Search the links the user saved to Hermes Brief (from the browser extension, Chrome's 'Hermes' "
                   "bookmarks folder or chat) and return their briefs. Use for 'what did I save about X', "
                   "'what did I bookmark this week', 'my saved videos'.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Words to match in title, URL, brief or text. Empty = everything."},
            "folder": {"type": "string", "description": "Only this folder."},
            "days": {"type": "number", "description": "Only items saved in the last N days."},
            "limit": {"type": "integer", "description": "Max items (default 10, max 30)."},
        },
        "additionalProperties": False,
    },
}

SCHEMA_GET = {
    "name": "brief_get",
    "description": "Read one saved item's full brief, and optionally the text that was read from it.",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "include_text": {"type": "boolean", "description": "Also return up to 12,000 characters of the page/transcript text."},
        },
        "required": ["id"],
        "additionalProperties": False,
    },
}


class Tools:
    def __init__(self, store_getter, llm_getter):
        self.store = store_getter
        self.llm = llm_getter

    def save(self, args: dict | None = None, **_: Any) -> str:
        a = args or {}
        url = str(a.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            return json.dumps({"error": "url must be an http(s) link"})
        store = self.store()
        meta = {"note": a["note"]} if a.get("note") else {}
        item = store.save(url=url, folder=str(a.get("folder") or ""), source="chat", kind=readers.kind_of(url), meta=meta)
        got = readers.read(url)
        if got.get("text"):
            store.set_content(item["id"], content=got["text"], title=got.get("title", ""), kind=got.get("kind", ""), meta=got.get("meta"))
        item = store.get(item["id"], with_content=True)
        llm = self.llm()
        if llm is None:
            return json.dumps({"saved": True, "id": item["id"], "brief": None, "note": "Saved; no model access for a brief."})
        store.set_status(item["id"], "briefing")
        try:
            result = llm.complete_structured(instructions=INSTRUCTIONS, input=[{"type": "text", "text": build_input(item)}],
                                             json_schema=BRIEF_SCHEMA, purpose="hermes-brief.brief", temperature=0.2, max_tokens=900)
            brief = result.parsed if isinstance(getattr(result, "parsed", None), dict) else None
            if not brief:
                raise RuntimeError("the model did not return a brief")
            if item.get("kind") not in ("youtube", "video"):
                brief.pop("timestamps", None)
            store.set_brief(item["id"], brief, model=str(getattr(result, "model", "") or ""))
        except Exception as exc:
            store.set_status(item["id"], "error", error=str(exc)[:300])
        item = store.get(item["id"])
        return json.dumps({"id": item["id"], "folder": item["folder"], "status": item["status"], "brief_markdown": brief_markdown(item)})

    def search(self, args: dict | None = None, **_: Any) -> str:
        a = args or {}
        days = float(a.get("days") or 0)
        items = self.store().search(query=str(a.get("query") or ""), folder=str(a.get("folder") or ""),
                                    since=time.time() - days * 86400 if days > 0 else 0,
                                    limit=max(1, min(int(a.get("limit") or 10), 30)))
        return json.dumps({"count": len(items), "items": [
            {"id": i["id"], "folder": i["folder"], "kind": i["kind"], "saved": time.strftime("%Y-%m-%d %H:%M", time.localtime(i["saved_at"])),
             "status": i["status"], "brief_markdown": brief_markdown(i)} for i in items]})

    def get(self, args: dict | None = None, **_: Any) -> str:
        a = args or {}
        item = self.store().get(str(a.get("id") or ""), with_content=bool(a.get("include_text")))
        if not item:
            return json.dumps({"error": "no saved item with that id"})
        out = {"id": item["id"], "url": item["url"], "title": item["title"], "folder": item["folder"], "status": item["status"],
               "brief": item["brief"], "brief_markdown": brief_markdown(item)}
        if a.get("include_text"):
            out["text"] = (item.get("content") or "")[:12000]
        return json.dumps(out)
