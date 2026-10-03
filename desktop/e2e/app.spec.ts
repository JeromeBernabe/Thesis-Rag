import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { expect, test } from '@playwright/test'

import { stubTauri } from './fixtures'

/**
 * The user-visible contract: navigation works, a run can be configured and
 * started, results render against stored data, and the simulation replays it.
 */

test.beforeEach(async ({ page }) => {
  await stubTauri(page)
})

/**
 * A packaged build must load its assets over Tauri's own protocol, where a
 * root-absolute path resolves to nothing. This reads the built HTML rather than
 * driving a page, because the preview server would happily serve a broken path -
 * it is only the packaged window that breaks.
 *
 * Lives here rather than in the Vitest suite because `dist/` only exists after a
 * build, and this suite runs against that build.
 */
test('the production build references its assets relatively', () => {
  const html = readFileSync(resolve(process.cwd(), 'dist/index.html'), 'utf8')

  const refs = [...html.matchAll(/(?:src|href)="([^"]+)"/g)].map((m) => m[1])
  expect(refs.length).toBeGreaterThan(0)
  for (const ref of refs) {
    // Data URIs and absolute URLs are fine; a bare "/..." is not.
    expect(ref, `${ref} must not be root-absolute in a packaged build`).not.toMatch(/^\/(?!\/)/)
  }
  expect(html).toContain('<title>RAG Benchmark Console</title>')
})

test('opens on the run page and lists the datasets the host reports', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('navigation', { name: 'Primary' })).toBeVisible()
  // `exact` matters: "Start run" and "Run" both contain "Run".
  await expect(page.getByRole('button', { name: 'Run', exact: true })).toHaveAttribute('aria-current', 'page')
  await expect(page.getByRole('heading', { level: 1, name: 'Run' })).toBeAttached()
  // `toHaveValues` is for multi-selects; this one is a single select, so assert
  // the option texts instead.
  await expect(page.getByLabel('Dataset', { exact: true }).locator('option')).toHaveText([
    'hotpot',
    'fintech',
    'math',
    'ragtruth',
  ])
})

