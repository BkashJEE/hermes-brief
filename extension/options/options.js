import { api, settings, DEFAULTS } from '../lib.js'
const $ = id => document.getElementById(id)
const s = await settings()
$('base').value = s.base; $('profile').value = s.profile; $('key').value = s.key; $('folder').value = s.folderName; $('notify').checked = s.notify
$('save').onclick = async () => {
  const out = $('out')
  const base = $('base').value.trim() || DEFAULTS.base
  if (!/^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?\/?$/.test(base)) { out.className = 'small bad'; out.textContent = 'Use a local address like http://127.0.0.1:8642.'; return }
  await chrome.storage.local.set({ base, profile: $('profile').value.trim(), key: $('key').value.trim(), folderName: $('folder').value.trim() || 'Hermes', notify: $('notify').checked })
  out.className = 'small'; out.textContent = 'Testing…'
  try {
    const st = await api('/status')
    out.className = 'small ok'; out.textContent = `Connected: Hermes Brief ${st.version} on profile "${st.profile}", ${st.items} saved.`
  } catch (e) { out.className = 'small bad'; out.textContent = e.message }
}
