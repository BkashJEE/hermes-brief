// hermes-brief: the Briefs page in Hermes Desktop. Plain ESM, loaded uncompiled (no JSX, no build).
//
// Route /briefs (sidebar "Briefs" + ⌘K "Open Briefs"): folders on the left, search and "add a link" on top, one card
// per saved link with its brief (headline, key points, why it matters, next step, video timestamps).
// Data: this plugin's Desktop backend, ctx.rest('/items' ...) -> dashboard/plugin_api.py, the same library the
// Chrome extension saves into. Briefs are written by the gateway's worker; the page polls while any are pending.

import { host, PALETTE_AREA, ROUTES_AREA, SIDEBAR_NAV_AREA } from '@hermes/plugin-sdk'
import { useEffect, useMemo, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'hermes-brief'
const ROUTE = '/briefs'
const h = (type, props, ...children) => children.length ? (children.length > 1 ? jsxs : jsx)(type, { ...(props || {}), children: children.length === 1 ? children[0] : children }) : jsx(type, props || {})
const KIND = { page: 'Page', article: 'Article', x_post: 'X post', youtube: 'YouTube', video: 'Video', pdf: 'PDF' }
let ctxRef = null

const rest = (path, opts) => ctxRef.rest(path, opts)
const ago = t => {
  const s = Math.max(1, Math.round(Date.now() / 1000 - t))
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return `${Math.round(s / 86400)} d ago`
}
const open = url => { try { ctxRef.os?.openExternal?.(url) } catch { window.open(url, '_blank') } }

const CSS = `
.hb{display:flex;height:100%;min-height:0;color:var(--ui-text,#e8ecf4);font-size:13px}
.hb-side{width:210px;flex:none;border-right:1px solid var(--ui-border,#2a2f3a);padding:14px 10px;overflow:auto}
.hb-side h2{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--ui-text-tertiary,#8a93a6);margin:0 6px 8px}
.hb-f{display:flex;justify-content:space-between;width:100%;text-align:left;border:0;background:none;color:inherit;padding:6px 8px;border-radius:6px;cursor:pointer;font:inherit}
.hb-f:hover{background:var(--ui-bg-hover,rgba(255,255,255,.05))}.hb-f.on{background:var(--ui-accent-subtle,rgba(79,139,255,.16));color:var(--ui-accent,#4f8bff)}
.hb-f span:last-child{color:var(--ui-text-tertiary,#8a93a6)}
.hb-main{flex:1;min-width:0;display:flex;flex-direction:column}
.hb-top{display:flex;gap:8px;padding:14px 18px;border-bottom:1px solid var(--ui-border,#2a2f3a);align-items:center}
.hb-top h1{font-size:18px;margin:0 12px 0 0;white-space:nowrap}
.hb-in{flex:1;min-width:0;background:rgba(127,127,127,.08);border:1px solid var(--ui-border,#2a2f3a);color:inherit;border-radius:8px;padding:7px 10px;font:inherit}
.hb-btn{border:1px solid var(--ui-border,#2a2f3a);background:var(--ui-bg-elevated,transparent);color:inherit;border-radius:8px;padding:6px 11px;cursor:pointer;font:inherit;white-space:nowrap}
.hb-btn.pri{background:var(--ui-accent,#0a4cff);border-color:transparent;color:#fff}
.hb-list{flex:1;overflow:auto;padding:14px 18px;display:grid;gap:12px;align-content:start}
.hb-card{border:1px solid var(--ui-border,#2a2f3a);border-radius:12px;padding:14px 16px;background:var(--ui-bg-elevated,rgba(255,255,255,.02))}
.hb-meta{display:flex;gap:8px;align-items:center;color:var(--ui-text-tertiary,#8a93a6);font-size:12px;flex-wrap:wrap}
.hb-pill{font:600 11px/1 ui-monospace,monospace;padding:3px 7px;border-radius:99px;background:var(--ui-bg-hover,rgba(255,255,255,.06))}
.hb-pill.yt{color:#ff6b6b}.hb-pill.x{color:#9ecbff}.hb-pill.wait{color:#f5c518}.hb-pill.err{color:#ef4444}
.hb-card h3{font-size:15px;margin:8px 0 2px;line-height:1.35;cursor:pointer}
.hb-card h3:hover{color:var(--ui-accent,#4f8bff)}
.hb-what{color:var(--ui-text-secondary,#b5bdcc)}
.hb-card ul{margin:8px 0;padding-left:18px}.hb-card li{margin:3px 0;line-height:1.45}
.hb-why,.hb-next{margin-top:6px;line-height:1.45}.hb-next b,.hb-why b{color:var(--ui-text,#fff)}
.hb-ts{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}.hb-ts button{font-size:12px}
.hb-acts{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap}.hb-acts .hb-btn{font-size:12px;padding:4px 9px}
.hb-empty{color:var(--ui-text-tertiary,#8a93a6);padding:40px 6px;line-height:1.6;max-width:560px}
.hb-pair{border:1px solid var(--ui-accent,#4f8bff);border-radius:12px;padding:16px 18px;margin:14px 18px 0;background:var(--ui-accent-subtle,rgba(79,139,255,.08))}
.hb-code{font:700 34px/1 ui-monospace,monospace;letter-spacing:.35em;margin:10px 0 6px}
.hb-pair ol{margin:8px 0 0;padding-left:18px;line-height:1.6}
.hb-dev{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:5px 0;border-top:1px solid var(--ui-border,#2a2f3a);font-size:12px}
.hb-x{margin-top:10px;border-left:3px solid var(--ui-text,#e8ecf4);padding:6px 0 6px 12px}
.hb-x h5{margin:0 0 4px;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--ui-text-tertiary,#8a93a6)}
.hb-x ul{margin:6px 0}.hb-x a{color:inherit}.hb-x .muted{color:var(--ui-text-tertiary,#8a93a6);font-size:12px}
.hb-digest{border:1px dashed var(--ui-border,#2a2f3a);border-radius:12px;padding:12px 16px}
.hb-digest h4{margin:0 0 6px;font-size:13px}.hb-digest li{margin:2px 0}
`

function useLibrary() {
  const [data, setData] = useState({ items: [], folders: [], loaded: false, error: '' })
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let alive = true
    Promise.all([rest('/items?limit=200'), rest('/folders')])
      .then(([a, b]) => alive && setData({ items: a.items || [], folders: b.folders || [], loaded: true, error: '' }))
      .catch(e => alive && setData(d => ({ ...d, loaded: true, error: String(e?.message || e) })))
    return () => { alive = false }
  }, [tick])
  const pending = data.items.some(i => i.status === 'new' || i.status === 'briefing' || i.x_status === 'new')
  useEffect(() => {
    const t = setTimeout(() => setTick(x => x + 1), pending ? 4000 : 30000)
    return () => clearTimeout(t)
  }, [tick, pending])
  return [data, () => setTick(x => x + 1)]
}

