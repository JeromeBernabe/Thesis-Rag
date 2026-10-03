/**
 * Cancel a run from the real window and require the run row to be closed out.
 *
 * Regression check for two bugs found by hand in the real app:
 *
 *   1. Cancelling killed the sidecar, which therefore never emitted
 *      `run_finished` - and that event was the only thing that ever set a
 *      terminal status, so the row stayed `running` for good.
 *   2. `cancel_run` was a synchronous command, so the kill ran on the main
 *      thread, where an unbounded `child.wait()` froze the whole window whenever
 *      `taskkill` did not do the job.
 *
 * The run is a *real* one, not a dry run, and that is deliberate. A dry run is
 * far too fast to cancel reliably, and inflating the prompt count to buy time
 * floods the webview with tens of thousands of events, which wedges the UI and
 * makes the test fail for reasons that have nothing to do with cancelling. Real
 * prompts take seconds each, so five of them leave ample room, and they produce
 * a realistic number of events.
 *
 * The trigger is the first prompt row appearing in the database rather than a
 * sleep, so the test does not race the run.
 *
 * Run from the desktop directory: node scripts/cancel-window.mjs
 */

import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'

import { chromium } from '@playwright/test'

const CDP = process.env.CDP_URL ?? 'http://127.0.0.1:9222'
const DESKTOP = resolve('.')
const DB = join(resolve(DESKTOP, '..'), 'data', 'bench', 'runs.sqlite3')

const counts = () =>
  JSON.parse(
    execFileSync('python', [join(DESKTOP, 'scripts', 'db-counts.py'), DB], { encoding: 'utf8' }),
  )

function fail(msg) {
  console.error(`FAIL: ${msg}`)
  process.exit(1)
}

const browser = await chromium.connectOverCDP(CDP)
const page = browser
  .contexts()
  .flatMap((c) => c.pages())
  .find((p) => p.url().includes('localhost:1420'))
if (!page) fail(`no app window found on ${CDP}`)

page.on('pageerror', (err) => console.log(`  [pageerror] ${err.message}`))

await page.getByRole('button', { name: /Configure another run/ }).click().catch(() => {})

// Real mode: judge off, twenty prompts. Slow enough to interrupt, small enough
// that the window stays responsive.
await page.getByRole('checkbox', { name: /^Skip judge/ }).check()
await page.getByRole('checkbox', { name: /^Dry run/ }).uncheck().catch(() => {})
await page.getByRole('spinbutton', { name: 'Prompts' }).fill('20')

const before = counts()
console.log(`runs before: ${before.runs}`)

await page.getByRole('button', { name: 'Start run' }).click()
await page
  .waitForFunction(
    () =>
      [...document.querySelectorAll('button')].some((b) => /Cancel run/i.test(b.textContent ?? '')),
    null,
    { timeout: 60_000 },
  )
  .catch(() => fail('the run never started'))

const started = counts().newest
if (!started || started.run_id === before.newest?.run_id) fail('no new run row appeared')
console.log(`started ${started.run_id}`)

// Trigger on the run's first event rather than its first finished prompt, and
// judge readiness from the database rather than a timer. Waiting for a completed
// prompt gave away most of the runway: twenty warm prompts finish faster than the
// click lands, so the run would be `completed` before the cancel arrived and the
// test would report a race rather than a defect.
const workDeadline = Date.now() + 120_000
while (Date.now() < workDeadline) {
  if (counts().events > before.events) break
  await page.waitForTimeout(200)
}
if (counts().events <= before.events) fail('the run never emitted an event to interrupt')
console.log(`interrupting after ${counts().events - before.events} event(s)`)

console.log('clicking Cancel run')
await page.getByRole('button', { name: 'Cancel run' }).click({ timeout: 30_000 })

// The row has to reach `cancelled` on its own, with no further prompting.
const deadline = Date.now() + 60_000
let run = null
while (Date.now() < deadline) {
  run = counts().newest
  if (run?.status !== 'running') break
  await page.waitForTimeout(500)
}

if (!run || run.run_id !== started.run_id) fail('the newest run is not the one we started')
if (run.status === 'running') {
  fail(`the run row is still 'running' ${counts().prompts - before.prompts} prompts in`)
}
if (run.status !== 'cancelled') fail(`expected 'cancelled', got '${run.status}'`)

console.log(`run ${run.run_id} is ${run.status}`)
console.log('\nOK: cancelling from the real window closes the run out')
await browser.close()
