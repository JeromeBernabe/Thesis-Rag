/**
 * 3D view 2: the retrieval pipeline as a graph.
 *
 * The eight stages come from the legacy `simulation/index.html`, in the order the
 * sidecar actually emits them: question, embedding, DQN decision, retrieval,
 * generation, judging, reward, training.
 *
 * The layout is deterministic rather than force-directed. A force layout would
 * look impressive and be useless: the order of the stages *is* the information,
 * so the graph is laid out along a fixed path and the stages are numbered.
 *
 * A token travels the path while a run plays, which is what makes the ordering
 * legible. Durations come from the selected run when it has them, so a real run
 * shows real timing rather than an arbitrary animation.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { Html, OrbitControls } from '@react-three/drei'

import { cn } from '@/lib/utils'
import { fmtDuration } from '@/lib/format'
import { COLORS, systemColor } from '@/components/three/colors'

/** One stage of the pipeline. */
export interface Stage {
  key: string
  label: string
  /** What the stage consumes and produces, shown in the detail panel. */
  detail: string
  /** Nominal position along the path, before any layout is applied. */
  position: [number, number, number]
  /**
   * Only part of the learned policy, so system A skips it.
   *
   * Marked rather than hidden: seeing that the DQN stages did not run is itself
   * the difference between the two systems.
   */
  bOnly?: boolean
}

/**
 * The pipeline, in execution order.
 *
 * `run_system_a` skips the DQN stages, so those are marked `bOnly` and dim rather
 * than hidden - seeing that a stage was skipped is itself informative.
 */
export const STAGES: Stage[] = [
  {
    key: 'question',
    label: 'Question',
    detail: 'A prompt and its ground truth arrive from the dataset.',
    position: [-60, 0, 0],
  },
  {
    key: 'embedding',
    label: 'Embedding',
    detail: 'The question is embedded into the 768-dim corpus space.',
    position: [-36, 0, 0],
  },
  {
    key: 'decision',
    label: 'DQN decision',
    detail: 'The agent scores each k and, above epsilon, may explore.',
    position: [-12, 0, 0],
    bOnly: true,
  },
  {
    key: 'retrieval',
    label: 'Retrieval',
    detail: 'Top-k chunks are fetched from ChromaDB by cosine distance.',
    position: [12, 0, 0],
  },
  {
    key: 'generation',
    label: 'Generation',
    detail: 'The answer is generated from the retrieved context.',
    position: [36, 0, 0],
  },
  {
    key: 'judge',
    label: 'RAGAS',
    detail: 'The judge scores faithfulness, relevancy and recall.',
    position: [60, 0, 0],
  },
  {
    key: 'reward',
    label: 'Reward',
    detail: 'The judge scores become the reward signal for the policy.',
    position: [60, 0, 24],
    bOnly: true,
  },
  {
    key: 'training',
    label: 'Training step',
    detail: 'The replay buffer update nudges the Q-values.',
    position: [36, 0, 24],
    bOnly: true,
  },
]

/** Stage keys, for lookup by index. */
export const STAGE_KEYS = STAGES.map((stage) => stage.key)

/**
 * Per-stage timing from a real run, so the animation reflects actual durations.
 *
 * A stage the run never performed is omitted rather than zeroed, so the caller can
 * tell "fast" from "did not happen".
 */
export type StageTimings = Partial<Record<string, number>>

/** Sum of the given stage timings, used as the animation's total duration. */
function totalTime(timings: StageTimings, system: 'A' | 'B'): number {
  return STAGES.filter((stage) => stage.bOnly !== (system === 'A')).reduce((sum, stage) => {
    const seconds = timings[stage.key]
    return sum + (seconds && seconds > 0 ? seconds : 0)
  }, 0)
}

export interface PipelineViewProps {
  /** Which system's run is being visualised; decides which stages are live. */
  system: 'A' | 'B'
  /** Measured durations, in seconds. */
  timings?: StageTimings
  /** Called with the stage index under the travelling token. */
  onStageChange?: (index: number) => void
  /** When false the token parks and the graph is static. */
  playing?: boolean
  className?: string
}

