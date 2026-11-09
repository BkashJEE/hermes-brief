"""'What X says': the conversation on X around a saved link, through Hermes's own Grok x_search tool.

The plugin never handles an xAI key: it calls the built-in x_search tool with ctx.dispatch_tool, which uses
whatever Grok access Hermes has (SuperGrok sign-in via `hermes auth add xai-oauth`, or XAI_API_KEY).
Grok is asked for a fixed, short format so no second model call is needed to structure it.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any, Callable

QUERY = """Find what people on X are saying about this link or topic.
Link: {url}
Title: {title}
Look for X posts from the last 30 days that share, quote or discuss it.
Answer in exactly this format and nothing else:
SUMMARY: one or two plain sentences on the overall reaction.
TAKES:
- @handle: a one-line gist of their take
(up to 5 takes, the most notable or most engaged first)
PUSHBACK: one sentence on criticism or doubts, or "none found".
NOTABLE: comma-separated @handles of well-known accounts talking about it, or "none".
If nobody on X is discussing it, answer only: NONE"""


def available() -> bool:
    """True when Hermes has Grok credentials in the current profile scope (SuperGrok sign-in or XAI_API_KEY)."""
    try:
        from tools.x_search_tool import check_x_search_requirements
        return bool(check_x_search_requirements())
    except Exception:
        return False


def run(dispatch: Callable[[str, dict], str], url: str, title: str) -> tuple[str, dict]:
    """Returns (status, x_says). status: done | none | unavailable | error. Never raises."""
    try:
        raw = dispatch("x_search", {"query": QUERY.format(url=url, title=title or url),
                                    "from_date": (date.today() - timedelta(days=30)).isoformat()})
    except Exception as exc:
        return "error", {"error": f"{type(exc).__name__}: {exc}"[:300]}
    try:
        data = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except Exception:
        data = {"answer": str(raw)}
    if not data.get("success", True) or data.get("error"):
        msg = str(data.get("error") or data.get("message") or "x_search failed")
        if re.search(r"credential|auth add xai|XAI_API_KEY|not available|unknown tool|disabled", msg, re.I):
            return "unavailable", {"error": "Connect Grok to see what X says: run `hermes auth add xai-oauth` in this profile, "
                                            "or set the plugin's x_search_profile to the profile that has your Grok sign-in."}
        return "error", {"error": msg[:300]}
    parsed = parse(data.get("answer") or "")
    links = _post_links(data)
    parsed["sources"] = links[:8]
    for t in parsed.get("takes", []):            # link each take to that handle's post when Grok cited it
        t["url"] = next((u for u in links if f"/{t['handle'].lower()}/status/" in u.lower()), "")
    parsed["degraded"] = bool(data.get("degraded")) or not links
    if parsed.get("none"):
        return "none", parsed
    return "done", parsed


def parse(answer: str) -> dict:
    text = answer.strip()
    if re.fullmatch(r"\W*NONE\W*", text, re.I) or not text:
        return {"none": True, "summary": "Nobody on X seems to be talking about this yet.", "takes": [], "pushback": "", "notable": []}
    def field(name):
        m = re.search(rf"^\s*{name}\s*:\s*(.+?)(?=^\s*(?:SUMMARY|TAKES|PUSHBACK|NOTABLE)\s*:|\Z)", text, re.I | re.S | re.M)
        return m.group(1).strip() if m else ""
    takes = []
    for line in field("TAKES").splitlines():
        m = re.match(r"\s*[-•*]\s*@?([A-Za-z0-9_]{1,15})\s*[:—-]\s*(.+)", line)
        if m:
            takes.append({"handle": m.group(1), "gist": _strip_cites(m.group(2))})
    pushback = _strip_cites(field("PUSHBACK"))
    notable = [h.strip().lstrip("@") for h in re.split(r"[,\s]+", field("NOTABLE")) if re.fullmatch(r"@?[A-Za-z0-9_]{1,15}", h.strip())]
    summary = _strip_cites(field("SUMMARY")) or _strip_cites(text.split("\n")[0])
    return {"summary": summary, "takes": takes[:5], "pushback": "" if re.match(r"none", pushback, re.I) else pushback,
            "notable": [] if [n.lower() for n in notable] == ["none"] else notable[:8]}


def _strip_cites(s: str) -> str:
    return re.sub(r"\s*\[\[?\d+\]?\]\([^)]*\)|\s*\[\d+\]", "", s or "").strip()


def _post_links(data: dict) -> list[str]:
    out = []
    for c in list(data.get("citations") or []) + list(data.get("inline_citations") or []):
        u = c if isinstance(c, str) else (c.get("url") or c.get("link") or "")
        if re.search(r"https?://(www\.)?(x|twitter)\.com/[^/]+/status/\d+", u or "") and u not in out:
            out.append(u)
    return out


def markdown(x: dict | None, status: str = "") -> str:
    if status == "unavailable":
        return "What X says: connect Grok (hermes auth add xai-oauth) to see the conversation on X."
    if not x or status not in ("done", "none"):
        return ""
    lines = ["**What X says:** " + (x.get("summary") or "")]
    lines += [f"- @{t['handle']}: {t['gist']}" + (f" ({t['url']})" if t.get("url") else "") for t in x.get("takes", [])]
    if x.get("pushback"):
        lines.append(f"Pushback: {x['pushback']}")
    if x.get("notable"):
        lines.append("Notable: " + ", ".join("@" + n for n in x["notable"]))
    return "\n".join(lines)
