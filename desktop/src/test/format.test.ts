import { describe, expect, it } from 'vitest'

import { DASH, fmtDelta, fmtDuration, fmtInt, fmtNum, fmtPValue, fmtStat, kValues, shortRunId } from '@/lib/format'

describe('fmtNum', () => {
  it('renders a real zero rather than the dash', () => {
    // The whole point of the dash convention: 0 is a score, absence is not.
    expect(fmtNum(0)).toBe('0.000')
    expect(fmtNum(0, 2)).toBe('0.00')
  })

  it('renders null, undefined and NaN as a dash', () => {
    expect(fmtNum(null)).toBe(DASH)
    expect(fmtNum(undefined)).toBe(DASH)
    expect(fmtNum(Number.NaN)).toBe(DASH)
  })

  it('honours the requested precision', () => {
    expect(fmtNum(0.9157, 2)).toBe('0.92')
    expect(fmtNum(1, 3)).toBe('1.000')
  })
})

describe('fmtInt', () => {
  it('keeps zero and dashes absence', () => {
    expect(fmtInt(0)).toBe('0')
    expect(fmtInt(null)).toBe(DASH)
    expect(fmtInt(42.4)).toBe('42')
  })
})

describe('fmtDuration', () => {
  it('scales the unit to the magnitude', () => {
    expect(fmtDuration(0.031)).toBe('31 ms')
    expect(fmtDuration(2.5)).toBe('2.5 s')
    expect(fmtDuration(90)).toBe('1m 30s')
    expect(fmtDuration(3725)).toBe('1h 2m')
  })

  it('dashes absence instead of showing 0 s', () => {
    expect(fmtDuration(null)).toBe(DASH)
    expect(fmtDuration(undefined)).toBe(DASH)
  })
})

describe('fmtDelta', () => {
  it('signs improvements and regressions', () => {
    expect(fmtDelta(0.05)).toBe('+5.0%')
    expect(fmtDelta(-0.023)).toBe('-2.3%')
  })

  it('leaves an exactly zero delta unsigned', () => {
    // "+0.0%" reads as a rounding artefact; "0.0%" reads as no difference.
    expect(fmtDelta(0)).toBe('0.0%')
  })

  it('dashes absence, so an unjudged run shows no delta', () => {
    expect(fmtDelta(null)).toBe(DASH)
  })
})

describe('fmtPValue', () => {
  it('collapses very small values', () => {
    expect(fmtPValue(0.00004)).toBe('< 0.001')
  })

  it('shows three decimals otherwise and dashes absence', () => {
    expect(fmtPValue(0.042)).toBe('0.042')
    expect(fmtPValue(null)).toBe(DASH)
  })
})

describe('fmtStat', () => {
  it('dashes a null statistic rather than showing NaN', () => {
    // A constant difference makes the t-statistic undefined; "NaN" would look
    // like a bug in the app rather than a property of the data.
    expect(fmtStat(Number.NaN)).toBe(DASH)
    expect(fmtStat(null)).toBe(DASH)
    expect(fmtStat(2.345)).toBe('2.35')
  })
})

describe('kValues', () => {
  it('reads only the ks the run actually used', () => {
    // A run that only ever chose k=3 should not imply four phantom bars.
    expect(kValues({ '3': 12 })).toEqual([3])
    expect(kValues({ '5': 1, '1': 2, '3': 4 })).toEqual([1, 3, 5])
  })

  it('tolerates a missing distribution', () => {
    expect(kValues(null)).toEqual([])
    expect(kValues(undefined)).toEqual([])
    expect(kValues({})).toEqual([])
  })
})

describe('shortRunId', () => {
  it('leaves a short id alone and truncates a long one', () => {
    expect(shortRunId('abc')).toBe('abc')
    expect(shortRunId('0123456789abcdef')).toBe('01234567…')
  })
})