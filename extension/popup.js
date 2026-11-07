import { api, esc, KIND_LABEL } from './lib.js'
const $ = id => document.getElementById(id)
const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
$('title').textContent = tab?.title || ''
$('opts').onclick = e => { e.preventDefault(); chrome.runtime.openOptionsPage() }
$('ask').onclick = async () => { await chrome.sidePanel.open({ tabId: tab.id }); window.close() }
$('save').onclick = async () => {
  $('save').disabled = true; $('out').className = 'small'; $('out').textContent = 'Saving…'
  const r = await chrome.runtime.sendMessage({ type: 'save-tab', tabId: tab.id, folder: $('folder').value.trim(), note: $('note').value.trim() })
  if (r?.ok) { $('out').className = 'small ok'; $('out').textContent = `Saved to ${r.item.folder}. The brief will pop up when it's ready.`; setTimeout(() => window.close(), 1400) }
  else { $('out').className = 'small bad'; $('out').textContent = r?.error || 'Could not save.'; $('save').disabled = false }
}
try {
  const [{ folders }, { items }] = await Promise.all([api('/folders'), api('/items?limit=6')])
  $('folders').innerHTML = folders.map(f => `<option value="${esc(f.name)}">`).join('')
  $('recent').innerHTML = items.length ? items.map(i => `<div class="item"><a href="${esc(i.url)}" target="_blank">${esc(i.brief?.headline || i.title || i.url)}</a>
    <div class="muted">${esc(KIND_LABEL[i.kind] || i.kind)} · ${esc(i.folder)} <span class="pill ${esc(i.status)}">${esc(i.status === 'done' ? 'brief ready' : i.status)}</span></div></div>`).join('') : 'Nothing saved yet.'
} catch (e) { $('recent').className = 'small bad'; $('recent').textContent = e.message }
