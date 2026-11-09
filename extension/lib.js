// Shared by the service worker, popup and options page.

export const DEFAULTS = { base: 'http://127.0.0.1:8642', key: '', folderName: 'Hermes', notify: true }

export async function settings() {
  const s = await chrome.storage.local.get(Object.keys(DEFAULTS))
  return { ...DEFAULTS, ...s }
}

// The plugin's routes live on the API server's root (on a multiplexed gateway, the default profile's).
export function apiRoot(s) {
  return (s.base || DEFAULTS.base).replace(/\/+$/, '')
}

export async function api(path, { method = 'GET', body } = {}) {
  const s = await settings()
  if (!s.key) throw new Error('Connect the extension to Hermes first: open its options and enter the pairing code.')
  const res = await fetch(`${apiRoot(s)}/api/plugins/hermes-brief${path}`, {
    method,
    headers: { Authorization: `Bearer ${s.key}`, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (res.status === 401) throw new Error('Hermes no longer knows this browser. Pair it again in the extension options.')
  if (res.status === 404) throw new Error('Hermes Brief is not running on that Hermes. Enable the plugin and restart the gateway.')
  if (!res.ok) throw new Error(`Hermes answered ${res.status}`)
  return res.json()
}

// Read the page in the tab: page text, an X post, or a YouTube video's captions. Runs only when the user acts.
export async function readTab(tabId) {
  try {
    const [{ result } = {}] = await chrome.scripting.executeScript({ target: { tabId }, world: 'MAIN', func: pageReader })
    return result || {}
  } catch (e) {
    if (/permission|Cannot access/i.test(String(e))) throw new Error('NEEDS_ACCESS')
    throw e
  }
}

// Injected into the page (MAIN world, so YouTube's player data is visible). Must be self-contained.
export async function pageReader() {
  const url = location.href
  const selection = String(getSelection() || '').trim().slice(0, 4000)
  const host = location.hostname.replace(/^www\./, '')
  const clean = s => (s || '').replace(/[ \t]+/g, ' ').replace(/\n\s*\n+/g, '\n\n').trim()
  try {
    if ((host === 'x.com' || host === 'twitter.com') && /\/status\/\d+/.test(location.pathname)) {
      const arts = [...document.querySelectorAll('article')].slice(0, 6)
      const text = arts.map(a => {
        const who = a.querySelector('[data-testid="User-Name"]')?.innerText.replace(/\n/g, ' ') || ''
        const body = a.querySelector('[data-testid="tweetText"]')?.innerText || ''
        return `${who}\n${body}`
      }).join('\n\n---\n\n')
      return { url, title: document.title, kind: 'x_post', selection, content: clean(text), meta: { read_by: 'browser' } }
    }
    if (host.endsWith('youtube.com') && location.pathname === '/watch') {
      const pr = window.ytInitialPlayerResponse || {}
      const vd = pr.videoDetails || {}
      const tracks = pr.captions?.playerCaptionsTracklistRenderer?.captionTracks || []
      const track = tracks.find(t => t.languageCode === 'en' && t.kind !== 'asr') || tracks.find(t => (t.languageCode || '').startsWith('en')) || tracks[0]
      let transcript = ''
      // YouTube often refuses this fetch now (it wants a token only its player has); then Hermes fetches the
      // transcript itself with yt-dlp, because meta.transcript says 'none'.
      let j = {}
      if (track?.baseUrl) {
        try { j = JSON.parse((await (await fetch(track.baseUrl + '&fmt=json3')).text()) || '{}') } catch { j = {} }
        let last = -99
        for (const ev of j.events || []) {
          const t = (ev.tStartMs || 0) / 1000
          const words = (ev.segs || []).map(s => s.utf8).join('').replace(/\n/g, ' ').trim()
          if (!words) continue
          if (t - last >= 20) { const m = Math.floor(t / 60), s = Math.floor(t % 60); transcript += `\n[${m}:${String(s).padStart(2, '0')}] `; last = t }
          transcript += words + ' '
        }
      }
      const len = +vd.lengthSeconds || 0
      const head = `Video: ${vd.title || document.title}\nChannel: ${vd.author || ''}\nLength: ${Math.floor(len / 60)}:${String(len % 60).padStart(2, '0')}\n\n${(vd.shortDescription || '').slice(0, 3000)}`
      return { url, title: vd.title || document.title, kind: 'youtube', selection,
               content: head + (transcript ? `\n\nTranscript (timestamps in [m:ss]):${transcript}` : '\n\n(No transcript available.)'),
               meta: { read_by: 'browser', channel: vd.author, duration: len, transcript: transcript ? 'yes' : 'none' } }
    }
    const main = document.querySelector('article') || document.querySelector('main') || document.body
    const text = clean(main.innerText).length > 400 ? main.innerText : document.body.innerText
    const desc = document.querySelector('meta[name="description"], meta[property="og:description"]')?.content || ''
    return { url, title: document.title, kind: 'page', selection, content: clean(`${document.title}\n${desc}\n\n${text}`).slice(0, 60000), meta: { read_by: 'browser' } }
  } catch (e) {
    return { url, title: document.title, kind: 'page', selection, content: '', meta: { read_error: String(e).slice(0, 200) } }
  }
}

export const KIND_LABEL = { page: 'Page', x_post: 'X post', youtube: 'YouTube', video: 'Video', pdf: 'PDF', article: 'Article' }

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
}

// Swap the 6-digit code from the Desktop Briefs page for this browser's own token.
export async function pair(base, code) {
  const res = await fetch(`${base.replace(/\/+$/, '')}/api/plugins/hermes-brief/pair`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, name: `${navigator.userAgentData?.brands?.find(b => !/Not|Chromium/.test(b.brand))?.brand || 'Chrome'} on ${navigator.userAgentData?.platform || navigator.platform}` }),
  })
  if (res.status === 404) throw new Error('Hermes Brief is not running at that address. Is the plugin enabled and the gateway restarted?')
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.error || `Hermes answered ${res.status}`)
  return body.token
}
