// Hermes Brief service worker: right-click menus, the shortcut, the watched "Hermes" bookmarks folder, notifications.
// It reads a page only when you save it (button, menu, shortcut or a bookmark of the tab you're on).
import { api, readTab, settings } from './lib.js'

chrome.runtime.onInstalled.addListener(async () => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: 'save-link', title: 'Save link to Hermes', contexts: ['link'] })
    chrome.contextMenus.create({ id: 'save-page', title: 'Save page to Hermes', contexts: ['page', 'frame', 'video'] })
    chrome.contextMenus.create({ id: 'save-selection', title: 'Save page + highlight to Hermes', contexts: ['selection'] })
  })
  await ensureFolder()
  if (!(await settings()).key) chrome.runtime.openOptionsPage()   // first run: pair with Hermes
})

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === 'save-link') return saveUrl(info.linkUrl, { source: 'link', title: info.selectionText || '' })
  return saveTab(tab, { source: info.menuItemId === 'save-selection' ? 'selection' : 'menu' })
})

chrome.commands.onCommand.addListener(async (command, tab) => {
  tab = tab || (await chrome.tabs.query({ active: true, currentWindow: true }))[0]
  if (!tab) return
  if (command === 'save-page') return saveTab(tab, { source: 'shortcut' })
})

// The popup asks the worker to save, so a save finishes even if the popup closes.
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg?.type === 'save-tab') {
    chrome.tabs.get(msg.tabId).then(tab => saveTab(tab, { source: 'button', folder: msg.folder, note: msg.note }))
      .then(item => reply({ ok: true, item }), err => reply({ ok: false, error: String(err.message || err) }))
    return true
  }
})

export async function saveTab(tab, { source = 'button', folder = '', note = '' } = {}) {
  if (!/^https?:/.test(tab?.url || '')) throw new Error('Only web pages can be saved.')
  let page = {}
  // Without access to the site (e.g. a bookmark of a page you never clicked the extension on), Hermes reads the link itself.
  try { page = await readTab(tab.id) } catch (e) { page = { meta: { read_by: 'hermes', read_error: e.message === 'NEEDS_ACCESS' ? '' : String(e).slice(0, 200) } } }
  return save({ url: tab.url, title: page.title || tab.title, kind: page.kind, content: page.content, selection: page.selection,
                meta: page.meta, folder, note, source })
}

async function saveUrl(url, extra = {}) {
  if (!/^https?:/.test(url || '')) return
  return save({ url, ...extra })
}

async function save(body) {
  try {
    const item = await api('/items', { method: 'POST', body })
    notify(item.id, 'Saved to Hermes', `${item.title || item.url}\nIn ${item.folder}. Hermes is reading it now.`)
    watchBrief(item.id)
    return item
  } catch (e) {
    notify('err', 'Hermes Brief could not save', String(e.message || e))
    throw e
  }
}

// Tell the user when the brief is ready (polls for up to 3 minutes).
async function watchBrief(id) {
  for (let i = 0; i < 36; i++) {
    await new Promise(r => setTimeout(r, 5000))
    let item
    try { item = await api(`/items/${id}`) } catch { return }
    if (item.status === 'done') return notify(id, item.brief?.headline || 'Brief ready', (item.brief?.key_points || []).slice(0, 2).join(' · '))
    if (item.status === 'error') return notify(id, 'Brief failed', item.error || item.url)
  }
}

async function notify(id, title, message) {
  if (!(await settings()).notify) return
  chrome.notifications.create(`hb-${id}-${Date.now()}`, { type: 'basic', iconUrl: 'icons/128.png', title, message: String(message).slice(0, 300) })
}

// ── the watched bookmarks folder ──────────────────────────────────────────
// Bookmark anything into "Hermes" (or a subfolder of it) and it is saved; the subfolder name becomes the Brief folder.
async function ensureFolder() {
  const { folderName } = await settings()
  const found = await chrome.bookmarks.search({ title: folderName })
  if (found.some(n => !n.url)) return
  const tree = await chrome.bookmarks.getTree()
  const roots = tree[0].children || []
  const parent = roots.find(n => n.id === '2') || roots[roots.length - 1]   // "Other bookmarks"
  await chrome.bookmarks.create({ parentId: parent.id, title: folderName })
}

async function folderFor(node) {
  const { folderName } = await settings()
  let id = node.parentId, child = ''
  while (id) {
    const [p] = await chrome.bookmarks.get(id)
    if (!p) return null
    if (p.title === folderName && !p.url) return child || ''
    child = p.title
    id = p.parentId
  }
  return null
}

chrome.bookmarks.onCreated.addListener(async (_id, node) => {
  if (!node.url) return
  const folder = await folderFor(node)
  if (folder === null) return
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  // Bookmarking the page you're on (Ctrl+D): read it from the tab, so logged-in pages and video captions come too.
  if (tab && tab.url === node.url) return saveTab(tab, { source: 'bookmark', folder }).catch(() => {})
  return saveUrl(node.url, { title: node.title, folder, source: 'bookmark' }).catch(() => {})
})

chrome.bookmarks.onMoved.addListener(async (id, move) => {
  const [node] = await chrome.bookmarks.get(id)
  if (!node?.url) return
  const folder = await folderFor(node)
  if (folder === null) return
  saveUrl(node.url, { title: node.title, folder, source: 'bookmark' }).catch(() => {})
})

// For tests and the DevTools console: hermesBrief.saveTab(tab)
globalThis.hermesBrief = { saveTab, readTab }
