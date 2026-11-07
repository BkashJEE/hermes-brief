"""Read a saved link when the browser didn't send its text (a right-clicked link, a chat `brief_save`, a bookmark).

Standard library only, plus `yt-dlp` for video transcripts when it is installed. Every reader returns
{"kind", "title", "text", "meta"} and never raises: a failure comes back as empty text plus meta["read_error"].

- X posts: X's public embed endpoint (cdn.syndication.twimg.com), the same data an embedded post shows.
- YouTube and other videos: yt-dlp subtitles (manual first, then automatic) with timestamps.
- Everything else: the page's HTML, reduced to readable text (title, description, article/main body).
"""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import tempfile
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36 HermesBrief/0.1"
TIMEOUT = 20
MAX_BYTES = 3_000_000


def kind_of(url: str) -> str:
    p = urlsplit(url)
    host = (p.hostname or "").lower().removeprefix("www.")
    if host in ("x.com", "twitter.com", "mobile.twitter.com") and "/status/" in p.path:
        return "x_post"
    if host in ("youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"):
        return "youtube"
    if host in ("vimeo.com", "loom.com", "tiktok.com") or p.path.lower().endswith((".mp4", ".webm")):
        return "video"
    return "page"


def read(url: str) -> dict:
    k = kind_of(url)
    try:
        if k == "x_post":
            return read_x_post(url)
        if k in ("youtube", "video"):
            return read_video(url, k)
        return read_page(url)
    except Exception as exc:  # readers never raise
        return {"kind": k, "title": "", "text": "", "meta": {"read_error": f"{type(exc).__name__}: {exc}"[:300]}}


# ── X posts ──────────────────────────────────────────────────────────────────
def _post_id(url: str) -> str:
    m = re.search(r"/status(?:es)?/(\d+)", url)
    return m.group(1) if m else ""


def read_x_post(url: str) -> dict:
    pid = _post_id(url)
    if not pid:
        return read_page(url)
    data = json.loads(_get(f"https://cdn.syndication.twimg.com/tweet-result?id={pid}&token=4"))
    user = data.get("user") or {}
    lines = [f"Post by {user.get('name', '')} (@{user.get('screen_name', '')}), {data.get('created_at', '')}:", data.get("text", "")]
    q = data.get("quoted_tweet")
    if q:
        lines += ["", f"It quotes @{(q.get('user') or {}).get('screen_name', '')}:", q.get("text", "")]
    for m in data.get("mediaDetails") or []:
        if m.get("type") == "video":
            secs = round((m.get("video_info") or {}).get("duration_millis", 0) / 1000)
            lines.append(f"[Attached video, {secs} s]")
        elif m.get("type") == "photo":
            lines.append("[Attached image]" + (f": {m['ext_alt_text']}" if m.get("ext_alt_text") else ""))
    card = (data.get("card") or {}).get("binding_values") or {}
    title = (card.get("title") or {}).get("string_value")
    if title:
        lines.append(f"[Link card: {title} — {(card.get('description') or {}).get('string_value', '')}]")
    meta = {"author": user.get("screen_name", ""), "likes": data.get("favorite_count"), "replies": data.get("conversation_count"),
            "posted_at": data.get("created_at")}
    return {"kind": "x_post", "title": f"@{user.get('screen_name', '')}: {data.get('text', '')[:80]}", "text": "\n".join(lines), "meta": meta}