export function PipelineView({ system, timings = {}, onStageChange, playing = true, className }: PipelineViewProps) {
  const [elapsed, setElapsed] = useState(0)

  const active = useMemo(
    () => STAGES.filter((stage) => (system === 'B' ? true : !stage.bOnly)),
    [system],
  )

  const total = useMemo(() => {
    const measured = totalTime(timings, system)
    // No measurements: fall back to a nominal 12s so the animation still runs.
    return measured > 0 ? measured : 12
  }, [timings, system])

  useEffect(() => {
    if (!playing) return
    setElapsed(0)
    const started = performance.now()
    const timer = window.setInterval(() => {
      const seconds = (performance.now() - started) / 1000
      // Loop, because the interesting part of a pipeline is the cycle.
      setElapsed(seconds % total)
    }, 50)
    return () => window.clearInterval(timer)
  }, [playing, total])

  const fraction = Math.min(1, Math.max(0, elapsed / total))
  const activeIndex = Math.min(active.length - 1, Math.floor(fraction * active.length))

  useEffect(() => {
    onStageChange?.(activeIndex)
  }, [activeIndex, onStageChange])

  const cursor = useMemo(() => {
    const stage = active[activeIndex] ?? active[0]
    if (!stage) return null
    const next = active[activeIndex + 1]
    if (!next) return stage.position
    // Interpolate toward the next stage so the token moves rather than jumps.
    const local = fraction * active.length - activeIndex
    return stage.position.map((value, i) => value + (next.position[i] - value) * local) as [
      number,
      number,
      number,
    ]
  }, [active, activeIndex, fraction])

  if (!active.length || !cursor) return null

  return (
    <div className={cn('relative h-96 min-h-0 w-full', className)}>
      <Canvas camera={{ position: [0, 10, 110], fov: 45 }} dpr={[1, 2]}>
        <color attach="background" args={[COLORS.inset]} />
        <ambientLight intensity={1} />
        <Edges stages={active} activeIndex={activeIndex} system={system} />
        {playing ? <Token position={cursor} /> : <Token position={cursor} dimmed />}
        <OrbitControls enableDamping makeDefault />
      </Canvas>
      <ol className="text-ink-faint absolute bottom-2 left-2 flex flex-col gap-0.5 text-[0.7rem]">
        {active.map((stage, index) => (
          <li
            key={stage.key}
            aria-current={index === activeIndex ? 'step' : undefined}
            className={cn(
              'flex items-center gap-1.5 transition-colors',
              index === activeIndex ? 'text-accent' : 'text-ink-faint',
            )}
          >
            <span className="tnum w-3">{index + 1}</span>
            {stage.label}
            {timings[stage.key] ? (
              <span className="text-ink-faint tnum">({fmtDuration(timings[stage.key])})</span>
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  )
}

/** Nodes and the edges between them. */
function Edges({
  stages,
  activeIndex,
  system,
}: {
  stages: Stage[]
  activeIndex: number
  system: 'A' | 'B'
}) {
  return (
    <group>
      {stages.map((stage, index) => (
        <Node
          key={stage.key}
          stage={stage}
          active={index === activeIndex}
          dimmed={Boolean(stage.bOnly) && system === 'A'}
          accent={systemColor(system)}
        />
      ))}
      {stages.slice(0, -1).map((stage, index) => {
        const next = stages[index + 1]
        return (
          <line key={`${stage.key}-${next.key}`}>
            <bufferGeometry>
              <bufferAttribute
                attach="attributes-position"
                args={[
                  new Float32Array([...stage.position, ...next.position]),
                  3,
                ]}
              />
            </bufferGeometry>
            <lineBasicMaterial
              color={index === activeIndex ? COLORS.accent : COLORS.border}
              transparent
              opacity={index === activeIndex ? 0.9 : 0.5}
            />
          </line>
        )
      })}
    </group>
  )
}

function Node({
  stage,
  active,
  dimmed,
  accent,
}: {
  stage: Stage
  active: boolean
  dimmed: boolean
  accent: string
}) {
  const ref = useRef<import('three').Mesh>(null)
  useFrame((state) => {
    if (!ref.current) return
    const target = active ? 1.5 : 1
    const pulse = active ? 1 + Math.sin(state.clock.elapsedTime * 3) * 0.12 : 1
    // Smooth the scale change rather than snapping, so the pulse reads as motion.
    const next = ref.current.scale.x + (target * pulse - ref.current.scale.x) * 0.15
    ref.current.scale.setScalar(next)
  })

  return (
    <group position={stage.position}>
      <mesh ref={ref}>
        <sphereGeometry args={[4, 24, 24]} />
        <meshStandardMaterial
          color={dimmed ? COLORS.border : active ? COLORS.accent : accent}
          transparent
          opacity={dimmed ? 0.35 : 1}
          emissive={active ? COLORS.accent : '#000000'}
          emissiveIntensity={active ? 0.6 : 0}
        />
      </mesh>
      <Html center distanceFactor={90} style={{ pointerEvents: 'none' }}>
        <span
          className={cn(
            'whitespace-nowrap font-mono text-[0.65rem]',
            dimmed ? 'text-ink-faint' : active ? 'text-accent' : 'text-ink-muted',
          )}
        >
          {stage.label}
        </span>
      </Html>
    </group>
  )
}

/** The travelling token. */
function Token({ position, dimmed = false }: { position: [number, number, number]; dimmed?: boolean }) {
  const ref = useRef<import('three').Mesh>(null)
  useFrame((_, delta) => {
    if (!ref.current) return
    ref.current.rotation.x += delta * 2
    ref.current.rotation.y += delta * 3
  })
  return (
    <mesh ref={ref} position={position}>
      <octahedronGeometry args={[2.2, 0]} />
      <meshStandardMaterial
        color={COLORS.warning}
        emissive={COLORS.warning}
        emissiveIntensity={dimmed ? 0.1 : 0.8}
        transparent
        opacity={dimmed ? 0.4 : 1}
      />
    </mesh>
  )
}
