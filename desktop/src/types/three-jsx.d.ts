/**
 * TypeScript shim for React Three Fiber.
 *
 * R3F v9 publishes its element types through `declare module` augmentations in
 * `three-types.d.ts`, but that file is side-effect-only and is not pulled in
 * unless something imports it. Without it the 3D intrinsics - `<points>`,
 * `<pointMaterial>`, `<bufferAttribute>` - do not resolve, and `tsc -b` fails on
 * every 3D component.
 *
 * All three JSX entry points are declared because the automatic runtime resolves
 * intrinsics through `react/jsx-runtime`, while type positions still reference
 * the `react` namespace. Declaring one and not the others leaves it failing in a
 * different file each time.
 */

import type { ThreeElements } from '@react-three/fiber'

declare module 'react' {
  namespace JSX {
    interface IntrinsicElements extends ThreeElements {}
  }
}

declare module 'react/jsx-runtime' {
  namespace JSX {
    interface IntrinsicElements extends ThreeElements {}
  }
}

declare module 'react/jsx-dev-runtime' {
  namespace JSX {
    interface IntrinsicElements extends ThreeElements {}
  }
}

export {}