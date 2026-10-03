/**
 * Live event console.
 *
 * An append-only list of what the sidecar has emitted. Auto-follows the tail
 * unless the user has scrolled up, because the common case is "watch it work" and
 * the important case is "read back what just happened".
 */

import { useCallback, useLayoutEffect, useRef, useState } from 'react'

import { useRunStore, type LogLine } from '@/store/runStore'
import { Button, Panel, PanelHeader } from '@/components/ui'
import { fmtTime } from '@/lib/format'
import { cn } from '@/lib/utils'

export function EventConsole() {
  const logs = useRunStore((s) => s.logs)
  const scrollRef = useRef<HTMLDivElement>(null)
  const pinnedRef = useRef(true)
  // Mirrored in state so the "Follow" button can appear. Reading the ref during
  // render would not re-render when scrolling changes it, leaving a button that
  // either never shows or shows wrongly.
  const [pinned, setPinned] = useState(true)

  // `useLayoutEffect` so the scroll lands in the same paint as the new line;
  // with `useEffect` a fast run visibly trails by a frame.
  useLayoutEffect(() => {
    const el = scrollRef.current
    if (el && pinnedRef.current) el.scrollTop = el.scrollHeight
  }, [logs])

  // Pausing the follow on manual scroll: if the user scrolls up mid-run they are
  // reading something, and yanking them back to the bottom is hostile.
  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    const next = distanceFromBottom < 24
    if (pinnedRef.current !== next) setPinned(next)
    pinnedRef.current = next
  }

  const resume = useCallback(() => {
    pinnedRef.current = true
    setPinned(true)
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [])

  return (
    <Panel className="flex min-h-0 flex-1 flex-col">
      <PanelHeader
        title="Event stream"
        subtitle={`${logs.length} events`}
        actions={
          pinned ? null : (
            <Button onClick={resume} size="sm">
              Follow
            </Button>
          )
        }
      />
      <div ref={scrollRef} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto font-mono text-xs">
        {logs.length === 0 ? (
          <p className="text-ink-faint p-4">Waiting for events…</p>
        ) : (
          <ol>
            {logs.map((line) => (
              <LogRow key={`${line.seq}-${line.level}`} line={line} />
            ))}
          </ol>
        )}
      </div>
    </Panel>
  )
}

function LogRow({ line }: { line: LogLine }) {
  return (
    <li className="hover:bg-surface-inset/60 flex gap-2 border-b border-border/40 px-3 py-1 last:border-b-0">
      <span className="text-ink-faint shrink-0 tabular-nums">{String(line.seq).padStart(3, '0')}</span>
      <span className="text-ink-faint shrink-0">{fmtTime(line.ts_ms)}</span>
      <span
        className={cn(
          'shrink-0 uppercase',
          line.level === 'error'
            ? 'text-danger'
            : line.level === 'warning'
              ? 'text-warning'
              : line.level === 'info'
                ? 'text-ink-muted'
                : 'text-accent/70',
        )}
      >
        {line.level === 'event' ? '·' : line.level.slice(0, 3)}
      </span>
      <span
        className={cn(
          'min-w-0 break-words',
          line.level === 'event' ? 'text-ink-muted' : 'text-ink',
        )}
      >
        {line.message}
      </span>
    </li>
  )
}