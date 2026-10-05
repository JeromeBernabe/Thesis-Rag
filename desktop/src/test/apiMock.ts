/**
 * A stand-in for `@/lib/api`.
 *
 * Tauri is not present under jsdom, so every test that touches the store or a
 * component needs these functions to be controllable. Assigning to an ES module's
 * exports does not work at runtime - the namespace is read-only - which is why
 * the tests mock the module rather than patching it.
 *
 * Each function starts as a rejected promise, not a no-op. An unconfigured mock
 * that silently resolves would let a test pass against data it never provided.
 */

import { vi } from 'vitest'

import type { AppInfo, RunRecord } from '@/types/models'

export const apiMock = {
  getAppInfo: vi.fn<() => Promise<AppInfo>>(),
  startRun: vi.fn(),
  cancelRun: vi.fn<() => Promise<string>>(),
  runInProgress: vi.fn<() => Promise<boolean>>(),
  listRuns: vi.fn<() => Promise<RunRecord[]>>(),
  getRunDetail: vi.fn(),
  getRunEvents: vi.fn(),
  getStats: vi.fn(),
  deleteRun: vi.fn<() => Promise<void>>(),
  getProjection: vi.fn(),
  getProjectionData: vi.fn(),
  listProjections: vi.fn<() => Promise<string[]>>(),
  importLegacy: vi.fn(),
  onEvent: vi.fn<() => Promise<() => void>>(),
}

/** A minimal `AppInfo`, matching what `app_info` returns. */
export const APP_INFO: AppInfo = {
  datasets: ['hotpot', 'fintech', 'math', 'ragtruth'],
  defaultDataset: 'hotpot',
  defaultLimit: 50,
  defaultSeed: 42,
  python: 'python',
  projectRoot: 'C:/repo',
  dbPath: 'C:/repo/data/bench/runs.sqlite3',
  schemaVersion: 1,
}

/** Reset every mock to a rejected promise and forget recorded calls. */
export function resetApiMock(): void {
  for (const fn of Object.values(apiMock)) {
    fn.mockReset()
    // Actually reject, as the file's contract promises. `mockReset()` on its own
    // leaves the mock returning `undefined`, so a component that a test forgot
    // to configure crashed on `undefined.then` instead of showing the error it
    // had a handler for - which reads as a bug in the component under test and
    // sends you looking in the wrong file.
    fn.mockRejectedValue(new Error('apiMock: not configured for this test'))
  }
  apiMock.getAppInfo.mockResolvedValue(APP_INFO)
  apiMock.listRuns.mockResolvedValue([])
  apiMock.listProjections.mockResolvedValue([])
  apiMock.runInProgress.mockResolvedValue(false)
  apiMock.onEvent.mockResolvedValue(() => {})
  apiMock.getProjection.mockResolvedValue(null)
  apiMock.getProjectionData.mockResolvedValue(null)
}