# ── videos ───────────────────────────────────────────────────────────────────
def read_video(url: str, kind: str) -> dict:
    ytdlp = shutil.which("yt-dlp")
    if not ytdlp:
        page = read_page(url)
        page["kind"] = kind
        page["meta"]["transcript"] = "none (yt-dlp not installed)"
        return page
    with tempfile.TemporaryDirectory() as tmp:
        info = json.loads(subprocess.run(
            [ytdlp, "--skip-download", "--dump-single-json", "--no-warnings", "--no-playlist", url],
            capture_output=True, text=True, timeout=60).stdout or "{}")
        subprocess.run(
            [ytdlp, "--skip-download", "--no-warnings", "--no-playlist", "--write-subs", "--write-auto-subs",
             "--sub-langs", "en.*,en", "--sub-format", "vtt", "-o", str(Path(tmp) / "v.%(ext)s"), url],
            capture_output=True, text=True, timeout=90)
        subs = sorted(Path(tmp).glob("*.vtt"), key=lambda p: (".en-orig." in p.name, "auto" in p.name))
        transcript = vtt_to_text(subs[0].read_text(errors="ignore")) if subs else ""
    title = info.get("title") or ""
    head = [f"Video: {title}", f"Channel: {info.get('uploader') or info.get('channel') or ''}",
            f"Length: {_hms(info.get('duration') or 0)}", "", (info.get("description") or "")[:3000]]
    text = "\n".join(head) + ("\n\nTranscript (timestamps in [m:ss]):\n" + transcript if transcript else "\n\n(No transcript available.)")
    meta = {"channel": info.get("uploader") or info.get("channel"), "duration": info.get("duration"),
            "views": info.get("view_count"), "transcript": "yes" if transcript else "none"}
    return {"kind": kind, "title": title, "text": text, "meta": meta}


def vtt_to_text(vtt: str) -> str:
    """WebVTT -> '[m:ss] line' rows, one per ~20 s, with the rolling-caption duplicates removed."""
    out, seen, last_mark = [], set(), -99.0
    cur_t = 0.0
    for line in vtt.splitlines():
        m = re.match(r"(\d+):(\d+):(\d+)[.,]\d+\s+-->", line) or re.match(r"(\d+):(\d+)[.,]\d+\s+-->", line)
        if m:
            g = [int(x) for x in m.groups()]
            cur_t = g[0] * 3600 + g[1] * 60 + g[2] if len(g) == 3 else g[0] * 60 + g[1]
            continue
        text = re.sub(r"<[^>]+>", "", line).strip()
        if not text or text.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")) or text in seen:
            continue
        seen.add(text)
        if cur_t - last_mark >= 20:
            out.append(f"\n[{_hms(cur_t)}] ")
            last_mark = cur_t
        out.append(text + " ")
    return "".join(out).strip()


def _hms(secs: float) -> str:
    secs = int(secs)
    h, rest = divmod(secs, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ── web pages ────────────────────────────────────────────────────────────────
class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form", "button", "iframe"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "blockquote", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts: list[str] = []
        self.title = ""
        self.in_title = False
        self.meta: dict[str, str] = {}
        self.main_depth = 0
        self.main_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key in ("og:title", "og:description", "description", "author", "article:published_time", "og:site_name"):
                self.meta[key] = a.get("content") or ""
        if tag in self.SKIP:
            self.skip += 1
        if tag in ("article", "main") or self.main_depth:
            self.main_depth += 1
        if tag in self.BLOCK:
            self._emit("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if self.main_depth:
            self.main_depth -= 1

    def handle_data(self, data):
        if self.in_title:
            self.title += data
            return
        if not self.skip:
            self._emit(data)

    def _emit(self, s):
        self.parts.append(s)
        if self.main_depth:
            self.main_parts.append(s)


def html_to_text(raw: str) -> tuple[str, str, dict]:
    p = _Text()
    p.feed(raw)
    body = "".join(p.main_parts) if len("".join(p.main_parts).strip()) > 400 else "".join(p.parts)
    body = re.sub(r"[ \t\r\f\v]+", " ", body)
    body = re.sub(r"\n\s*\n+", "\n\n", body).strip()
    title = html.unescape(p.meta.get("og:title") or p.title).strip()
    return title, body, p.meta


def read_page(url: str) -> dict:
    raw = _get(url)
    title, body, meta = html_to_text(raw)
    desc = meta.get("og:description") or meta.get("description") or ""
    text = "\n".join(x for x in [title, desc, "", body] if x is not None)
    m = {k.split(":")[-1]: v for k, v in meta.items() if k in ("author", "article:published_time", "og:site_name") and v}
    return {"kind": "page", "title": title, "text": text, "meta": m}


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = r.read(MAX_BYTES)
        charset = r.headers.get_content_charset() or "utf-8"
    return data.decode(charset, errors="replace")


def youtube_id(url: str) -> str:
    p = urlsplit(url)
    if (p.hostname or "").endswith("youtu.be"):
        return p.path.strip("/")
    return (parse_qs(p.query).get("v") or [""])[0]
