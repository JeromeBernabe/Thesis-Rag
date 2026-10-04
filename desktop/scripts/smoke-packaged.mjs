/**
 * Smoke-test the packaged executable, which every other check so far has missed.
 *
 * `verify.ps1` builds a production bundle but never loads it, and
 * `verify-window.ps1` runs the app from `tauri dev`. Between them they leave the
 * one thing a release build can do differently untested: the packaged window
 * serves its assets from Tauri's own `tauri.localhost` protocol rather than the
 * Vite dev server, and everything routes off that.
 *
 * The failures this is looking for are all packaging-shaped rather than
 * behavioural, and none of them are reachable from the dev server:
 *
 *   - hash routing dying because `#/results` is now a request for a file called
 *     `results`, which does not exist;
 *   - a chunk or asset 404ing because the built bundle references it differently;
 *   - the sidecar failing to launch because the packaged process has a different
 *     working directory and inherits nothing from a dev shell.
 *
 * It reuses the database assertions the dev-window flow makes, because "the
 * window opened" is not evidence that the app works - a run reaching SQLite is.
 *
 * Run from the `desktop` directory: node scripts/smoke-packaged.mjs
 */

import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'

import { chromium } from '@playwright/test'

const CDP = process.env.CDP_URL ?? 'http://127.0.0.1:9223'
const RUN_TIMEOUT_MS = 180_000
const DESKTOP = resolve('.')
const DB = join(resolve(DESKTOP, '..'), 'data', 'bench', 'runs.sqlite3')

function python(script, args) {
  return execFileSync('python', [join(DESKTOP, 'scripts', script), ...args], {
    encoding: 'utf8',
  })
}

const dbCounts = () => JSON.parse(python('db-counts.py', [DB]))

function fail(msg) {
  console.error(`FAIL: ${msg}`)
  process.exit(1)
}

const nav = (page, label) =>
  page.getByRole('navigation', { name: 'Primary' }).getByRole('button', { name: label })

const browser = await chromium.connectOverCDP(CDP)
// Matched by title rather than by URL: the dev window is on localhost:1420 and
// this one is on tauri.localhost, and needing to tell them apart is the point.
const page = browser
  .contexts()
  .flatMap((c) => c.pages())
  .find((p) => p.url().includes('tauri.localhost'))
if (!page) fail(`no packaged window found on ${CDP}`)

page.on('pageerror', (err) => console.log(`  [pageerror] ${err.message}`))
page.on('console', (msg) => {
  if (msg.type() === 'error') console.log(`  [console.error] ${msg.text()}`)
})

console.log(`attached to "${await page.title()}" at ${page.url()}`)

/* ------------------------------------------------------- the packaged shell */

if (!(await page.title()).includes('RAG Benchmark Console')) {
  fail(`unexpected packaged window title "${await page.title()}"`)
}
await page.getByRole('navigation', { name: 'Primary' }).waitFor({ timeout: 30_000 })
console.log('  window is serving the packaged assets, not the dev server')

// The header's run count comes from `list_runs`, so a number here means the
// command layer, the IPC serialisation and the real database all worked from a
// release binary. A blank or a zero-width element means one of them did not.
const runCount = page.locator('header').getByText(/^\d+ runs?$/)
await runCount.waitFor({ timeout: 30_000 }).catch(() => fail('the header never showed a run count'))
console.log(`  list_runs answered: "${(await runCount.textContent())?.trim()}"`)

// A `role="alert"` here is the app's own "Tauri could not be reached" banner,
// which is what a page opened outside the host looks like. It must not be there.
if (await page.getByRole('alert').count()) {
  fail(`the packaged app reported a host error: ${await page.getByRole('alert').first().innerText()}`)
}

/* ---------------------------------------------------------- hash routing */

await nav(page, 'Results').click()
await page.getByRole('combobox', { name: 'Run' }).waitFor({ timeout: 30_000 })
const options = await page.getByRole('combobox', { name: 'Run' }).locator('option').count()
if (options === 0) fail('Results rendered but offered no runs, so a route failed to load its data')
console.log(`  #/results routed and offered ${options} run(s)`)

await nav(page, 'Simulation').click()
await page.getByText('Pipeline').first().waitFor({ timeout: 30_000 })
console.log('  #/simulation routed')

await nav(page, 'Run').click()

/* -------------------------------------------------- a real run, packaged */

// Dry run, because this is about the packaging, not about retrieval quality - but
// still a real launch of the sidecar from the packaged process.
await page
  .getByRole('button', { name: /Configure another run/ })
  .click({ timeout: 5_000 })
  .catch(() => {})
await page.getByRole('checkbox', { name: /^Dry run/ }).check()
await page.getByRole('spinbutton', { name: 'Prompts' }).fill('1')

const before = dbCounts()
console.log('clicking Start run')
await page.getByRole('button', { name: 'Start run' }).click()
await page
  .waitForFunction(
    () =>
      [...document.querySelectorAll('button')].some((b) => /Cancel run/i.test(b.textContent ?? '')),
    null,
    { timeout: 60_000 },
  )
  .catch(() => fail('the packaged app never started a run'))

const deadline = Date.now() + RUN_TIMEOUT_MS
let run = null
while (Date.now() < deadline) {
  run = dbCounts().newest
  if (run?.status === 'completed') break
  if (run?.status === 'failed') fail(`run failed: ${run.error}`)
  await page.waitForTimeout(500)
}
if (run?.status !== 'completed') fail(`run did not complete, status=${run?.status}`)
if (run.run_id === before.newest?.run_id) fail('no new run row appeared')
console.log(`  run ${run.run_id} completed from the packaged binary`)

// Clean up after ourselves, the same way the dev-window pages flow does.
await nav(page, 'Results').click()
await page.getByRole('combobox', { name: 'Run' }).selectOption(run.run_id)
await page.getByRole('button', { name: 'Delete run' }).click({ timeout: 30_000 })
const deleteDeadline = Date.now() + 30_000
while (Date.now() < deleteDeadline) {
  const after = dbCounts()
  if (after.runs === before.runs) break
  await page.waitForTimeout(250)
}
if (dbCounts().runs !== before.runs) fail('the smoke-test run was not cleaned up')

console.log('\nOK: the packaged app routes, reads the database and launches the sidecar')
await browser.close()