// "What X says": the conversation on X around this link, from Grok's x_search (run by the gateway worker).
function XSays({ item, ask }) {
  const st = item.x_status, x = item.x_says
  if (item.status !== 'done') return null
  if (!st) return h('div', { className: 'hb-x' }, h('button', { className: 'hb-btn', onClick: ask }, '𝕏  What X says'))
  if (st === 'new') return h('div', { className: 'hb-x' }, h('div', { className: 'muted' }, '𝕏  Asking Grok what X says…'))
  if (st === 'unavailable' || st === 'error') return h('div', { className: 'hb-x' },
    h('div', { className: 'muted' }, st === 'unavailable' ? 'Connect Grok to see what X says: run  hermes auth add xai-oauth' : `Grok couldn't search X: ${x?.error || ''}`),
    h('button', { className: 'hb-btn', style: { marginTop: 6 }, onClick: ask }, 'Try again'))
  return h('div', { className: 'hb-x' },
    h('h5', null, '𝕏  What X says'),
    h('div', null, x?.summary || ''),
    x?.takes?.length ? h('ul', null, ...x.takes.map((t, i) => h('li', { key: i },
      t.url ? h('a', { href: t.url, onClick: e => { e.preventDefault(); open(t.url) } }, `@${t.handle}`) : h('b', null, `@${t.handle}`), `: ${t.gist}`))) : null,
    x?.pushback ? h('div', null, h('b', null, 'Pushback: '), x.pushback) : null,
    x?.notable?.length ? h('div', { className: 'muted' }, `Notable: ${x.notable.map(n => '@' + n).join(', ')}`) : null,
    x?.degraded ? h('div', { className: 'muted' }, 'Grok gave no post links for this, so treat it as a rough read.') : null)
}

