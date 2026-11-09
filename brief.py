"""Turn one saved item into a brief with one host-owned model call (ctx.llm, the user's own provider and model)."""

from __future__ import annotations

import json
from typing import Any

BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "One plain sentence: what this is and the main point."},
        "what_it_is": {"type": "string", "description": "Kind and source, e.g. 'A 12-minute YouTube tutorial by X' or 'An X post by @y'."},
        "key_points": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 6},
        "why_it_matters": {"type": "string", "description": "Why the reader saved-worthy: what it lets them do or decide."},
        "next_step": {"type": "string", "description": "One concrete thing the reader could do with it, or '' if none."},
        "timestamps": {"type": "array", "description": "Videos only: the moments worth jumping to.",
                       "items": {"type": "object", "properties": {"t": {"type": "string"}, "note": {"type": "string"}},
                                 "required": ["t", "note"]}, "maxItems": 8},
        "links": {"type": "array", "items": {"type": "string"}, "maxItems": 6,
                  "description": "Tools, repos or links the content names, as they appear."},
        "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "read_minutes": {"type": "integer", "description": "Minutes to read or watch the original."},
        "confidence": {"type": "string", "enum": ["full", "partial", "title_only"],
                       "description": "full = read the whole thing; partial = part of it; title_only = only the title/description."},
    },
    "required": ["headline", "what_it_is", "key_points", "why_it_matters", "next_step", "tags", "confidence"],
}

INSTRUCTIONS = """You write short, useful briefs of things a person saved from their browser to read or watch later.
Rules:
- Only use what is in the provided content. Never invent facts, numbers, quotes or timestamps.
- If the content is only a title or description, say so with confidence = "title_only" and keep the brief short.
- Plain English, short sentences. No hype words. Key points are the real substance, not a table of contents.
- Videos: timestamps come only from the [m:ss] marks in the transcript.
- next_step is one concrete action (try a command, read section X, compare with Y), or an empty string.
"""

MAX_PROMPT_CHARS = 40_000


def build_input(item: dict) -> str:
    meta = item.get("meta") or {}
    head = [f"URL: {item.get('url', '')}", f"Title: {item.get('title', '')}", f"Kind: {item.get('kind', 'page')}",
            f"Saved into folder: {item.get('folder', '')}"]
    if meta.get("selection"):
        head.append(f"The reader highlighted this part: {meta['selection'][:2000]}")
    if meta.get("note"):
        head.append(f"The reader's note: {meta['note'][:500]}")
    content = (item.get("content") or "").strip()
    if len(content) > MAX_PROMPT_CHARS:
        content = content[:MAX_PROMPT_CHARS] + "\n[... cut for length]"
    return "\n".join(head) + "\n\nContent:\n" + (content or "(none: only the title and URL are known)")


async def write_brief(llm: Any, item: dict) -> tuple[dict, str]:
    """Returns (brief, model). Raises RuntimeError when the model gave no usable answer."""
    result = await llm.acomplete_structured(
        instructions=INSTRUCTIONS,
        input=[{"type": "text", "text": build_input(item)}],
        json_schema=BRIEF_SCHEMA,
        purpose="hermes-brief.brief",
        temperature=0.2,
        max_tokens=900,
    )
    brief = getattr(result, "parsed", None)
    if not isinstance(brief, dict):
        text = (getattr(result, "text", "") or "").strip()
        try:
            brief = json.loads(text[text.find("{"): text.rfind("}") + 1])
        except Exception:
            raise RuntimeError("the model did not return a brief") from None
    if item.get("kind") not in ("youtube", "video"):
        brief.pop("timestamps", None)
    return brief, f"{getattr(result, 'provider', '') or ''}/{getattr(result, 'model', '') or ''}".strip("/")


def brief_markdown(item: dict) -> str:
    """A brief as short Markdown, for chat tools and the digest."""
    b = item.get("brief") or {}
    if not b:
        state = {"new": "waiting to be read", "briefing": "being read now", "error": f"failed: {item.get('error') or ''}"}
        return f"**{item.get('title') or item.get('url')}**: {state.get(item.get('status'), item.get('status'))}\n{item.get('url')}"
    lines = [f"**{b.get('headline', '')}**", f"_{b.get('what_it_is', '')}_  ·  {item.get('url', '')}", ""]
    lines += [f"- {p}" for p in b.get("key_points", [])]
    if b.get("why_it_matters"):
        lines += ["", f"Why it matters: {b['why_it_matters']}"]
    if b.get("timestamps"):
        lines += ["", "Jump to: " + "  ·  ".join(f"{t['t']} {t['note']}" for t in b["timestamps"])]
    if b.get("next_step"):
        lines += ["", f"Next step: {b['next_step']}"]
    if b.get("confidence") and b["confidence"] != "full":
        lines += ["", f"(Read: {b['confidence'].replace('_', ' ')})"]
    return "\n".join(lines)


def digest_markdown(items: list[dict], hours: float = 24) -> str:
    """'What you saved' in one glance: one line per item, grouped by folder. No model call."""
    if not items:
        return f"Nothing saved in the last {int(hours)} hours."
    by_folder: dict[str, list[dict]] = {}
    for it in items:
        by_folder.setdefault(it.get("folder") or "Inbox", []).append(it)
    lines = [f"**You saved {len(items)} thing{'s' if len(items) != 1 else ''} in the last {int(hours)} hours**"]
    for folder, its in by_folder.items():
        lines += ["", f"**{folder}**"]
        for it in its:
            b = it.get("brief") or {}
            head = b.get("headline") or it.get("title") or it.get("url")
            extra = f" Next: {b['next_step']}" if b.get("next_step") else ""
            lines.append(f"- {head} ({it.get('url')}){extra}")
    return "\n".join(lines)
