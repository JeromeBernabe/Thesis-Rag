/**
 * Exercise the Results and Simulation pages against the real host.
 *
 * `drive-window.mjs` and `cancel-window.mjs` both stop at the Run page, so every
 * command those two reach - `start_run`, `cancel_run`, `app_info`, `list_runs` -
 * had been driven for real, and everything the other pages call had not. The
 * browser suite covers the rest, but against a mocked `api` module, so a wrong
 * argument name, a bad serde shape or a command that was never registered would
 * all pass there and fail only here.
 *
 * This drives the pages themselves rather than calling commands directly. The app
 * does not expose `withGlobalTauri`, so `window.__TAURI__` is not reachable from
 * the page and there is no way to invoke a command without a UI affordance to
 * click. That constraint is the point of the next note.
 *
 * Six commands have no affordance at all and so cannot be reached this way:
 * `run_in_progress`, `get_run_events`, `get_stats`, `get_projection`,
 * `list_projections` and `import_legacy` are referenced only from `lib/api.ts` and
 * its mock. They are listed here so the gap stays visible rather than being
 * rediscovered as "the commands are covered, they must be fine".
 *
 * The run is a dry run, because this is about reading and deleting stored rows,
 * not about retrieval quality - and because a dry run finishes in seconds. It is
 * still a real run through the real host, and it is deleted at the end, so the
 * script leaves the database exactly as it found it.
 *
 * Requires the app to already be running with the debugging port set; see
 * scripts/verify-window.ps1.
 *
 * Run from the `desktop` directory: node scripts/pages-window.mjs
 */

import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'

import { chromium } from '@playwright/test'

const CDP = process.env.CDP_URL ?? 'http://127.0.0.1:9222'
const RUN_TIMEOUT_MS = 180_000
const DESKTOP = resolve('.')
const DB = join(resolve(DESKTOP, '..'), 'data', 'bench', 'runs.sqlite3')

/* ---------------------------------------------------------------- helpers */

function python(script, args) {
  return execFileSync('python', [join(DESKTOP, 'scripts', script), ...args], {
    encoding: 'utf8',
  })
}

const dbCounts = () => JSON.parse(python('db-counts.py', [DB]))

/**
 * `describe-run.py` exits non-zero for a run that is gone, which is a legitimate
 * answer when checking a deletion rather than a crash, so the output is read off
 * the failure instead of being allowed to throw.
 */
function describeRun(runId) {
  try {
    return JSON.parse(python('describe-run.py', [runId, DB]))
  } catch (err) {
    const out = err?.stdout ? String(err.stdout) : ''
    if (out.includes('"found"')) return JSON.parse(out)
    throw err
  }
}

function fail(msg) {
  console.error(`FAIL: ${msg}`)
  process.exit(1)
}

const nav = (page, label) =>
  page.getByRole('navigation', { name: 'Primary' }).getByRole('button', { name: label })

/* ------------------------------------------------------------------- main */

const browser = await chromium.connectOverCDP(CDP)
const page = browser
  .contexts()
  .flatMap((c) => c.pages())
  .find((p) => p.url().includes('localhost:1420'))
if (!page) fail(`no app window found on ${CDP}`)

page.on('pageerror', (err) => console.log(`  [pageerror] ${err.message}`))
page.on('console', (msg) => {
  if (msg.type() === 'error') console.log(`  [console.error] ${msg.text()}`)
})

await page.getByRole('navigation', { name: 'Primary' }).waitFor({ timeout: 30_000 })

const before = dbCounts()
console.log(`runs before: ${before.runs} (prompts ${before.prompts}, events ${before.events})`)

/* ------------------------------------------------- a run of our own to read */

// Dry run and one prompt: the point is stored rows, not retrieval quality.
await nav(page, 'Run').click()
// The Run page swaps its form for a summary once a run finishes, so after the
// cancel flow there is no Start button until this is clicked. Optional, because a
// window that has not run anything yet shows the form already.
await page
  .getByRole('button', { name: /Configure another run/ })
  .click({ timeout: 5_000 })
  .catch(() => {})
await page.getByRole('checkbox', { name: /^Dry run/ }).check()
await page.getByRole('spinbutton', { name: 'Prompts' }).fill('1')

console.log('clicking Start run')
await page.getByRole('button', { name: 'Start run' }).click()
await page
  .waitForFunction(
    () =>
      [...document.querySelectorAll('button')].some((b) => /Cancel run/i.test(b.textContent ?? '')),
    null,
    { timeout: 60_000 },
  )
  .catch(() => fail('the run never started'))

// Claim the run by diffing the newest row rather than trusting a timer, and
// require it to be a different row than the one that was newest before.
let started = null
const claimDeadline = Date.now() + 30_000
while (Date.now() < claimDeadline) {
  const newest = dbCounts().newest
  if (newest && newest.run_id !== before.newest?.run_id) {
    started = newest
    break
  }
  await page.waitForTimeout(200)
}
if (!started) fail('no new run row appeared')
const runId = started.run_id
console.log(`started ${runId}`)

const runDeadline = Date.now() + RUN_TIMEOUT_MS
let run = null
while (Date.now() < runDeadline) {
  run = dbCounts().newest
  if (run?.status === 'completed') break
  if (run?.status === 'failed') fail(`run failed: ${run.error}`)
  await page.waitForTimeout(500)
}
if (run?.status !== 'completed') fail(`run did not complete, status=${run?.status}`)

