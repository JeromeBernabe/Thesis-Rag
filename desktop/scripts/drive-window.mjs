/**
 * Drive the real Tauri window and start a run through the real UI.
 *
 * Every other check either stubs the host or calls the sidecar directly, so
 * nothing had ever crossed the last seam: an actual click in an actual WebView
 * going through `invoke`, the Tauri command layer, the run-row insert and the
 * process spawn. That is where a wrong argument name or a misregistered command
 * would surface, and it is exactly the class of bug that already bit twice.
 *
 * The WebView is attached over the DevTools protocol rather than through
 * `tauri-driver`, which would need an msedgedriver matching the installed
 * runtime. `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port`
 * exposes the same DOM with nothing extra installed.
 *
 * Requires the app to already be running with that argument set; see
 * scripts/verify-window.ps1.
 *
 * Run from the `desktop` directory: node scripts/drive-window.mjs
 */

import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'

import { chromium } from '@playwright/test'

const CDP = process.env.CDP_URL ?? 'http://127.0.0.1:9222'
const RUN_TIMEOUT_MS = 180_000
const DESKTOP = resolve('.')
const REPO = resolve(DESKTOP, '..')
const DB = join(REPO, 'data', 'bench', 'runs.sqlite3')

/* ---------------------------------------------------------------- helpers */

function python(script, args) {
  return execFileSync('python', [join(DESKTOP, 'scripts', script), ...args], {
    encoding: 'utf8',
  })
}

function dbCounts() {
  return JSON.parse(python('db-counts.py', [DB]))
}

function describeRun(runId) {
  return JSON.parse(python('describe-run.py', [runId, DB]))
}

function fail(msg) {
  console.error(`FAIL: ${msg}`)
  process.exit(1)
}

/* ------------------------------------------------------------------- main */

const browser = await chromium.connectOverCDP(CDP)
let page = null
for (const ctx of browser.contexts()) {
  for (const candidate of ctx.pages()) {
    if (candidate.url().includes('localhost:1420')) page = candidate
  }
}
if (!page) fail(`no app window found on ${CDP}`)

page.on('console', (msg) => {
  if (msg.type() === 'error') console.log(`  [console.error] ${msg.text()}`)
})
page.on('pageerror', (err) => console.log(`  [pageerror] ${err.message}`))

console.log(`attached to "${await page.title()}"`)
await page.getByRole('navigation', { name: 'Primary' }).waitFor({ timeout: 30_000 })

const before = dbCounts()
console.log(`runs before: ${before.runs} (prompts ${before.prompts}, events ${before.events})`)

// Dry run: exercises the whole host path - command, argv, protocol, database -
// in seconds, with in-process fakes standing in for the models.
await page.getByRole('checkbox', { name: /^Dry run/ }).check()
// By role, because "Prompts" is also the start of "Rebuild prompts".
await page.getByRole('spinbutton', { name: 'Prompts' }).fill('1')

// Baseline only, so the run cannot be held up by DQN training.
await page.getByRole('button', { name: /DQN/ }).click()

console.log('clicking Start run')
await page.getByRole('button', { name: 'Start run' }).click()

// The host refuses the click outright if the command layer is broken, so a
// running state already proves `invoke('start_run', ...)` landed with arguments
// the Rust side could deserialise.
await page
  .waitForFunction(
    () =>
      [...document.querySelectorAll('button')].some((b) => /Cancel run/i.test(b.textContent ?? '')),
    null,
    { timeout: 60_000 },
  )
  .catch(() => fail('the window never showed a running run after Start was clicked'))
console.log('window shows a running run')

// Wait for completion *in the database*, which is the only claim worth making:
// the window can look busy while nothing was stored.
const deadline = Date.now() + RUN_TIMEOUT_MS
let run = null
while (Date.now() < deadline) {
  run = dbCounts().newest
  if (run?.status === 'completed') break
  if (run?.status === 'failed') fail(`run failed: ${run.error}`)
  await page.waitForTimeout(1000)
}

if (!run) fail('no run row was ever written')
if (run.status !== 'completed') fail(`run did not complete, status=${run.status}`)

console.log(`run ${run.run_id} completed in the database`)

const detail = describeRun(run.run_id)
console.log(`  prompts: ${detail.prompts}, events: ${detail.events}`)
console.log(`  nulls preserved: ${detail.nulls.join(', ') || 'none'}`)
if (detail.prompts === 0) fail('a completed run persisted no prompt rows')
if (detail.events === 0) fail('a completed run persisted no events')
if (!detail.nulls.includes('context_recall')) {
  fail('unmeasured metrics must stay null rather than 0')
}
if (detail.samplePrompt && typeof detail.samplePrompt.answer !== 'string') {
  fail('the answer text did not survive the round trip')
}

console.log('\nOK: a run started from the real window reached the real database')
await browser.close()
