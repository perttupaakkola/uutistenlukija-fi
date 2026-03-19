#!/usr/bin/env python3
"""
Generate 7 category OG images (1200×630) as proper PNG files.
Pure stdlib — no PIL required.

Design spec (Sara/Felix 2026-03-19):
  - Background: dark navy #1c2e4a
  - Site name "UUTISTENLUKIJA" in large white text (top-left area)
  - Tagline "fi" domain badge
  - Category color accent bar (left 10px edge) + bottom accent strip
  - Category name in large white text (center-bottom area)
  - Output: static/images/og-{category}.png (1200×630)

Usage: python3 pipeline/gen_og_images.py
"""

import os
import struct
import zlib
from pathlib import Path

# ---------------------------------------------------------------------------
# Category map: slug → (Finnish label, hex color)
# ---------------------------------------------------------------------------
CATEGORIES = {
    "kotimaa":    ("Kotimaa",    "#3498db"),
    "ulkomaat":   ("Ulkomaat",   "#e74c3c"),
    "talous":     ("Talous",     "#f39c12"),
    "teknologia": ("Teknologia", "#8e44ad"),
    "urheilu":    ("Urheilu",    "#27ae60"),
    "kulttuuri":  ("Kulttuuri",  "#d35400"),
    "tiede":      ("Tiede",      "#16a085"),
}

W, H = 1200, 630
NAVY = (0x1c, 0x2e, 0x4a)    # dark navy background
WHITE = (255, 255, 255)


# ---------------------------------------------------------------------------
# PNG helpers
# ---------------------------------------------------------------------------

def _chunk(name: bytes, data: bytes) -> bytes:
    c = name + data
    return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)


def _ihdr(width: int, height: int) -> bytes:
    data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return _chunk(b"IHDR", data)


def _idat(pixels: list[list[tuple]]) -> bytes:
    """pixels[y][x] = (r,g,b)"""
    raw = bytearray()
    for row in pixels:
        raw.append(0)  # filter type None
        for r, g, b in row:
            raw.extend([r, g, b])
    compressed = zlib.compress(bytes(raw), 9)
    return _chunk(b"IDAT", compressed)


def _iend() -> bytes:
    return _chunk(b"IEND", b"")


def hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