test('navigates between the three pages and back', async ({ page }) => {
  await page.goto('/')

  await page.getByRole('button', { name: 'Results', exact: true }).click()
  await expect(page).toHaveURL(/#\/results$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Results' })).toBeAttached()

  await page.getByRole('button', { name: 'Simulation', exact: true }).click()
  await expect(page).toHaveURL(/#\/simulation$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Simulation' })).toBeAttached()

  // Reload must land back on the same page, not silently fall back to Run. This
  // is the reason routing is a hash: over the packaged Tauri asset protocol a
  // path-based URL is a request for a file that does not exist.
  await page.reload()
  await expect(page.getByRole('heading', { level: 1, name: 'Simulation' })).toBeAttached()

  await page.getByRole('button', { name: 'Run', exact: true }).click()
  await expect(page).toHaveURL(/#\/$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Run' })).toBeAttached()
})

test('starts a dry run with the chosen settings', async ({ page }) => {
  await page.goto('/')

  await page.getByLabel('Dataset', { exact: true }).selectOption('fintech')
  await page.getByLabel('Prompts', { exact: true }).fill('3')
  await page.getByLabel('Seed', { exact: true }).fill('7')
  await page.getByRole('checkbox', { name: 'Dry run' }).check()
  await page.getByRole('button', { name: 'Start run' }).click()

  // The shell reflects the new run immediately; the button becomes Cancel.
  await expect(page.getByRole('button', { name: 'Cancel run' })).toBeVisible()
  await expect(page.getByText('running', { exact: true })).toBeVisible()
})

test('warns when skipping the judge, since it leaves the metrics empty', async ({ page }) => {
  await page.goto('/')
  const skipJudge = page.getByRole('checkbox', { name: /Skip judge/ })
  await expect(skipJudge).toBeChecked()
  await expect(page.getByText(/the judge runs 80-190s per prompt/i)).toBeVisible()
})

test('shows an actionable empty state on results when nothing has been stored', async ({ page }) => {
  await stubTauri(page, { empty: true })
  await page.goto('/#/results')
  await expect(page.getByText('No run selected')).toBeVisible()
  // It must point at the way out, not just report emptiness.
  await expect(page.getByText(/Start one from the Run page/)).toBeVisible()
})

test('renders stored results for a completed run', async ({ page }) => {
  await page.goto('/#/results')

  // The run picker defaults to the most recent run.
  await expect(page.getByLabel('Run', { exact: true })).toHaveValue('e2e-run-0001')

  // Headline numbers, not just a chart.
  await expect(page.getByText('Faithfulness').first()).toBeVisible()

  // Both systems must be distinguishable. The colour dot alone is not enough -
  // each system's mean has to be spelled out, and the two must actually differ,
  // or the fixture is not exercising the comparison.
  await expect(page.getByText('System A').first()).toBeVisible()
  await expect(page.getByText('System B').first()).toBeVisible()
  await expect(page.getByText('0.900').first()).toBeVisible()
  await expect(page.getByText('0.950').first()).toBeVisible()

  // Every metric gets a Recharts surface; an empty one means the container has
  // no measurable height, which is invisible to unit tests.
  const svg = page.locator('.recharts-surface').first()
  await expect(svg).toBeVisible()
  const box = await svg.boundingBox()
  expect(box?.height ?? 0).toBeGreaterThan(20)
  expect(box?.width ?? 0).toBeGreaterThan(20)

  // Both SVG (charts) and canvas (3D) must have real geometry.
  const canvas = page.locator('canvas').first()
  await expect(canvas).toBeVisible()
  const canvasBox = await canvas.boundingBox()
  expect(canvasBox?.height ?? 0).toBeGreaterThan(20)

  // The retrieved chunks must be matched back to the projection despite the id
  // shortening, and the reported variance has to come from the metadata rather
  // than being invented.
  await expect(page.getByText(/2 of 400/)).toBeVisible()
  await expect(page.getByText(/explain 91\.0% of the variance/)).toBeVisible()
})

test('significance is reported honestly rather than overstated', async ({ page }) => {
  await page.goto('/#/results')
  // n=2 with a p-value of 0.32 must not be dressed up as a win.
  await expect(page.getByText(/not significant/i).first()).toBeVisible()
})

test('replays a stored run in the simulation', async ({ page }) => {
  await page.goto('/#/simulation')
  await expect(page.getByRole('heading', { level: 1, name: 'Simulation' })).toBeAttached()

  // The replay starts itself, so the control offers Pause first.
  await expect(page.getByRole('button', { name: 'Pause' })).toBeVisible()
  await page.getByRole('button', { name: 'Pause' }).click()
  await expect(page.getByRole('button', { name: 'Play' })).toBeVisible()

  // The 3D pipeline must render with real geometry.
  const canvas = page.locator('canvas').first()
  const box = await canvas.boundingBox()
  expect(box?.height ?? 0).toBeGreaterThan(20)
})

test('falls back to the system an A-only run actually has', async ({ page }) => {
  // An A-only run has no B rows. Holding B would render an empty pipeline whose
  // stage list still claims to include decision, reward and training - the three
  // stages the baseline never runs.
  await page.addInitScript(() => {
    const internals = (window as unknown as { __TAURI_INTERNALS__: unknown }).__TAURI_INTERNALS__ as {
      invoke: (command: string, args?: Record<string, unknown>) => Promise<unknown>
    }
    const inner = internals.invoke
    internals.invoke = (command: string, args?: Record<string, unknown>) => {
      if (command === 'get_run_detail') {
        return inner(command, args).then((detail) => {
          const d = detail as {
            run: { systems: string[] }
            promptRows: { system: string }[]
          }
          d.run.systems = ['A']
          d.promptRows = d.promptRows.filter((row) => row.system === 'A')
          return d
        })
      }
      return inner(command, args)
    }
  })

  await page.goto('/#/simulation')
  // Several elements name the system (the sr-only dot label, the visible label,
  // the row count, the panel subtitle); `.first()` pins it to the switcher.
  await expect(page.getByText('System A').first()).toBeVisible()
  // The single-system case shows a label, not an inert dropdown.
  await expect(page.getByLabel('System')).toHaveCount(0)

  // Five stages, not eight: the baseline never runs the policy stages.
  await expect(page.getByText(/System A - 5 stages/)).toBeVisible()

  const canvas = page.locator('canvas').first()
  const box = await canvas.boundingBox()
  expect(box?.height ?? 0).toBeGreaterThan(20)
})

test('explains that the app belongs in the Tauri window, not a browser', async ({ page }) => {
  // An empty command table stands in for "not running under Tauri"; the message
  // must name the fix rather than showing a bare stack trace.
  await page.addInitScript(() => {
    const internals = (window as unknown as { __TAURI_INTERNALS__: unknown }).__TAURI_INTERNALS__ as {
      invoke: (command: string) => Promise<unknown>
    }
    internals.invoke = () => Promise.reject(new Error('window.__TAURI_INTERNALS__ is undefined'))
  })
  await page.goto('/')
  await expect(page.getByRole('alert')).toContainText('npm run tauri dev')
})