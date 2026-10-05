/**
 * The `apiMock` stand-in must shadow every export of `@/lib/api`.
 *
 * Vitest's module mock is a proxy: reading an export the factory did not return
 * throws *synchronously*, at the property access. That matters because
 * components call these functions inside promise chains
 * (`void api.getX().then().catch()`), so a synchronous throw at the access site
 * escapes the `.catch` the component wrote for real failures. The result is an
 * unhandled rejection attributed to whatever test happened to be running last,
 * or - worse - no visible failure at all while a component renders nothing.
 *
 * That is not hypothetical: `getProjectionData` was missing for the entire life
 * of this mock, and `getRunDetail` fixtures were shaped `{prompts, training}`
 * instead of `{promptRows, trainingRows}`. Neither showed up as a failing test.
 * This file exists so the next missing export is a test failure instead.
 */

import { describe, expect, it } from 'vitest'

import * as realApi from '@/lib/api'

import { apiMock } from './apiMock'

describe('apiMock', () => {
  it('shadows every export of @/lib/api', () => {
    const exported = Object.keys(realApi).filter(
      (name) => name !== 'default' && typeof (realApi as Record<string, unknown>)[name] === 'function',
    )
    const missing = exported.filter((name) => !(name in apiMock))

    expect(missing, `apiMock is missing: ${missing.join(', ')}`).toEqual([])
  })

  it('declares nothing that @/lib/api does not export', () => {
    // A stale entry is not harmless: it silently keeps a removed API alive in
    // tests that could then pass against a function production no longer has.
    const extra = Object.keys(apiMock).filter((name) => !(name in realApi))

    expect(extra, `apiMock declares functions absent from @/lib/api: ${extra.join(', ')}`).toEqual([])
  })
})