# ---------------------------------------------------------------------------
# Simple bitmap font — 5×7 pixel glyphs for A-Z, 0-9, space, .fi chars
# ---------------------------------------------------------------------------
# Each glyph is 5 columns × 7 rows, encoded as 7 integers (5 bits each, MSB=left)
GLYPHS = {
    'A': [0b01110,0b10001,0b10001,0b11111,0b10001,0b10001,0b10001],
    'B': [0b11110,0b10001,0b10001,0b11110,0b10001,0b10001,0b11110],
    'C': [0b01110,0b10001,0b10000,0b10000,0b10000,0b10001,0b01110],
    'D': [0b11100,0b10010,0b10001,0b10001,0b10001,0b10010,0b11100],
    'E': [0b11111,0b10000,0b10000,0b11110,0b10000,0b10000,0b11111],
    'F': [0b11111,0b10000,0b10000,0b11110,0b10000,0b10000,0b10000],
    'G': [0b01110,0b10001,0b10000,0b10111,0b10001,0b10001,0b01111],
    'H': [0b10001,0b10001,0b10001,0b11111,0b10001,0b10001,0b10001],
    'I': [0b01110,0b00100,0b00100,0b00100,0b00100,0b00100,0b01110],
    'J': [0b00111,0b00010,0b00010,0b00010,0b00010,0b10010,0b01100],
    'K': [0b10001,0b10010,0b10100,0b11000,0b10100,0b10010,0b10001],
    'L': [0b10000,0b10000,0b10000,0b10000,0b10000,0b10000,0b11111],
    'M': [0b10001,0b11011,0b10101,0b10001,0b10001,0b10001,0b10001],
    'N': [0b10001,0b11001,0b10101,0b10011,0b10001,0b10001,0b10001],
    'O': [0b01110,0b10001,0b10001,0b10001,0b10001,0b10001,0b01110],
    'P': [0b11110,0b10001,0b10001,0b11110,0b10000,0b10000,0b10000],
    'Q': [0b01110,0b10001,0b10001,0b10001,0b10101,0b10010,0b01101],
    'R': [0b11110,0b10001,0b10001,0b11110,0b10100,0b10010,0b10001],
    'S': [0b01110,0b10001,0b10000,0b01110,0b00001,0b10001,0b01110],
    'T': [0b11111,0b00100,0b00100,0b00100,0b00100,0b00100,0b00100],
    'U': [0b10001,0b10001,0b10001,0b10001,0b10001,0b10001,0b01110],
    'V': [0b10001,0b10001,0b10001,0b10001,0b01010,0b01010,0b00100],
    'W': [0b10001,0b10001,0b10001,0b10101,0b10101,0b11011,0b10001],
    'X': [0b10001,0b10001,0b01010,0b00100,0b01010,0b10001,0b10001],
    'Y': [0b10001,0b10001,0b01010,0b00100,0b00100,0b00100,0b00100],
    'Z': [0b11111,0b00001,0b00010,0b00100,0b01000,0b10000,0b11111],
    '0': [0b01110,0b10001,0b10011,0b10101,0b11001,0b10001,0b01110],
    '1': [0b00100,0b01100,0b00100,0b00100,0b00100,0b00100,0b01110],
    '2': [0b01110,0b10001,0b00001,0b00110,0b01000,0b10000,0b11111],
    '3': [0b11111,0b00001,0b00010,0b00110,0b00001,0b10001,0b01110],
    '4': [0b00010,0b00110,0b01010,0b10010,0b11111,0b00010,0b00010],
    '5': [0b11111,0b10000,0b11110,0b00001,0b00001,0b10001,0b01110],
    '6': [0b01110,0b10000,0b10000,0b11110,0b10001,0b10001,0b01110],
    '7': [0b11111,0b00001,0b00010,0b00100,0b01000,0b01000,0b01000],
    '8': [0b01110,0b10001,0b10001,0b01110,0b10001,0b10001,0b01110],
    '9': [0b01110,0b10001,0b10001,0b01111,0b00001,0b00001,0b01110],
    '.': [0b00000,0b00000,0b00000,0b00000,0b00000,0b01100,0b01100],
    ' ': [0b00000,0b00000,0b00000,0b00000,0b00000,0b00000,0b00000],
    '-': [0b00000,0b00000,0b00000,0b11111,0b00000,0b00000,0b00000],
    '/': [0b00001,0b00010,0b00010,0b00100,0b01000,0b01000,0b10000],
    'Ä': [0b01010,0b00000,0b10001,0b11111,0b10001,0b10001,0b10001],
    'Ö': [0b01010,0b00000,0b01110,0b10001,0b10001,0b10001,0b01110],
    'Å': [0b00100,0b01010,0b01110,0b10001,0b11111,0b10001,0b10001],
    'a': [0b00000,0b00000,0b01110,0b00001,0b01111,0b10001,0b01111],
    'e': [0b00000,0b00000,0b01110,0b10001,0b11111,0b10000,0b01110],
    'i': [0b00100,0b00000,0b01100,0b00100,0b00100,0b00100,0b01110],
    'j': [0b00010,0b00000,0b00110,0b00010,0b00010,0b10010,0b01100],
    'k': [0b10000,0b10000,0b10010,0b10100,0b11000,0b10100,0b10010],
    'l': [0b01100,0b00100,0b00100,0b00100,0b00100,0b00100,0b01110],
    'm': [0b00000,0b00000,0b11010,0b10101,0b10101,0b10001,0b10001],
    'n': [0b00000,0b00000,0b11110,0b10001,0b10001,0b10001,0b10001],
    'o': [0b00000,0b00000,0b01110,0b10001,0b10001,0b10001,0b01110],
    'r': [0b00000,0b00000,0b10110,0b11001,0b10000,0b10000,0b10000],
    's': [0b00000,0b00000,0b01111,0b10000,0b01110,0b00001,0b11110],
    't': [0b00100,0b00100,0b01110,0b00100,0b00100,0b00101,0b00010],
    'u': [0b00000,0b00000,0b10001,0b10001,0b10001,0b10011,0b01101],
    'g': [0b00000,0b00000,0b01110,0b10001,0b10001,0b01111,0b00001,0b01110],
    'ä': [0b01010,0b00000,0b01110,0b00001,0b01111,0b10001,0b01111],
    'ö': [0b01010,0b00000,0b01110,0b10001,0b10001,0b10001,0b01110],
}

