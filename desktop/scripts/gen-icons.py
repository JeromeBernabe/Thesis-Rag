#!/usr/bin/env python3
"""Generate the Tauri icon set without any image dependencies.

Tauri's Windows build embeds ``icons/icon.ico`` as a Win32 resource, and the
bundler also wants the PNG sizes listed in ``tauri.conf.json``. Rather than
commit opaque binaries with no provenance, this script renders them from a
simple vector description so they can be regenerated or restyled.

Only the standard library is used (``zlib`` + ``struct``), so the icons can be
regenerated on any machine that can run the app's Python.

Usage::

    python desktop/scripts/gen-icons.py
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

# Same palette as the app shell so the taskbar icon does not clash.
BG = (15, 23, 42)  # slate-900
FG = (56, 189, 248)  # sky-400
ACCENT = (168, 85, 247)  # purple-500
ACCENT2 = (34, 197, 94)  # green-500

SIZES = {
    "32x32.png": 32,
    "128x128.png": 128,
    "128x128@2x.png": 256,
    "icon.png": 512,
}


def _blend(dst, src, alpha):
    """Source-over composite of ``src`` over ``dst`` at ``alpha`` (0..1)."""
    return tuple(int(round(d + (s - d) * alpha)) for d, s in zip(dst, src))


def _coverage(px, py, shape, samples=4):
    """Supersampled coverage of a shape at a point, for cheap anti-aliasing."""
    hits = 0
    step = 1.0 / samples
    for i in range(samples):
        for j in range(samples):
            x = px + (i + 0.5) * step
            y = py + (j + 0.5) * step
            if shape(x, y):
                hits += 1
    return hits / (samples * samples)


def _circle(cx, cy, r):
    r2 = r * r

    def inside(x, y):
        dx, dy = x - cx, y - cy
        return dx * dx + dy * dy <= r2

    return inside


def _segment(x0, y0, x1, y1, width):
    """Thick line segment as a capsule (point-to-segment distance test)."""
    hw2 = (width / 2.0) ** 2
    vx, vy = x1 - x0, y1 - y0
    len2 = vx * vx + vy * vy

    def inside(x, y):
        if len2 == 0:
            dx, dy = x - x0, y - y0
            return dx * dx + dy * dy <= hw2
        t = ((x - x0) * vx + (y - y0) * vy) / len2
        t = max(0.0, min(1.0, t))
        dx = x - (x0 + t * vx)
        dy = y - (y0 + t * vy)
        return dx * dx + dy * dy <= hw2

    return inside


def _rounded_rect(size, radius):
    def inside(x, y):
        if x < 0 or y < 0 or x > size or y > size:
            return False
        cx = min(max(x, radius), size - radius)
        cy = min(max(y, radius), size - radius)
        dx, dy = x - cx, y - cy
        return dx * dx + dy * dy <= radius * radius

    return inside


def render(size: int) -> bytearray:
    """Render one RGBA icon at ``size`` px square."""
    radius = size * 0.22
    plate = _rounded_rect(size, radius)
    stroke = size * 0.055

    # A triangle of three embedding clusters, echoing the 3D scatter view.
    pts = [
        (size * 0.28, size * 0.68, FG),
        (size * 0.72, size * 0.64, ACCENT),
        (size * 0.50, size * 0.28, ACCENT2),
    ]
    dot_r = size * 0.115

    edges = [
        _segment(*pts[0][:2], *pts[1][:2], stroke),
        _segment(*pts[1][:2], *pts[2][:2], stroke),
        _segment(*pts[2][:2], *pts[0][:2], stroke),
    ]
    dots = [_circle(cx, cy, dot_r) for cx, cy, _ in pts]

    buf = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            r, g, b, a = 0, 0, 0, 0
            cov = _coverage(x, y, plate)
            if cov > 0:
                r, g, b = BG
                a = int(round(255 * cov))
                for shape in edges:
                    c = _coverage(x, y, shape, samples=3)
                    if c > 0:
                        r, g, b = _blend((r, g, b), FG, c * 0.9)
                for dot, (_, _, colour) in zip(dots, pts):
                    c = _coverage(x, y, dot, samples=4)
                    if c > 0:
                        r, g, b = _blend((r, g, b), colour, c)
            i = (y * size + x) * 4
            buf[i : i + 4] = bytes((r, g, b, a))
    return buf


def write_png(path: Path, size: int, rgba: bytearray) -> None:
    raw = bytearray()
    stride = size * 4
    for y in range(size):
        raw.append(0)  # filter type 0 (None)
        raw += rgba[y * stride : (y + 1) * stride]

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return (
            struct.pack(">I", len(payload))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


def write_ico(path: Path, images: list[tuple[int, Path]]) -> None:
    """Write an ICO containing PNG-compressed entries (Vista+ format).

    Tauri's Win32 resource compiler accepts PNG entries, which keeps this
    script short and lossless compared to hand-packing BMPs.
    """
    payloads = [p.read_bytes() for _, p in images]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)

    entries = bytearray()
    for (size, _), payload in zip(images, payloads):
        entries += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,  # 0 means 256
            0 if size >= 256 else size,
            0,  # palette
            0,  # reserved
            1,  # colour planes
            32,  # bits per pixel
            len(payload),
            offset,
        )
        offset += len(payload)

    path.write_bytes(header + bytes(entries) + b"".join(payloads))


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "src-tauri" / "icons"
    out.mkdir(parents=True, exist_ok=True)

    rendered: dict[int, Path] = {}
    for name, size in SIZES.items():
        target = out / name
        write_png(target, size, render(size))
        rendered[size] = target
        print(f"  {target.name}  {size}x{size}")

    # 16px keeps the small taskbar/small-icon renderings crisp.
    for size in (16, 48, 64):
        write_png(out / f"{size}x{size}.png", size, render(size))
        print(f"  {size}x{size}.png  {size}x{size}")

    write_ico(
        out / "icon.ico",
        [
            (16, out / "16x16.png"),
            (32, out / "32x32.png"),
            (48, out / "48x48.png"),
            (64, out / "64x64.png"),
            (128, out / "128x128.png"),
            (256, out / "128x128@2x.png"),
        ],
    )
    print("  icon.ico")


if __name__ == "__main__":
    main()