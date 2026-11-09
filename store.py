"""Saved links and their briefs, in the plugin's own SQLite database.

One row per saved URL (the canonical URL is unique, so saving the same page twice updates it instead of
duplicating it). Content is the text we read from the page, post or video, capped so one huge page can't
fill the database. The brief is the model's JSON answer.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
import uuid
from typing import Any, Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MAX_CONTENT = 60_000          # characters of page text kept per item
DEFAULT_FOLDER = "Inbox"

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,
  url TEXT NOT NULL,
  canonical TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL DEFAULT 'page',
  folder TEXT NOT NULL DEFAULT 'Inbox',
  source TEXT NOT NULL DEFAULT 'button',
  saved_at REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'new',
  content TEXT NOT NULL DEFAULT '',
  meta TEXT NOT NULL DEFAULT '{}',
  brief TEXT,
  error TEXT,
  briefed_at REAL
);
CREATE INDEX IF NOT EXISTS items_folder ON items(folder, saved_at);
CREATE INDEX IF NOT EXISTS items_saved ON items(saved_at);
CREATE TABLE IF NOT EXISTS devices (
  id TEXT PRIMARY KEY,
  token_sha256 TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL DEFAULT 'Chrome',
  created REAL NOT NULL,
  last_seen REAL
);
CREATE TABLE IF NOT EXISTS pair_codes (
  code_sha256 TEXT PRIMARY KEY,
  expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS pair_state (
  k TEXT PRIMARY KEY,
  v INTEGER NOT NULL
);
"""

PAIR_TTL = 300          # a pairing code works for 5 minutes, once
PAIR_MAX_TRIES = 5      # five wrong codes cancel every open code

# Query parameters that only track where a click came from.
_TRACKING = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id", "fbclid", "gclid",
             "igshid", "mc_cid", "mc_eid", "ref_src", "ref_url", "si", "s", "t", "feature", "pp"}


