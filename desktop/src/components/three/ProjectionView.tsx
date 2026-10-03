/**
 * 3D view 1: the embedding space, PCA-projected to three dimensions.
 *
 * The sidecar writes a binary point cloud plus a small JSON sidecar
 * (`bench_bridge/projection.py`), so this view is a straight read of two files -
 * no PCA in the browser, which would mean shipping the whole corpus to the webview.
 *
 * Three constraints shape the implementation:
 *
 * - **A 30k-point cloud must not become 30k React elements.** Points go into one
 *   `THREE.Points` primitive; only the run's retrieved chunks get a second one.
 * - **The camera has to fit the data.** PCA output has no fixed scale, so the
 *   bounds are measured from the buffer and the camera framed from them.
 * - **Ids only match after the same shortening.** The projection stores full
 *   document ids while rows store the sidecar's short form, so matching needs
 *   `matchesDocId` rather than string equality.
 */

import { useEffect, useMemo, useState } from 'react'
import { Canvas, useThree } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'

import * as api from '@/lib/api'
import { COLORS, systemColor } from '@/components/three/colors'
import { fmtInt } from '@/lib/format'
import { EmptyState, Panel, PanelHeader, Select } from '@/components/ui'
import type { PromptRow, ProjectionPoints } from '@/types/models'
import { varianceExplained } from '@/types/models'

/**
 * Whether a projected document is one of a run's retrieved chunks.
 *
 * Compare on the prefix both sides share, because the projection holds the full
 * id (`doc-<hash>-<n>`) and the event stream carries only `doc-<hash>`.
 */
export function matchesDocId(projectedId: string, retrievedId: string): boolean {
  return projectedId === retrievedId || projectedId.startsWith(retrievedId) || retrievedId.startsWith(projectedId)
}

/** Axis-aligned bounds of a flat xyz buffer. */
function boundsOf(xyz: Float32Array): { centre: [number, number, number]; radius: number } {
  let minX = Infinity
  let minY = Infinity
  let minZ = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  let maxZ = -Infinity
  for (let i = 0; i + 2 < xyz.length; i += 3) {
    if (xyz[i] < minX) minX = xyz[i]
    if (xyz[i] > maxX) maxX = xyz[i]
    if (xyz[i + 1] < minY) minY = xyz[i + 1]
    if (xyz[i + 1] > maxY) maxY = xyz[i + 1]
    if (xyz[i + 2] < minZ) minZ = xyz[i + 2]
    if (xyz[i + 2] > maxZ) maxZ = xyz[i + 2]
  }
  if (!Number.isFinite(minX)) return { centre: [0, 0, 0], radius: 1 }
  const radius = Math.max(maxX - minX, maxY - minY, maxZ - minZ, 1e-6)
  return { centre: [(minX + maxX) / 2, (minY + maxY) / 2, (minZ + maxZ) / 2], radius }
}

/**
 * Frame the camera on the cloud.
 *
 * Must live inside `<Canvas>` because it reads the camera from the R3F store.
 * The camera is not a render output, so it is mutated inside the effect rather
 * than during render - React owns the declarative tree, not three.js.
 */
function FitCamera({ xyz }: { xyz: Float32Array }) {
  const camera = useThree((state) => state.camera)
  useEffect(() => {
    const { centre, radius } = boundsOf(xyz)
    // Pull back far enough that the whole bounding sphere fits the smaller of the
    // two viewport axes, with margin so points are not flush against the edge.
    const distance = radius * 2.6
    /* oxlint-disable react/immutability --
       `camera` comes from the R3F store, but it is three.js state, not React
       state. Framing the scene is imperative by design and there is no
       declarative way to express it. */
    camera.position.set(centre[0], centre[1], centre[2] + distance)
    camera.near = Math.max(distance / 1000, 0.01)
    camera.far = distance * 10
    camera.updateProjectionMatrix()
    camera.lookAt(centre[0], centre[1], centre[2])
    /* oxlint-enable react/immutability */
  }, [camera, xyz])
  return null
}

type LoadState =
  | { kind: 'loading' }
  | { kind: 'missing' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; points: ProjectionPoints }

