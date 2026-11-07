// Run the extension's page reader inside real pages (YouTube, a docs article) in Chromium. Needs network.
import { chromium } from '/home/bkash86/Claude/videos/nous-calendar-launch/rec/node_modules/playwright-core/index.mjs'
globalThis.chrome = { storage: { local: { get: async () => ({}) } } }
const { pageReader } = await import('../extension/lib.js')
const b = await chromium.launch({ executablePath: process.env.CHR, headless: true })
const p = await b.newPage()
for (const url of ['https://www.youtube.com/watch?v=jNQXAC9IVRw', 'https://hermes-agent.nousresearch.com/docs/developer-guide/plugin-llm-access']) {
  await p.goto(url, { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(5000)
  const r = await p.evaluate(`(${pageReader.toString()})()`)
  console.log(`== ${r.kind} | ${r.title} | ${JSON.stringify(r.meta)} | ${r.content.length} chars\n${r.content.slice(0, 300).replace(/\n/g, ' / ')}`)
}
await b.close()
