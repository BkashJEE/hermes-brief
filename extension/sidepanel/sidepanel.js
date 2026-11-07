import { api, apiRoot, esc, readTab, settings } from '../lib.js'
const $ = id => document.getElementById(id)
let tab = null, page = null, busy = false

async function currentTab() {
  const [t] = await chrome.tabs.query({ active: true, currentWindow: true })
  return t
}

async function refresh() {
  tab = await currentTab()
  page = null
  $('page').textContent = tab?.title || ''
  $('brief').innerHTML = ''
  if (!/^https?:/.test(tab?.url || '')) { $('state').textContent = 'not a web page'; return }
  try {
    const { item: hit } = await api(`/lookup?url=${encodeURIComponent(tab.url)}`)
    if (hit) showBrief(hit)
    $('state').textContent = hit ? (hit.status === 'done' ? 'saved' : hit.status) : 'not saved'
  } catch (e) { $('state').textContent = 'not connected'; $('brief').innerHTML = `<span class="bad">${esc(e.message)}</span>` }
}

function showBrief(item) {
  const b = item.brief
  if (!b) { $('brief').innerHTML = `<span class="muted">Saved in ${esc(item.folder)}. The brief is ${esc(item.status)}.</span>`; return }
  $('brief').innerHTML = `<h3>${esc(b.headline)}</h3><div class="muted">${esc(b.what_it_is)} · ${esc(item.folder)}</div>
    <ul>${(b.key_points || []).map(p => `<li>${esc(p)}</li>`).join('')}</ul>
    ${b.timestamps?.length ? `<div class="muted">Jump to: ${b.timestamps.map(t => `${esc(t.t)} ${esc(t.note)}`).join(' · ')}</div>` : ''}
    ${b.next_step ? `<div style="margin-top:6px"><strong>Next step:</strong> ${esc(b.next_step)}</div>` : ''}`
}

function add(cls, text) {
  const d = document.createElement('div'); d.className = `msg ${cls}`; d.textContent = text
  $('log').appendChild(d); $('log').scrollTop = 1e9; return d
}

async function ask(question) {
  if (busy || !question.trim()) return
  busy = true; $('send').disabled = true
  add('me', question)
  const out = add('her', '…')
  try {
    if (!page) page = await readTab(tab.id)
    const s = await settings()
    const context = `The user is looking at this web page in Chrome and asks about it.\nURL: ${tab.url}\nTitle: ${page.title || tab.title}\n` +
      (page.selection ? `They highlighted: ${page.selection}\n` : '') + `\nPage content:\n${(page.content || '').slice(0, 30000)}`
    const res = await fetch(`${apiRoot(s)}/v1/chat/completions`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${s.key}`, 'Content-Type': 'application/json',
                 'X-Hermes-Session-Key': `hermes-brief:${tab.id}:${tab.url}`.slice(0, 200) },
      body: JSON.stringify({ model: 'hermes-agent', stream: true, messages: [{ role: 'user', content: `${context}\n\nQuestion: ${question}` }] }),
    })
    if (!res.ok) throw new Error(res.status === 401 ? 'Hermes refused the key.' : `Hermes answered ${res.status}`)
    const reader = res.body.getReader(), dec = new TextDecoder()
    let buf = '', text = ''
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      const lines = buf.split('\n'); buf = lines.pop()
      for (const line of lines) {
        if (!line.startsWith('data:')) continue
        const data = line.slice(5).trim()
        if (data === '[DONE]') continue
        try { const delta = JSON.parse(data).choices?.[0]?.delta?.content; if (delta) { text += delta; out.textContent = text; $('log').scrollTop = 1e9 } } catch {}
      }
    }
    if (!text) out.textContent = '(no answer)'
  } catch (e) { out.textContent = e.message; out.classList.add('bad') }
  busy = false; $('send').disabled = false
}

$('send').onclick = () => { const q = $('q').value; $('q').value = ''; ask(q) }
$('q').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('send').click() } })
document.querySelectorAll('[data-q]').forEach(b => b.onclick = () => ask(b.dataset.q))
$('saveBtn').onclick = async () => {
  $('saveBtn').disabled = true
  const r = await chrome.runtime.sendMessage({ type: 'save-tab', tabId: tab.id })
  $('saveBtn').disabled = false
  if (r?.ok) { $('state').textContent = 'saved'; showBrief(r.item) } else add('her bad', r?.error || 'Could not save.')
}
chrome.tabs.onActivated.addListener(refresh)
chrome.tabs.onUpdated.addListener((id, info) => { if (id === tab?.id && info.status === 'complete') refresh() })
refresh()
