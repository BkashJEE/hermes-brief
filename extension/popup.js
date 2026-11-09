import { api, esc, KIND_LABEL } from './lib.js'
const $ = id => document.getElementById(id)
const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
$('title').textContent = tab?.title || ''
$('opts').onclick = e => { e.preventDefault(); chrome.runtime.openOptionsPage() }

function showHere(item) {
  const b = item?.brief
  if (!item) return
  $('here').style.display = ''
  $('save').textContent = 'Save again & re-brief'
  $('here').innerHTML = b
    ? `<div class="muted">Saved in ${esc(item.folder)}</div><h3 style="margin:4px 0">${esc(b.headline)}</h3>
       <ul>${(b.key_points || []).slice(0, 4).map(p => `<li>${esc(p)}</li>`).join('')}</ul>
       ${b.next_step ? `<div style="margin-top:6px"><strong>Next step:</strong> ${esc(b.next_step)}</div>` : ''}`
    : `<div class="muted">Saved in ${esc(item.folder)}. Hermes is ${item.status === 'error' ? 'stuck on it: ' + esc(item.error || '') : 'reading it now'}.</div>`
}

$('save').onclick = async () => {
  $('save').disabled = true; $('out').className = 'small'; $('out').textContent = 'Saving…'
  const r = await chrome.runtime.sendMessage({ type: 'save-tab', tabId: tab.id, folder: $('folder').value.trim(), note: $('note').value.trim() })
  if (r?.ok) { $('out').className = 'small ok'; $('out').textContent = `Saved to ${r.item.folder}. The brief pops up when it's ready.`; setTimeout(() => window.close(), 1400) }
  else { $('out').className = 'small bad'; $('out').textContent = r?.error || 'Could not save.'; $('save').disabled = false }
}

try {
  const [{ folders }, { items }, here] = await Promise.all([
    api('/folders'), api('/items?limit=6'),
    /^https?:/.test(tab?.url || '') ? api(`/lookup?url=${encodeURIComponent(tab.url)}`) : Promise.resolve({}),
  ])
  showHere(here.item)
  $('folders').innerHTML = folders.map(f => `<option value="${esc(f.name)}">`).join('')
  $('recent').innerHTML = items.length ? items.map(i => `<div class="item"><a href="${esc(i.url)}" target="_blank">${esc(i.brief?.headline || i.title || i.url)}</a>
    <div class="muted">${esc(KIND_LABEL[i.kind] || i.kind)} · ${esc(i.folder)} <span class="pill ${esc(i.status)}">${esc(i.status === 'done' ? 'brief ready' : i.status)}</span></div></div>`).join('') : 'Nothing saved yet.'
} catch (e) { $('recent').className = 'small bad'; $('recent').textContent = e.message }
