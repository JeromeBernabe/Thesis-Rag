/**
 * Vitest setup.
 *
 * The Tauri API is unavailable under jsdom, so `@/lib/api` is replaced wholesale
 * with a mock the tests control. Mocking per-module would leave every component
 * holding a real `invoke` that rejects at call time.
 */

import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

// jsdom has no WebGL, so the 3D canvases cannot mount. The projection maths that
// is worth testing is pure and lives outside the component; the components
// themselves are covered by their exported helpers.
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

vi.stubGlobal('ResizeObserver', ResizeObserverStub)

// Recharts' ResponsiveContainer needs a non-zero box; jsdom reports 0 for
// everything, which makes charts render nothing and trips its own warnings.
vi.stubGlobal(
  'ResizeObserver',
  class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  },
)

if (!window.matchMedia) {
  vi.stubGlobal(
    'matchMedia',
    (query: string) =>
      ({
        matches: false,
        media: query,
        onchange: null,
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList,
  )
}