# Fallback for missing chars
GLYPHS_DEFAULT = [0b01110,0b10001,0b10001,0b10001,0b10001,0b10001,0b01110]


def draw_text(pixels, text, x0, y0, color, scale=1):
    """Draw text at (x0, y0) using 5×7 bitmap font, scaled."""
    glyph_w = 5 * scale
    glyph_h = 7 * scale
    gap = max(1, scale)
    cx = x0
    for ch in text:
        glyph = GLYPHS.get(ch, GLYPHS_DEFAULT)
        for row_i, row_bits in enumerate(glyph[:7]):
            for col_i in range(5):
                if row_bits & (1 << (4 - col_i)):
                    for dy in range(scale):
                        for dx in range(scale):
                            py = y0 + row_i * scale + dy
                            px = cx + col_i * scale + dx
                            if 0 <= py < H and 0 <= px < W:
                                pixels[py][px] = color
        cx += glyph_w + gap
    return cx  # return end x for chaining


def text_width(text, scale=1):
    return len(text) * (5 * scale + max(1, scale))


def fill_rect(pixels, x, y, w, h, color):
    for ry in range(y, min(y + h, H)):
        for rx in range(x, min(x + w, W)):
            pixels[ry][rx] = color


def generate_og_image(slug: str, label: str, accent_hex: str, out_path: Path):
    accent = hex_to_rgb(accent_hex)

    # Initialize canvas with navy background
    pixels = [[NAVY] * W for _ in range(H)]

    # Left accent bar (full height, 12px wide)
    fill_rect(pixels, 0, 0, 12, H, accent)

    # Bottom accent strip (full width, 8px tall)
    fill_rect(pixels, 0, H - 8, W, 8, accent)

    # Site name "UUTISTENLUKIJA" — large, top-left area
    site_name = "UUTISTENLUKIJA"
    site_scale = 6
    site_x = 40
    site_y = 80
    draw_text(pixels, site_name, site_x, site_y, WHITE, scale=site_scale)

    # Domain badge ".fi" next to site name (smaller, accent colored)
    fi_scale = 3
    fi_x = site_x + text_width(site_name, site_scale) + 12
    fi_y = site_y + (7 * site_scale) - (7 * fi_scale)
    draw_text(pixels, ".fi", fi_x, fi_y, accent, scale=fi_scale)

    # Divider line under site name
    div_y = site_y + 7 * site_scale + 20
    fill_rect(pixels, site_x, div_y, W - site_x - 40, 2, (*accent, ))

    # Category label — large, lower section
    cat_scale = 10
    cat_w = text_width(label.upper(), cat_scale)
    cat_x = max(40, (W - cat_w) // 2)
    cat_y = H - 8 - 7 * cat_scale - 60
    draw_text(pixels, label.upper(), cat_x, cat_y, WHITE, scale=cat_scale)

    # Category accent pill behind label
    pill_pad = 16
    fill_rect(pixels, cat_x - pill_pad, cat_y - pill_pad,
              cat_w + pill_pad * 2, 7 * cat_scale + pill_pad * 2,
              tuple(max(0, c - 60) for c in accent))
    # Re-draw label over pill
    draw_text(pixels, label.upper(), cat_x, cat_y, WHITE, scale=cat_scale)

    # Tagline below site name
    tagline = "PAIVAN TARKEIMMAT UUTISET"
    tagline_scale = 2
    tagline_y = div_y + 16
    draw_text(pixels, tagline, site_x, tagline_y, tuple(c * 3 // 4 for c in WHITE), scale=tagline_scale)

    # Write PNG
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(_ihdr(W, H))
        f.write(_idat(pixels))
        f.write(_iend())

    kb = out_path.stat().st_size // 1024
    print(f"  {out_path.name}: {W}×{H}, {kb}KB")


if __name__ == "__main__":
    base = Path(__file__).parent.parent / "static" / "images"
    print(f"Generating {len(CATEGORIES)} OG images → {base}/")
    for slug, (label, color) in CATEGORIES.items():
        out = base / f"og-{slug}.png"
        generate_og_image(slug, label, color, out)
    print("Done.")