const detail = describeRun(runId)
if (!detail.found) fail('the completed run is not in the database')
if (detail.prompts === 0) fail('the completed run stored no prompt rows to read')
console.log(`completed with ${detail.prompts} stored prompt row(s)`)

/* ------------------------------------------------------------ Results page */

console.log('opening Results')
await nav(page, 'Results').click()

// Select our run explicitly. The page defaults to the newest, which is usually
// ours but not guaranteed once earlier runs share a creation timestamp.
const runPicker = page.getByRole('combobox', { name: 'Run' })
await runPicker.waitFor({ timeout: 30_000 })
if ((await runPicker.locator('option').allTextContents()).length === 0) {
  fail('the run picker is empty, so list_runs returned nothing')
}
await runPicker.selectOption(runId).catch(() => fail(`run ${runId} is not offered by list_runs`))

// get_run_detail is the one call this page makes, and it feeds every panel below,
// so a rendered summary tile is proof the whole payload deserialised.
//
// The label is a direct child of its tile, so the parent is the tile and its text
// is the label followed by the value and the hint. Requiring a digit catches a
// tile that rendered with no value at all, which is what a missing field looks like.
const rowsStoredTile = page.getByText('Rows stored', { exact: true }).locator('xpath=..')
await rowsStoredTile
  .waitFor({ timeout: 30_000 })
  .catch(() => fail('the Results summary never rendered'))
const rowsStored = await rowsStoredTile.textContent()
console.log(`  summary tiles rendered, rows stored reads "${rowsStored?.trim()}"`)
if (!/\d/.test(rowsStored ?? '')) fail(`"Rows stored" rendered no number: ${rowsStored}`)

const promptPanel = page.getByText(/stored rows?$/).first()
await promptPanel.waitFor({ timeout: 30_000 }).catch(() => fail('the prompt table never rendered'))

// The 3D panel calls get_projection_data for this run's dataset. Whichever way it
// resolves is a pass, as long as it resolves: "no projection" means the command
// came back null, points means it came back with data. An error panel, or a
// spinner that never resolves, is a failure - and this asserts on the resolved
// state rather than one hardcoded string, because the dataset decides which of the
// two good outcomes to expect.
const spacePanel = page
  .getByRole('heading', { name: 'Embedding space' })
  // heading -> its wrapper -> PanelHeader -> Panel. The state lives in the Panel's
  // body, which is a sibling of the header rather than a child of it.
  .locator('xpath=../../..')
await spacePanel.waitFor({ timeout: 30_000 }).catch(() => fail('the embedding-space panel never appeared'))

let space = ''
const spaceDeadline = Date.now() + 30_000
while (Date.now() < spaceDeadline) {
  space = (await spacePanel.textContent()) ?? ''
  if (!/Loading projection/.test(space)) break
  await page.waitForTimeout(250)
}
if (/Loading projection/.test(space)) fail('the projection lookup never resolved')

const resolved = /No projection for \w+/.test(space)
  ? 'no projection for this dataset, so the command returned null'
  : /\d+\s+documents/.test(space)
    ? 'points rendered'
    : null
if (!resolved) fail(`the embedding-space panel is in an unexpected state: ${space.trim()}`)

console.log(`  prompt table rendered; embedding space: ${resolved}`)

/* --------------------------------------------------------- Simulation page */

console.log('opening Simulation')
await nav(page, 'Simulation').click()

const simPicker = page.getByRole('combobox', { name: 'Run' })
await simPicker.waitFor({ timeout: 30_000 })
await simPicker.selectOption(runId).catch(() => fail(`run ${runId} is not offered on Simulation`))

// Reads the same stored rows, and renders per-stage timings measured from them.
await page
  .getByText('Pipeline')
  .first()
  .waitFor({ timeout: 30_000 })
  .catch(() => fail('the Simulation pipeline never rendered'))
await page
  .getByText('Measured')
  .waitFor({ timeout: 30_000 })
  .catch(() => fail('the Simulation measured panel never rendered'))
console.log('  pipeline and measured timings rendered')

/* ----------------------------------------------------------------- cleanup */

console.log('deleting the run from the Results page')
await nav(page, 'Results').click()
await page.getByRole('combobox', { name: 'Run' }).selectOption(runId)
await page.getByRole('button', { name: 'Delete run' }).click({ timeout: 30_000 })

// delete_run has to remove the run and cascade to its rows, and it has to do so
// through the real command rather than a local state edit.
const deleteDeadline = Date.now() + 30_000
let gone = false
while (Date.now() < deleteDeadline) {
  if (describeRun(runId).found === false) {
    gone = true
    break
  }
  await page.waitForTimeout(250)
}
if (!gone) fail('the run row survived the delete')

const after = dbCounts()
if (after.runs !== before.runs) fail(`run count is ${after.runs}, expected ${before.runs}`)
if (after.prompts !== before.prompts) {
  fail(`${after.prompts} prompt rows left behind, expected ${before.prompts} - the delete did not cascade`)
}
if (after.events !== before.events) {
  fail(`${after.events} events left behind, expected ${before.events} - the delete did not cascade`)
}
console.log('  run, rows and events all removed')

console.log('\nOK: Results and Simulation read real data, and deleting cleaned up after itself')
await browser.close()