def canonical_url(url: str) -> str:
    """The same page saved twice should be one item: drop tracking params, fragments and x.com/twitter.com aliases."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host in ("twitter.com", "mobile.twitter.com", "mobile.x.com"):
        host = "x.com"
    if host == "m.youtube.com":
        host = "youtube.com"
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in _TRACKING]
    if host == "youtu.be" and parts.path.strip("/"):
        host, path = "youtube.com", "/watch"
        query = [("v", parts.path.strip("/"))] + query
    else:
        path = parts.path.rstrip("/") or "/"
    if host == "x.com":                      # x.com/user/status/ID/photo/1 -> the post itself
        segs = path.split("/")
        if len(segs) > 3 and segs[2] == "status":
            path = "/".join(segs[:4])
    return urlunsplit(((parts.scheme or "https").lower(), host, path, urlencode(query), ""))


class Store:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            cols = {r[1] for r in self.conn.execute("PRAGMA table_info(items)")}
            if "x_says" not in cols:      # added in 0.3.0
                self.conn.execute("ALTER TABLE items ADD COLUMN x_says TEXT")
                self.conn.execute("ALTER TABLE items ADD COLUMN x_status TEXT NOT NULL DEFAULT ''")
            self.conn.commit()

    # ── writes ─────────────────────────────────────────────────────────────
    def save(self, *, url: str, title: str = "", kind: str = "page", folder: str = "", source: str = "button",
             content: str = "", meta: Optional[dict] = None) -> dict:
        canon = canonical_url(url)
        folder = (folder or "").strip()[:60] or None
        content = (content or "")[:MAX_CONTENT]
        now = time.time()
        with self.lock:
            row = self.conn.execute("SELECT * FROM items WHERE canonical = ?", (canon,)).fetchone()
            if row:
                merged = {**json.loads(row["meta"] or "{}"), **(meta or {})}
                # New content from the browser beats what we had; an empty save never wipes it.
                new_content = content if len(content) > 40 else row["content"]
                changed = new_content != row["content"]
                self.conn.execute(
                    "UPDATE items SET title = ?, kind = ?, folder = ?, content = ?, meta = ?, saved_at = ?,"
                    " status = CASE WHEN ? THEN 'new' ELSE status END WHERE id = ?",
                    (title or row["title"], kind if kind != "page" else row["kind"], folder or row["folder"],
                     new_content, json.dumps(merged), now, changed, row["id"]))
                item_id = row["id"]
            else:
                item_id = uuid.uuid4().hex[:12]
                self.conn.execute(
                    "INSERT INTO items (id, url, canonical, title, kind, folder, source, saved_at, content, meta)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (item_id, url.strip(), canon, title, kind, folder or DEFAULT_FOLDER, source, now, content,
                     json.dumps(meta or {})))
            self.conn.commit()
        return self.get(item_id)

    def set_status(self, item_id: str, status: str, *, error: Optional[str] = None) -> None:
        with self.lock:
            self.conn.execute("UPDATE items SET status = ?, error = ? WHERE id = ?", (status, error, item_id))
            self.conn.commit()

    def set_content(self, item_id: str, *, content: str, title: str = "", kind: str = "", meta: Optional[dict] = None) -> None:
        with self.lock:
            row = self.conn.execute("SELECT title, kind, meta FROM items WHERE id = ?", (item_id,)).fetchone()
            if not row:
                return
            merged = {**json.loads(row["meta"] or "{}"), **(meta or {})}
            self.conn.execute("UPDATE items SET content = ?, title = ?, kind = ?, meta = ? WHERE id = ?",
                              (content[:MAX_CONTENT], title or row["title"], kind or row["kind"], json.dumps(merged), item_id))
            self.conn.commit()

    def set_brief(self, item_id: str, brief: dict, *, model: str = "") -> None:
        with self.lock:
            self.conn.execute("UPDATE items SET brief = ?, status = 'done', error = NULL, briefed_at = ?,"
                              " meta = json_set(meta, '$.model', ?) WHERE id = ?",
                              (json.dumps(brief), time.time(), model, item_id))
            self.conn.commit()

    def set_x(self, item_id: str, status: str, x_says: Optional[dict] = None) -> None:
        """status: new (wanted) | done | none (nobody on X talks about it) | unavailable (no Grok access) | error"""
        with self.lock:
            if x_says is None:
                self.conn.execute("UPDATE items SET x_status = ? WHERE id = ?", (status, item_id))
            else:
                self.conn.execute("UPDATE items SET x_status = ?, x_says = ? WHERE id = ?", (status, json.dumps(x_says), item_id))
            self.conn.commit()

    def x_pending(self, limit: int = 5) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM items WHERE x_status = 'new' AND status = 'done' ORDER BY saved_at LIMIT ?", (limit,))
        return [_row(r, False) for r in rows]

    def move(self, item_id: str, folder: str) -> Optional[dict]:
        folder = folder.strip()[:60] or DEFAULT_FOLDER
        with self.lock:
            self.conn.execute("UPDATE items SET folder = ? WHERE id = ?", (folder, item_id))
            self.conn.commit()
        return self.get(item_id)

    def delete(self, item_id: str) -> bool:
        with self.lock:
            cur = self.conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
            self.conn.commit()
        return cur.rowcount > 0

    # ── pairing (the Chrome extension gets its own token; no API key in the browser) ──────────────
    def start_pairing(self) -> dict:
        code = f"{secrets.randbelow(1_000_000):06d}"
        now = time.time()
        with self.lock:
            self.conn.execute("DELETE FROM pair_codes WHERE expires < ?", (now,))
            self.conn.execute("INSERT OR REPLACE INTO pair_codes VALUES (?, ?)", (_sha(code), now + PAIR_TTL))
            self.conn.execute("INSERT OR REPLACE INTO pair_state VALUES ('tries', 0)")
            self.conn.commit()
        return {"code": code, "expires_in": PAIR_TTL}

    def finish_pairing(self, code: str, name: str = "Chrome") -> Optional[str]:
        """Swap a valid code for a long-lived device token (returned once, stored only as a hash)."""
        code = "".join(ch for ch in str(code) if ch.isdigit())
        now = time.time()
        with self.lock:
            row = self.conn.execute("SELECT expires FROM pair_codes WHERE code_sha256 = ?", (_sha(code),)).fetchone()
            if not row or row["expires"] < now:
                tries = (self.conn.execute("SELECT v FROM pair_state WHERE k = 'tries'").fetchone() or {"v": 0})["v"] + 1
                if tries >= PAIR_MAX_TRIES:
                    self.conn.execute("DELETE FROM pair_codes")
                    tries = 0
                self.conn.execute("INSERT OR REPLACE INTO pair_state VALUES ('tries', ?)", (tries,))
                self.conn.commit()
                return None
            self.conn.execute("DELETE FROM pair_codes WHERE code_sha256 = ?", (_sha(code),))
            token = "hb_" + secrets.token_urlsafe(32)
            self.conn.execute("INSERT INTO devices (id, token_sha256, name, created) VALUES (?, ?, ?, ?)",
                              (uuid.uuid4().hex[:10], _sha(token), (name or "Chrome")[:60], now))
            self.conn.commit()
        return token

    def device_for(self, token: str) -> Optional[str]:
        if not token or not token.startswith("hb_"):
            return None
        with self.lock:
            row = self.conn.execute("SELECT id FROM devices WHERE token_sha256 = ?", (_sha(token),)).fetchone()
            if row:
                self.conn.execute("UPDATE devices SET last_seen = ? WHERE id = ?", (time.time(), row["id"]))
                self.conn.commit()
        return row["id"] if row else None

    def devices(self) -> list[dict]:
        rows = self.conn.execute("SELECT id, name, created, last_seen FROM devices ORDER BY created DESC")
        return [dict(r) for r in rows]

    def forget_device(self, device_id: str) -> bool:
        with self.lock:
            cur = self.conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
            self.conn.commit()
        return cur.rowcount > 0

    # ── reads ──────────────────────────────────────────────────────────────
    def get(self, item_id: str, *, with_content: bool = False) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return _row(row, with_content) if row else None

    def by_url(self, url: str) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM items WHERE canonical = ?", (canonical_url(url),)).fetchone()
        return _row(row, False) if row else None

    def pending(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM items WHERE status IN ('new', 'briefing') ORDER BY saved_at LIMIT ?", (limit,))
        return [_row(r, True) for r in rows]

    def search(self, *, query: str = "", folder: str = "", since: float = 0, limit: int = 50) -> list[dict]:
        sql, args = "SELECT * FROM items WHERE saved_at >= ?", [since]
        if folder:
            sql += " AND folder = ?"
            args.append(folder)
        for word in [w for w in query.lower().split() if w][:6]:
            sql += " AND (lower(title) LIKE ? OR lower(url) LIKE ? OR lower(coalesce(brief, '')) LIKE ? OR lower(content) LIKE ?)"
            args += [f"%{word}%"] * 4
        sql += " ORDER BY saved_at DESC LIMIT ?"
        args.append(max(1, min(int(limit), 200)))
        return [_row(r, False) for r in self.conn.execute(sql, args)]

    def folders(self) -> list[dict]:
        rows = self.conn.execute("SELECT folder, count(*) AS n, max(saved_at) AS last FROM items GROUP BY folder ORDER BY last DESC")
        return [{"name": r["folder"], "count": r["n"], "last": r["last"]} for r in rows]


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _row(row: sqlite3.Row, with_content: bool) -> dict:
    out = {k: row[k] for k in row.keys() if k not in ("content", "meta", "brief", "x_says")}
    out["x_says"] = json.loads(row["x_says"]) if "x_says" in row.keys() and row["x_says"] else None
    out["meta"] = json.loads(row["meta"] or "{}")
    out["brief"] = json.loads(row["brief"]) if row["brief"] else None
    out["has_content"] = bool(row["content"])
    if with_content:
        out["content"] = row["content"]
    return out


def iter_ids(items: Iterable[dict]) -> list[str]:
    return [i["id"] for i in items]
