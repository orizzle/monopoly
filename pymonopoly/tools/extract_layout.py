"""Describe a captured screen as panels and coloured text runs.

Feeds the hand-written screen code in monopoly/screens.py.  Decoding a capture
gives an exact cell grid, but a grid dump is a screenshot replay, not a port.
What is wanted is the *structure* the original drew -- filled rectangles and
runs of text in one attribute -- so the port can redraw it with the same
primitives and then be checked back against the emulator.

Usage:
    python3 tools/extract_layout.py ../shots/00-boot.png
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from monopoly import cga
from verify_pixels import decode_capture


def runs(scr: cga.Screen):
    """Consecutive cells on a row sharing one attribute."""
    for y in range(1, cga.ROWS + 1):
        x = 1
        while x <= cga.COLS:
            ch, attr = scr.cell(x, y)
            x2 = x
            while x2 + 1 <= cga.COLS and scr.cell(x2 + 1, y)[1] == attr:
                x2 += 1
            text = "".join(cga._decode(scr.cell(i, y)[0])
                           for i in range(x, x2 + 1))
            if text.strip() or (attr >> 4) != 0:
                yield y, x, x2, attr, text
            x = x2 + 1


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    for path in argv[1:]:
        scr, cursors = decode_capture(path)
        print(f"=== {Path(path).name} ===")
        if cursors:
            print(f"  cursor at {cursors}")
        for y, x1, x2, attr, text in runs(scr):
            fg = cga.COLOR_NAMES[attr & 0x0F]
            bg = cga.COLOR_NAMES[(attr >> 4) & 0x07]
            body = text if text.strip() else f"<fill {x2 - x1 + 1}>"
            print(f"  y={y:2d} x={x1:2d}-{x2:<2d} {fg:>12s} on {bg:<10s} {body!r}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