export function ProjectionView({ dataset, rows }: { dataset: string; rows: PromptRow[] }) {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [system, setSystem] = useState<'A' | 'B'>('A')

  useEffect(() => {
    if (!dataset) return
    let cancelled = false
    setState({ kind: 'loading' })
    void api
      .getProjectionData(dataset)
      .then((points) => {
        if (cancelled) return
        setState(points ? { kind: 'ready', points } : { kind: 'missing' })
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({ kind: 'error', message: error instanceof Error ? error.message : String(error) })
        }
      })
    return () => {
      cancelled = true
    }
  }, [dataset])

  const systems = useMemo(() => [...new Set(rows.map((row) => row.system))].sort(), [rows])

  // The chunks this run actually retrieved, as indices into the point cloud.
  const highlighted = useMemo(() => {
    if (state.kind !== 'ready') return []
    const wanted = new Set<string>()
    for (const row of rows) {
      if (row.system !== system) continue
      for (const id of row.retrieved_ids ?? []) if (id) wanted.add(id)
    }
    if (wanted.size === 0) return []
    const indices: number[] = []
    state.points.meta.ids.forEach((id, i) => {
      for (const candidate of wanted) {
        if (matchesDocId(id, candidate)) {
          indices.push(i)
          return
        }
      }
    })
    return indices
  }, [state, rows, system])

  const highlightBuffer = useMemo(() => {
    if (state.kind !== 'ready' || highlighted.length === 0) return null
    const xyz = state.points.xyz
    const picked = new Float32Array(highlighted.length * 3)
    let n = 0
    for (const index of highlighted) {
      if (index * 3 + 2 >= xyz.length) continue
      picked[n * 3] = xyz[index * 3]
      picked[n * 3 + 1] = xyz[index * 3 + 1]
      picked[n * 3 + 2] = xyz[index * 3 + 2]
      n += 1
    }
    return n === highlighted.length ? picked : picked.subarray(0, n * 3)
  }, [state, highlighted])

  return (
    <Panel>
      <PanelHeader
        title="Embedding space"
        subtitle={
          state.kind === 'ready'
            ? `${fmtInt(state.points.meta.n_points)} documents, ${state.points.meta.dim}d, PCA to 3d`
            : 'PCA projection of the corpus'
        }
        actions={
          systems.length > 1 ? (
            <Select
              aria-label="Highlight retrieved chunks for system"
              value={system}
              onChange={(event) => setSystem(event.target.value as 'A' | 'B')}
              className="h-7 w-32 py-0 text-xs"
            >
              {systems.map((id) => (
                <option key={id} value={id}>
                  System {id}
                </option>
              ))}
            </Select>
          ) : null
        }
      />
      <div className="p-3">
        {state.kind === 'loading' ? (
          <div className="text-ink-faint flex h-80 items-center justify-center text-sm">Loading projection…</div>
        ) : state.kind === 'missing' ? (
          <div className="flex h-80 items-center justify-center">
            <EmptyState
              title={`No projection for ${dataset}`}
              detail="Run a benchmark with the projection phase enabled. The sidecar writes the point cloud to data/bench and the Results page picks it up from here."
            />
          </div>
        ) : state.kind === 'error' ? (
          <div className="text-danger flex h-80 items-center justify-center p-4 text-sm">{state.message}</div>
        ) : (
          <>
            {/* The height has to live on a wrapper: `<Canvas>` sizes itself from
                its parent, and a parent with no height collapses to zero. */}
            <div className="h-80 overflow-hidden rounded-panel border border-border">
              <Canvas camera={{ fov: 50 }} dpr={[1, 2]}>
                <color attach="background" args={[COLORS.inset]} />
                <FitCamera xyz={state.points.xyz} />
                <PointCloud xyz={state.points.xyz} size={1.2} opacity={0.5} color={COLORS.faint} />
                {highlightBuffer ? (
                  <PointCloud
                    xyz={highlightBuffer}
                    size={7}
                    opacity={0.95}
                    color={systemColor(system)}
                  />
                ) : null}
                <OrbitControls enableDamping makeDefault />
              </Canvas>
            </div>
            <p className="text-ink-faint mt-2 text-xs">
              Grey is the corpus; highlighted points are the chunks system {system} retrieved (
              {fmtInt(highlighted.length)} of {fmtInt(state.points.meta.n_points)}). Drag to orbit, scroll to zoom.
              {varianceExplained(state.points.meta) !== null
                ? ` The three axes shown explain ${((varianceExplained(state.points.meta) ?? 0) * 100).toFixed(1)}% of the variance.`
                : ''}
            </p>
          </>
        )}
      </div>
    </Panel>
  )
}

/** One `THREE.Points` primitive over a flat xyz buffer. */
function PointCloud({
  xyz,
  size,
  opacity,
  color,
}: {
  xyz: Float32Array
  size: number
  opacity: number
  color: string
}) {
  return (
    <points>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[xyz, 3]} />
      </bufferGeometry>
      <pointsMaterial size={size} color={color} sizeAttenuation transparent opacity={opacity} />
    </points>
  )
}
