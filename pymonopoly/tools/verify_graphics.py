"""Check the 320x200 board screen against the emulator.

The board screen is the one place the original leaves text mode, so it needs
its own measuring tool.  This decodes a graphics-mode capture, identifies the
8x8 text drawn over the board figure, rebuilds the screen from
monopoly.graphics, and diffs the result.

Usage:
    python3 tools/verify_graphics.py ../shots/22-board-land.png
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image

from monopoly import graphics
from monopoly.cga import FONT, _decode

_BY_BITMAP: dict[tuple[int, ...], int] = {}
for _code, _glyph in enumerate(FONT):
    _BY_BITMAP.setdefault(tuple(_glyph), _code)


def to_indices(path: str) -> np.ndarray:
    img = np.array(Image.open(path).convert("RGB"))
    if img.shape[:2] != (graphics.HEIGHT, graphics.WIDTH):
        raise ValueError(f"expected 320x200, got {img.shape[1]}x{img.shape[0]}")
    out = np.full(img.shape[:2], -1, dtype=int)
    for i, c in enumerate(graphics.PALETTE):
        mask = ((img[:, :, 0] == c[0]) & (img[:, :, 1] == c[1])
                & (img[:, :, 2] == c[2]))
        out[mask] = i
    if (out < 0).any():
        raise ValueError("capture uses colours outside the CGA palette-1 set")
    return out


def find_text(idx: np.ndarray, skip: tuple[int, int, int, int] | None = None):
    """Yield (col, row, char, colour) for 8x8 cells that hold a ROM glyph."""
    for row in range(graphics.ROWS):
        for col in range(graphics.COLS):
            if skip:
                x0, y0, x1, y1 = skip
                if (col * 8 < x1 and (col + 1) * 8 > x0
                        and row * 8 < y1 and (row + 1) * 8 > y0):
                    continue
            cell = idx[row * 8:(row + 1) * 8, col * 8:(col + 1) * 8]
            colors = set(np.unique(cell).tolist())
            if colors == {0}:
                continue
            ink = colors - {0}
            if len(ink) != 1:
                continue
            color = ink.pop()
            bitmap = tuple(
                int("".join("1" if v == color else "0" for v in cell[r]), 2)
                for r in range(8))
            code = _BY_BITMAP.get(bitmap)
            if code is not None and code != 32:
                yield col + 1, row + 1, _decode(code), color


def runs(items):
    """Group adjacent same-row, same-colour characters into strings."""
    items = sorted(items, key=lambda t: (t[1], t[0]))
    out = []
    for col, row, ch, color in items:
        if out and out[-1][1] == row and out[-1][3] == color \
                and col == out[-1][0] + len(out[-1][2]):
            out[-1][2] += ch
        else:
            out.append([col, row, ch, color])
    return out


NAMES = {0: "black", 1: "cyan", 2: "magenta", 3: "white"}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    asset = graphics.find_asset()
    board = graphics.load_board(asset) if asset else None

    for path in argv[1:]:
        idx = to_indices(path)
        print(f"=== {Path(path).name} ===")

        skip = (0, 0, len(board[0]), len(board)) if board else None
        for col, row, text, color in runs(find_text(idx, skip)):
            print(f"  col={col:2d} row={row:2d} {NAMES[color]:>7s}  {text!r}")

        if board is None:
            print("  (MONOGRAF.GRA not found; skipping the pixel diff)")
            continue

        mine = graphics.GraphicsScreen()
        mine.blit(board, 0, 0)
        got = np.array(mine.pixels)
        h, w = len(board), len(board[0])
        region_diff = int((got[:h, :w] != idx[:h, :w]).sum())
        print(f"  board figure: {region_diff}/{h * w} pixels differ "
              f"(tokens drawn over it account for these)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
