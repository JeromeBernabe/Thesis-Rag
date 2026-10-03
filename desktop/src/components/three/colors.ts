/**
 * Colours for the 3D views, as literal hex.
 *
 * These deliberately duplicate the theme in `index.css` instead of reading
 * `var(--color-...)`. three.js parses colour strings with `THREE.Color.setStyle`,
 * which understands hex, `rgb()` and `hsl()` but resolves neither CSS custom
 * properties nor the `oklch()` values this theme uses. Passing `var(--color-x)`
 * therefore renders as an unset colour, which three reports as black.
 *
 * Duplicating values invites drift, so they are kept in one place here rather
 * than inline in each view, and the CSS custom properties are the source of
 * truth for the DOM. `SYSTEM_COLORS` and `CHART` expose the same two system
 * colours as the Recharts series so a point in the cloud and a bar for the same
 * system read as the same system.
 */

/** Must match `--color-surface-inset`. */
export const COLORS = {
  inset: '#13161c',
  faint: '#83899b',
  border: '#474d5e',
  accent: '#9d8cff',
  warning: '#f5b942',
} as const

/** Must match `--color-system-a` / `--color-system-b`. */
export const SYSTEM_COLORS: Record<'A' | 'B', string> = {
  A: '#3f9be0',
  B: '#2cc76f',
}

export function systemColor(system: 'A' | 'B'): string {
  return SYSTEM_COLORS[system]
}