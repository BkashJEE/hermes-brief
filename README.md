# Hermes Brief

**Save a page, an X post or a YouTube video from Chrome. Your Hermes reads it and writes you a brief.**

You bookmark things to read later and never do. Hermes Brief reads them the moment you save them and keeps a short
brief of each one: what it is, the key points, why it matters, one next step, and timestamps for videos. Briefs land
in folders on a **Briefs** page in Hermes Desktop, any Hermes chat can find them ("what did I save about Ollama
this week?"), and a daily digest tells you what you saved yesterday.

## What you get

- **Three ways to save:** the toolbar button (pick a folder, add a note), right-click any link → *Save link to Hermes*,
  or just bookmark into a Chrome folder named **Hermes** (Ctrl+D). Subfolders of it become Brief folders.
- **Reads what you see:** the page is read in your own tab, so logged-in pages and the X post you're looking at come
  with it. Links saved without a tab are read by Hermes: articles, X posts (public embed) and videos (transcript via
  `yt-dlp`).
- **A brief per item:** headline, what it is, 2–6 key points, why it matters, a next step, timestamps for videos, and
  how much Hermes could read (full, partial or title only). The brief only uses what was read; it never invents.
- **Briefs page in Desktop:** folders, search, paste a link to save it, open, move, brief again, delete. Video
  timestamps open the video at that moment.
- **In any chat:** `brief_save` (save a link and brief it now), `brief_search` (what you saved), `brief_get`, and
  `brief_digest` (what you saved in the last 24 hours, by folder). Ask Hermes to *"run brief_digest every day at 8am
  and send it to me"* and you get it on Telegram or wherever your Hermes talks to you.
- **One-click connect:** no API keys in the browser. The Briefs page shows a 6-digit code; type it into the extension.
- **The popup** shows the brief of the page you're on if you saved it, plus your latest briefs.
- A notification when each brief is ready.
- **What X says:** under each brief, what people on X are saying about that link: a one-line read, the sharpest
  takes with the handle and a link to each post, the pushback, and who notable weighed in. Hermes asks Grok through
  its own `x_search` tool, so you see the conversation without opening X.

## What X says

Hermes Brief runs one `x_search` call per saved link after the brief is written (or when you click
**𝕏 What X says** on a card). It needs Grok access in Hermes: `hermes auth add xai-oauth` (Grok sign-in) or an xAI
API key. Without it the card says so and nothing else changes.

- `what_x_says: false` in the plugin's settings turns it off.
- `x_search_profile: ceo` points it at another profile's Grok sign-in. On a multi-profile gateway the worker runs in
  the API server's profile, which may not be the one you signed in to Grok with. The Briefs status
  (`/status` → `x_search`) tells you whether it can run and from which profile.
- Each lookup is one x_search call on your xAI account (about one Grok search). Grok's results are shown as they came
  back, with links to the posts it cited; when it cites nothing, the card marks the read as rough.

Want to chat with Hermes about the page you're on? That's what the excellent
[Hermes Browser Extension](https://github.com/abundantbeing/hermes-browser-extension) does; Hermes Brief is about
saving and remembering, and the two work side by side.

## Install

1. **The plugin**
   ```bash
   hermes plugins install BkashJEE/hermes-brief --enable
   hermes gateway restart
   ```
   The restart adds the plugin's routes to Hermes's API server. Turn on the **Briefs** page in Hermes Desktop under
   Capabilities → Plugins → Hermes Brief.
2. **The Chrome extension** (Chrome, Edge, Brave, Arc, Chromium): open `chrome://extensions`, switch on
   *Developer mode*, click *Load unpacked* and pick the `extension/` folder of this repo.
3. **Connect:** in Hermes Desktop open **Briefs** → **Connect Chrome**. Type the 6-digit code into the page the
   extension opened and click *Connect*. (The Hermes API server must be on: `API_SERVER_ENABLED=true`.)

On a multi-profile gateway (`gateway.multiplex_profiles`), enable the plugin in the **default** profile too: the API
server's routes belong to it. The library is shared by all your profiles.

## Privacy and limits

- The extension talks **only to your own Hermes on 127.0.0.1**. It never reads a page on its own: only the page you
  save (button, right-click, shortcut, or a bookmark of the tab you're on).
- Pairing gives the browser its own token (stored only as a hash in Hermes; disconnect it on the Briefs page). Codes
  last 5 minutes, work once, and five wrong tries cancel every open code. `/pair` is the only route that answers
  without auth, and only to a valid code.
- Briefs use your Hermes model through `ctx.llm` (one call per saved link), so each costs about what a short chat does.
- Links Hermes reads itself are fetched from your machine; logged-in pages read that way only show what's public.
- X's public embed cuts long quoted posts short; save from the tab to get the full post.
- YouTube transcripts need `yt-dlp` on the Hermes machine when YouTube blocks the in-page caption fetch.

## How it works

| Part | File |
|---|---|
| API-server routes for the extension (API-server auth or a paired device token) and the brief worker | `service.py` |
| Readers: page text, X posts, video transcripts | `readers.py` |
| The brief: one structured `ctx.llm` call | `brief.py` |
| Library (SQLite, one row per canonical URL) | `store.py` |
| Chat tools | `tools.py` |
| Desktop Briefs page and its backend | `desktop/plugin.js`, `dashboard/plugin_api.py` |
| Chrome extension (Manifest V3) | `extension/` |

Tests: `python tests/test_store_readers.py`, `python tests/test_routes.py`, and the extension end-to-end test
(`python tests/mock_hermes.py`, then `node tests/ext_e2e.mjs`).

Built by [@BkashJosi](https://x.com/BkashJosi). Independent, not affiliated with Nous Research. MIT License.