function Card({ item, folders, reload }) {
  const b = item.brief
  const pill = item.kind === 'youtube' || item.kind === 'video' ? 'yt' : item.kind === 'x_post' ? 'x' : ''
  const state = item.status === 'done' ? null : item.status === 'error' ? h('span', { className: 'hb-pill err' }, 'failed') : h('span', { className: 'hb-pill wait' }, 'reading…')
  const act = (path, opts) => rest(path, opts).then(reload).catch(e => host.toast?.(String(e?.message || e)))
  const move = () => {
    const to = window.prompt('Move to folder', item.folder)
    if (to != null && to.trim()) act(`/items/${item.id}/move`, { method: 'POST', body: { folder: to.trim() } })
  }
  const jump = t => {
    const parts = String(t).split(':').map(Number)
    const secs = parts.reduce((a, n) => a * 60 + (n || 0), 0)
    const u = new URL(item.url); u.searchParams.set('t', `${secs}s`); open(u.toString())
  }
  return h('article', { className: 'hb-card' },
    h('div', { className: 'hb-meta' },
      h('span', { className: `hb-pill ${pill}` }, KIND[item.kind] || item.kind),
      h('span', null, item.folder), h('span', null, '·'), h('span', null, ago(item.saved_at)), state),
    h('h3', { onClick: () => open(item.url), title: item.url }, b?.headline || item.title || item.url),
    b ? h('div', { className: 'hb-what' }, b.what_it_is) : h('div', { className: 'hb-what' }, item.status === 'error' ? (item.error || 'Could not brief this one.') : 'Hermes is reading this. The brief appears here in a few seconds.'),
    b?.key_points?.length ? h('ul', null, ...b.key_points.map((p, i) => h('li', { key: i }, p))) : null,
    b?.why_it_matters ? h('div', { className: 'hb-why' }, h('b', null, 'Why it matters: '), b.why_it_matters) : null,
    b?.next_step ? h('div', { className: 'hb-next' }, h('b', null, 'Next step: '), b.next_step) : null,
    jsx(XSays, { item, ask: () => act(`/items/${item.id}/xsays`, { method: 'POST' }) }),
    b?.timestamps?.length ? h('div', { className: 'hb-ts' }, ...b.timestamps.map((t, i) => h('button', { key: i, className: 'hb-btn', onClick: () => jump(t.t) }, `${t.t} ${t.note}`))) : null,
    h('div', { className: 'hb-acts' },
      h('button', { className: 'hb-btn', onClick: () => open(item.url) }, 'Open'),
      h('button', { className: 'hb-btn', onClick: move }, 'Move'),
      h('button', { className: 'hb-btn', onClick: () => act(`/items/${item.id}/rebrief`, { method: 'POST' }) }, 'Brief again'),
      h('button', { className: 'hb-btn', onClick: () => window.confirm('Delete this saved link and its brief?') && act(`/items/${item.id}`, { method: 'DELETE' }) }, 'Delete')))
}

