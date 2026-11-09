import { api, pair, settings, DEFAULTS } from '../lib.js'
const $ = id => document.getElementById(id)
const s = await settings()
$('base').value = s.base; $('folder').value = s.folderName; $('notify').checked = s.notify
$('key').value = s.key && !s.key.startsWith('hb_') ? s.key : ''
const localBase = v => /^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?\/?$/.test(v)

async function test(out) {
  try {
    const st = await api('/status')
    out.className = 'small ok'; out.textContent = `Connected to Hermes Brief ${st.version}. ${st.items} saved so far.`
  } catch (e) { out.className = 'small bad'; out.textContent = e.message }
}
if (s.key) test($('out'))

$('connect').onclick = async () => {
  const out = $('out'), base = $('base').value.trim() || DEFAULTS.base
  const code = $('code').value.replace(/\D/g, '')
  if (code.length !== 6) { out.className = 'small bad'; out.textContent = 'Enter the 6 digits from the Briefs page.'; return }
  if (!localBase(base)) { out.className = 'small bad'; out.textContent = 'The Hermes address must be on this computer (127.0.0.1).'; return }
  out.className = 'small'; out.textContent = 'Connecting…'
  try {
    const token = await pair(base, code)
    await chrome.storage.local.set({ base, key: token })
    $('code').value = ''
    await test(out)
  } catch (e) { out.className = 'small bad'; out.textContent = e.message }
}

$('save').onclick = async () => {
  const out = $('out2'), base = $('base').value.trim() || DEFAULTS.base
  if (!localBase(base)) { out.className = 'small bad'; out.textContent = 'Use a local address like http://127.0.0.1:8642.'; return }
  const patch = { base, folderName: $('folder').value.trim() || 'Hermes', notify: $('notify').checked }
  if ($('key').value.trim()) patch.key = $('key').value.trim()
  await chrome.storage.local.set(patch)
  await test(out)
}
