// Load the real extension into Chromium (new headless) against tests/mock_hermes.py on :8799.
import { chromium } from '/home/bkash86/Claude/videos/nous-calendar-launch/rec/node_modules/playwright-core/index.mjs'
import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path'
const EXT = path.resolve(new URL('../extension', import.meta.url).pathname)
const MOCK = 'http://127.0.0.1:8799'
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hb-e2e-'))
const ctx = await chromium.launchPersistentContext(dir, { executablePath: process.env.CHR, headless: true,
  args: ['--headless=new', `--disable-extensions-except=${EXT}`, `--load-extension=${EXT}`] })
let [sw] = ctx.serviceWorkers(); if (!sw) sw = await ctx.waitForEvent('serviceworker')
const extId = sw.url().split('/')[2]
const ok = (c, m) => { if (!c) { console.error('FAIL', m); process.exit(1) } console.log('ok', m) }
await sw.evaluate(async (base) => chrome.storage.local.set({ base, key: 'test-key', notify: false }), MOCK)

// 1. the folder exists
const folders = await sw.evaluate(async () => (await chrome.bookmarks.search({ title: 'Hermes' })).filter(n => !n.url).length)
ok(folders === 1, 'created the "Hermes" bookmarks folder')

// 2. save the open tab through the extension's own save path (page read in the tab, sent with content)
const page = await ctx.newPage(); await page.goto(`${MOCK}/test-article`)
const item = await sw.evaluate(async (base) => {
  const [tab] = await chrome.tabs.query({ url: base + '/test-article' })
  return hermesBrief.saveTab(tab, { folder: 'Agents', note: 'try it' })
}, MOCK)
ok(item.folder === 'Agents' && item.has_content && item.meta.note === 'try it' && item.meta.read_by === 'browser', 'saved the page with its text read from the tab')
const H = { Authorization: 'Bearer test-key' }
let got
for (let i = 0; i < 30; i++) { got = await (await fetch(`${MOCK}/api/plugins/hermes-brief/items/${item.id}`, { headers: H })).json(); if (got.status === 'done') break; await new Promise(r => setTimeout(r, 300)) }
ok(got.brief?.headline === 'Brief of: Mock article about agents' && got.brief.key_points[0] === 'read by the browser', 'brief written from the browser-read text (the logged-in-only line was included)')

// 3. bookmark into Hermes/Reading -> saved into folder "Reading"
const saved = await sw.evaluate(async (base) => {
  const [root] = (await chrome.bookmarks.search({ title: 'Hermes' })).filter(n => !n.url)
  const sub = await chrome.bookmarks.create({ parentId: root.id, title: 'Reading' })
  await chrome.bookmarks.create({ parentId: sub.id, title: 'Example', url: 'https://example.com/?utm_source=x' })
  await new Promise(r => setTimeout(r, 1500))
  return true
}, MOCK)
const list = await (await fetch(`${MOCK}/api/plugins/hermes-brief/items`, { headers: H })).json()
const bm = list.items.find(i => i.url.startsWith('https://example.com'))
ok(bm && bm.folder === 'Reading' && bm.source === 'bookmark', 'a bookmark into Hermes/Reading was saved into folder "Reading"')

// 4. a bookmark elsewhere is ignored
await sw.evaluate(async () => { const tree = await chrome.bookmarks.getTree(); await chrome.bookmarks.create({ parentId: tree[0].children[0].id, title: 'Not me', url: 'https://example.org/' }); await new Promise(r => setTimeout(r, 1200)) })
const list2 = await (await fetch(`${MOCK}/api/plugins/hermes-brief/items`, { headers: H })).json()
ok(!list2.items.some(i => i.url.startsWith('https://example.org')), 'bookmarks outside the Hermes folder are ignored')

// 5. popup and side panel pages load and talk to Hermes
const pop = await ctx.newPage(); await pop.goto(`chrome-extension://${extId}/popup.html`); await pop.waitForTimeout(1200)
const recent = await pop.locator('#recent').innerText()
ok(recent.includes('Brief of: Mock article'), 'popup lists recent briefs')
const opt = await ctx.newPage(); await opt.goto(`chrome-extension://${extId}/options/options.html`); await opt.click('#save'); await opt.waitForTimeout(800)
ok((await opt.locator('#out').innerText()).startsWith('Connected'), 'options page "Save and test" connects')
await ctx.close(); console.log('extension e2e: all ok')
