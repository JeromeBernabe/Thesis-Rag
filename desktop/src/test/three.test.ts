import { describe, expect, it } from 'vitest'

import { matchesDocId } from '@/components/three/ProjectionView'
import { STAGES, STAGE_KEYS } from '@/components/three/PipelineView'

describe('matchesDocId', () => {
  it('matches a short id against the full projected id', () => {
    // The sidecar emits `doc-<hash>`; the projection stores `doc-<hash>-<n>`.
    expect(matchesDocId('doc-5a78b7b4554299029c4b5e4f-0', 'doc-5a78b7b4554299029c4b5e4f')).toBe(true)
  })

  it('matches an exact id', () => {
    expect(matchesDocId('doc-abc', 'doc-abc')).toBe(true)
  })

  it('matches when the short id carries a suffix', () => {
    expect(matchesDocId('doc-abc', 'doc-abc-3')).toBe(true)
  })

  it('does not match unrelated documents', () => {
    expect(matchesDocId('doc-aaa', 'doc-bbb')).toBe(false)
    expect(matchesDocId('doc-aaa-1', 'doc-aab')).toBe(false)
  })
})

describe('pipeline stages', () => {
  it('has the eight stages of the pipeline, in execution order', () => {
    expect(STAGE_KEYS).toEqual([
      'question',
      'embedding',
      'decision',
      'retrieval',
      'generation',
      'judge',
      'reward',
      'training',
    ])
  })

  it('marks only the learned-policy stages as system B', () => {
    // System A has no policy, so these must be absent rather than faked; the view
    // dims them, which is itself the difference between the two systems.
    const bOnly = STAGES.filter((stage) => stage.bOnly).map((stage) => stage.key)
    expect(bOnly).toEqual(['decision', 'reward', 'training'])
  })

  it('gives every stage a label, a detail and a position', () => {
    for (const stage of STAGES) {
      expect(stage.label).not.toBe('')
      expect(stage.detail).not.toBe('')
      expect(stage.position).toHaveLength(3)
    }
  })

  it('keeps the graph in a sane coordinate range', () => {
    for (const stage of STAGES) {
      for (const axis of stage.position) {
        expect(Number.isFinite(axis)).toBe(true)
        expect(Math.abs(axis)).toBeLessThan(500)
      }
    }
  })
})