function PairPanel({ onClose }) {
  const [code, setCode] = useState(null)
  const [left, setLeft] = useState(0)
  const [devices, setDevices] = useState([])
  const [err, setErr] = useState('')
  const loadDevices = () => rest('/devices').then(d => setDevices(d.devices || [])).catch(() => {})
  const newCode = () => rest('/pair/start', { method: 'POST' }).then(r => { setCode(r.code); setLeft(r.expires_in); setErr('') }).catch(e => setErr(String(e?.message || e)))
  useEffect(() => { newCode(); loadDevices() }, [])
  useEffect(() => {
    if (!code) return
    const t = setInterval(() => { setLeft(x => Math.max(0, x - 1)); loadDevices() }, 1000)
    return () => clearInterval(t)
  }, [code])
  const forget = id => rest(`/devices/${id}`, { method: 'DELETE' }).then(loadDevices)
  const mmss = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`
  return h('div', { className: 'hb-pair' },
    h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
      h('strong', null, 'Connect Chrome'), h('button', { className: 'hb-btn', onClick: onClose }, 'Done')),
    err ? h('div', null, err) : null,
    code ? h('div', null,
      h('div', { className: 'hb-code' }, code.replace(/(\d{3})(\d{3})/, '$1 $2')),
      h('div', { style: { color: 'var(--ui-text-tertiary,#8a93a6)', fontSize: 12 } },
        left > 0 ? `Works once, for ${mmss}.` : 'Expired. ', left > 0 ? null : h('button', { className: 'hb-btn', onClick: newCode }, 'New code'))) : null,
    h('ol', null,
      h('li', null, 'Install the Hermes Brief extension (chrome://extensions → Developer mode → Load unpacked → the extension folder of this plugin).'),
      h('li', null, 'Its Connect page shows one line to add to ~/.hermes/.env (API_SERVER_CORS_ORIGINS=chrome-extension://…): Hermes only answers browsers on that allowlist. Add it, then hermes gateway restart.'),
      h('li', null, 'Type this code on the Connect page and click Connect.'),
      h('li', null, 'Save a page with the toolbar button, right-click a link, or bookmark into the "Hermes" folder.')),
    devices.length ? h('div', { style: { marginTop: 12 } },
      h('div', { style: { fontSize: 12, color: 'var(--ui-text-tertiary,#8a93a6)', marginBottom: 4 } }, 'Connected browsers'),
      ...devices.map(d => h('div', { key: d.id, className: 'hb-dev' },
        h('span', null, `${d.name} · connected ${ago(d.created)}${d.last_seen ? ` · last used ${ago(d.last_seen)}` : ''}`),
        h('button', { className: 'hb-btn', onClick: () => forget(d.id) }, 'Disconnect')))) : null)
}

function Digest({ items }) {
  const day = items.filter(i => Date.now() / 1000 - i.saved_at < 86400)
  if (!day.length) return null
  return h('div', { className: 'hb-digest' },
    h('h4', null, `Last 24 hours: you saved ${day.length}`),
    h('ul', null, ...day.slice(0, 8).map(i => h('li', { key: i.id }, `${i.brief?.headline || i.title || i.url}`, h('span', { style: { color: 'var(--ui-text-tertiary,#8a93a6)' } }, ` · ${i.folder}`)))),
    h('div', { style: { fontSize: 12, color: 'var(--ui-text-tertiary,#8a93a6)', marginTop: 6 } }, 'Get this every morning: ask Hermes to "run brief_digest every day at 8am and send it to me".'))
}

function BriefsPage() {
  const [pairing, setPairing] = useState(false)
  const [data, reload] = useLibrary()
  const [folder, setFolder] = useState('')
  const [q, setQ] = useState('')
  const [link, setLink] = useState('')
  const shown = useMemo(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean)
    return data.items.filter(i => (!folder || i.folder === folder) && words.every(w =>
      `${i.title} ${i.url} ${JSON.stringify(i.brief || {})}`.toLowerCase().includes(w)))
  }, [data.items, folder, q])
  const add = () => {
    const url = link.trim()
    if (!/^https?:\/\//.test(url)) return host.toast?.('Paste a full link starting with http(s)://')
    rest('/items', { method: 'POST', body: { url, folder } }).then(() => { setLink(''); reload() }).catch(e => host.toast?.(String(e?.message || e)))
  }
  return h('div', { className: 'hb' },
    h('style', null, CSS),
    h('nav', { className: 'hb-side' },
      h('h2', null, 'Folders'),
      h('button', { className: `hb-f ${folder ? '' : 'on'}`, onClick: () => setFolder('') }, h('span', null, 'All'), h('span', null, String(data.items.length))),
      ...data.folders.map(f => h('button', { key: f.name, className: `hb-f ${folder === f.name ? 'on' : ''}`, onClick: () => setFolder(f.name) },
        h('span', null, f.name), h('span', null, String(f.count))))),
    h('section', { className: 'hb-main' },
      h('div', { className: 'hb-top' },
        h('h1', null, 'Briefs'),
        h('input', { className: 'hb-in', placeholder: 'Search your saved links…', value: q, onChange: e => setQ(e.target.value) }),
        h('input', { className: 'hb-in', placeholder: 'Paste a link to save and brief', value: link, onChange: e => setLink(e.target.value), onKeyDown: e => e.key === 'Enter' && add() }),
        h('button', { className: 'hb-btn pri', onClick: add }, 'Save'),
        h('button', { className: 'hb-btn', onClick: () => setPairing(p => !p) }, 'Connect Chrome')),
      pairing ? jsx(PairPanel, { onClose: () => setPairing(false) }) : null,
      h('div', { className: 'hb-list' },
        !folder && !q && data.items.length ? jsx(Digest, { items: data.items }) : null,
        data.error ? h('div', { className: 'hb-empty' }, `Could not load your briefs: ${data.error}`) :
        !data.loaded ? h('div', { className: 'hb-empty' }, 'Loading…') :
        shown.length ? shown.map(i => jsx(Card, { item: i, folders: data.folders, reload }, i.id)) :
        h('div', { className: 'hb-empty' }, data.items.length ? 'Nothing matches.' :
          'Nothing saved yet. Click Connect Chrome to pair the Hermes Brief extension, then save a page with its button, right-click any link → "Save link to Hermes", or bookmark into the "Hermes" folder. You can also paste a link above.'))))
}

export default {
  id: ID,
  name: 'Hermes Brief',
  register(ctx) {
    ctxRef = ctx
    ctx.register({ id: 'page', area: ROUTES_AREA, data: { path: ROUTE }, render: () => jsx(BriefsPage, {}) })
    ctx.register({ id: 'nav', area: SIDEBAR_NAV_AREA, order: 88, data: { path: ROUTE, label: 'Briefs', codicon: 'bookmark' } })
    ctx.register({ id: 'open', area: PALETTE_AREA, data: { id: `${ID}.open`, label: 'Open Briefs', keywords: ['brief', 'bookmarks', 'saved', 'read later', 'links', 'youtube'], run: () => host.navigate(ROUTE) } })
  },
}
