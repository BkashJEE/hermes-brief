# Hermes Brief

**Save a page, an X post or a YouTube video from Chrome. Your Hermes reads it and writes you a brief.**

You bookmark things to read later and never do. Hermes Brief reads them the moment you save them and keeps a short
brief of each one: what it is, the key points, why it matters, one next step, and timestamps for videos. Briefs land
in folders on a **Briefs** page in Hermes Desktop, and any Hermes chat can find them ("what did I save about Ollama
this week?"). The extension's side panel also lets you ask Hermes about the page you're on.

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
- **In any chat:** `brief_save` (save a link and brief it now), `brief_search` (what you saved), `brief_get`.
- **Ask about this page:** the side panel sends the page to your Hermes and streams the answer (a real Hermes turn,
  with its tools). Quick asks: *Brief this*, *What can I do with it?*, *Explain simply*.
- A notification when each brief is ready.

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
3. **Connect:** the extension opens its options page. Paste the `API_SERVER_KEY` from your Hermes `.env` (the API
   server must be on: `API_SERVER_ENABLED=true`), then click *Save and test*.

On a multi-profile gateway (`gateway.multiplex_profiles`), enable the plugin in the **default** profile too: the API
server's routes belong to it. The library is shared by all your profiles.

## Privacy and limits

- The extension talks **only to your own Hermes on 127.0.0.1**. It never reads a page on its own: only the page you
  save, or the one you open the side panel on. To ask about a page, Chrome asks you once per site.
- Briefs use your Hermes model through `ctx.llm` (one call per saved link), so each costs about what a short chat does.
- Links Hermes reads itself are fetched from your machine; logged-in pages read that way only show what's public.
- X's public embed cuts long quoted posts short; save from the tab to get the full post.
- YouTube transcripts need `yt-dlp` on the Hermes machine when YouTube blocks the in-page caption fetch.

## How it works

| Part | File |
|---|---|
| API-server routes for the extension (behind the server's own auth) and the brief worker | `service.py` |
| Readers: page text, X posts, video transcripts | `readers.py` |
| The brief: one structured `ctx.llm` call | `brief.py` |
| Library (SQLite, one row per canonical URL) | `store.py` |
| Chat tools | `tools.py` |
| Desktop Briefs page and its backend | `desktop/plugin.js`, `dashboard/plugin_api.py` |
| Chrome extension (Manifest V3) | `extension/` |

Tests: `python tests/test_store_readers.py`, `python tests/test_routes.py`, and the extension end-to-end test
(`python tests/mock_hermes.py`, then `node tests/ext_e2e.mjs`).

Built by [@BkashJosi](https://x.com/BkashJosi). Independent, not affiliated with Nous Research. MIT License.
