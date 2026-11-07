"""Briefs page backend for Hermes Desktop: ``/api/plugins/hermes-brief/`` on the Desktop/dashboard server.

Reads and edits the same library the extension saves into (store.py, <hermes root>/plugin-data/hermes-brief).
"Brief again" only marks an item new; the gateway's brief worker picks it up within a few seconds.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import time
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Query

router = APIRouter()
_HERE = Path(__file__).resolve().parent.parent
_store = None


def _load(name: str):
    key = f"hermes_brief_dash_{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, _HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


def store():
    global _store
    if _store is None:
        Store = _load("store").Store
        try:
            from hermes_constants import get_default_hermes_root
            folder = get_default_hermes_root() / "plugin-data" / "hermes-brief"
        except Exception:
            folder = Path.home() / ".hermes" / "plugin-data" / "hermes-brief"
        folder.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(folder / "library.db"), check_same_thread=False, timeout=15)
        conn.execute("PRAGMA journal_mode=WAL")
        _store = Store(conn)
    return _store


@router.get("/items")
def items(q: str = "", folder: str = "", days: float = 0, limit: int = Query(100, le=200)):
    since = time.time() - days * 86400 if days > 0 else 0
    return {"items": store().search(query=q, folder=folder, since=since, limit=limit)}


@router.get("/items/{item_id}")
def item(item_id: str, text: bool = False):
    got = store().get(item_id, with_content=text)
    if not got:
        raise HTTPException(404, "no such item")
    if text and got.get("content"):
        got["content"] = got["content"][:20000]
    return got


@router.get("/folders")
def folders():
    return {"folders": store().folders()}


@router.post("/items/{item_id}/move")
def move(item_id: str, body: dict = Body(...)):
    got = store().move(item_id, str(body.get("folder") or ""))
    if not got:
        raise HTTPException(404, "no such item")
    return got


@router.post("/items/{item_id}/rebrief")
def rebrief(item_id: str):
    if not store().get(item_id):
        raise HTTPException(404, "no such item")
    store().set_status(item_id, "new")
    return store().get(item_id)


@router.delete("/items/{item_id}")
def delete(item_id: str):
    return {"deleted": store().delete(item_id)}


@router.post("/items")
def save(body: dict = Body(...)):
    url = str(body.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "url must be an http(s) link")
    readers = _load("readers")
    return store().save(url=url, folder=str(body.get("folder") or ""), source="desktop", kind=readers.kind_of(url))
