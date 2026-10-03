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
  getRun: vi.fn(),
  getRunDetail: vi.fn(),
  getRunEvents: vi.fn(),
  getStats: vi.fn(),
  deleteRun: vi.fn<() => Promise<void>>(),
  getProjection: vi.fn(),
  listProjections: vi.fn<() => Promise<string[]>>(),
  importLegacy: vi.fn(),
  onEvent: vi.fn<() => Promise<() => void>>(),
  readProjectionMeta: vi.fn(),
  readProjectionPoints: vi.fn(),
  setBinaryLoader: vi.fn(),
  resetBinaryLoader: vi.fn(),
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
  }
  apiMock.getAppInfo.mockResolvedValue(APP_INFO)
  apiMock.listRuns.mockResolvedValue([])
  apiMock.listProjections.mockResolvedValue([])
  apiMock.runInProgress.mockResolvedValue(false)
  apiMock.onEvent.mockResolvedValue(() => {})
  apiMock.getProjection.mockResolvedValue(null)
}