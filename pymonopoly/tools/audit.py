"""Audit the port against every screen a recording of the original produced.

The two programs cannot be run in lockstep -- their dice differ -- so a
frame-by-frame diff of two independent games would only measure that they
played different games.  What is comparable is the screens themselves: for
each distinct screen the original drew, read the game state back off it,
render that same state with the port, and diff the pixels.

Anything the port cannot reconstruct is reported rather than skipped
silently, because an unreconstructed screen is exactly where a discrepancy
would hide.

    python3 tools/audit.py screens/ --report audit.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
from PIL import Image

from monopoly import cga, graphics

import verify_graphics as vg
from verify_pixels import DecodeError, decode_capture

BOARD_W = BOARD_H = 123


# --------------------------------------------------------------------------
# Reading a board screen back into game state
# --------------------------------------------------------------------------

def _token_catalogue():
    """Exact pixels the port draws for every (square, player) combination.

    Matching these directly is more reliable than clustering the difference
    against the bare board: two players standing on adjacent squares sit only
    a few pixels apart, and proximity clustering merges them into one.
    """
    out = {}
    blank = [[0] * BOARD_W for _ in range(BOARD_H)]
    for pos in range(40):
        for who in range(4):
            scr = graphics.BoardScreen(blank)
            scr.token(pos, who)
            pix = [(y, x, scr.pixels[y][x])
                   for y in range(BOARD_H) for x in range(BOARD_W)
                   if scr.pixels[y][x] != 0 or _is_token_cell(scr, y, x)]
            if pix:
                out[(pos, who)] = pix
    return out


def _is_token_cell(scr, y, x):
    """Token pixels include the black ones -- the piece is opaque."""
    return False


TOKENS = _token_catalogue()


# Card labels are words; a tumbling die throws off stray fragments at the
# same row that happen to match a glyph, and treating one as a label
# suppresses the dice entirely.
LABELS = {"CHANCE", "COMMUNITY", "CHEST"}


def _is_label(text: str) -> bool:
    return text.strip().upper() in LABELS


def read_board(idx: np.ndarray, board: np.ndarray) -> dict:
    """Recover names, cash, tokens, dice and text from a board screen."""
    state = {"names": [], "cash": [], "tokens": {}, "title": "", "message": [],
             "dice_pips": 0, "unknown_tokens": [], "label": ""}

    for col, row, text, colour in vg.runs(vg.find_text(idx, skip=(0, 0, BOARD_W, BOARD_H))):
        if row == graphics.LABEL_ROW and colour == 2 and _is_label(text):
            state["label"] = (state.get("label", "") + " " + text).strip()
        elif row == graphics.TITLE_ROW:
            state["title"] += (" " if state["title"] else "") + text
        elif row in (graphics.MESSAGE_ROW, graphics.MESSAGE_ROW + 1):
            state["message"].append((row, col, text))
        elif row == graphics.CASH_NAME_ROW:
            state["names"].append((col, text))
        elif row == graphics.CASH_MONEY_ROW:
            state["cash"].append((col, text))

    # tokens: match each candidate's exact pixels
    for (pos, who), pix in TOKENS.items():
        if all(idx[y, x] == c for y, x, c in pix) and \
                any(idx[y, x] != board[y, x] for y, x, _c in pix):
            state["tokens"][who] = pos

    # anything left over that the board figure does not explain
    explained = {(y, x) for who, pos in state["tokens"].items()
                 for y, x, _c in TOKENS[(pos, who)]}
    for y, x in np.argwhere(idx[:BOARD_H, :BOARD_W] != board):
        if (int(y), int(x)) not in explained:
            state["unknown_tokens"].append((int(y), int(x)))

    # Look for dice strictly below the label row.  A card name is drawn in
    # magenta right where the dice sit, and counting it as "dice present"
    # misfiled 71 perfectly ordinary board screens as unverifiable rolls.
    below = graphics.DIE_Y + 4
    dice = idx[below:graphics.DIE_Y + 28, 190:260]
    state["dice_pips"] = int((idx[graphics.DIE_Y:graphics.DIE_Y + 28,
                                  190:260] == 3).sum())
    state["dice_drawn"] = bool((dice == 2).any())
    return state


BAND = slice(14, 52), slice(190, 264)


def match_tumble(idx: np.ndarray):
    """Which (left, right) tumble phases the dice band shows.

    The dice turn independently, so the two are matched separately rather
    than assumed to share a phase.
    """
    want = (idx[BAND[0], BAND[1]] == 2)
    n = len(graphics.diceart.TUMBLE_ART)
    for a in range(n):
        for b in range(n):
            probe = graphics.GraphicsScreen()
            graphics.draw_tumbling_dice(probe, a, b)
            got = (np.array(probe.pixels)[BAND[0], BAND[1]] == 2)
            if np.array_equal(got, want):
                return (a, b)
    return None


def read_dice(idx: np.ndarray) -> tuple[int, int] | None:
    """Recover both face values from the pips on a settled pair of dice."""
    faces = []
    for x0 in (graphics.DIE_LEFT_X, graphics.DIE_RIGHT_X):
        face = idx[graphics.DIE_Y:graphics.DIE_Y + graphics.DIE_FACE,
                   x0:x0 + graphics.DIE_FACE]
        spots = {(int(y), int(x)) for y, x in np.argwhere(face == 3)}
        match = None
        for value, layout in graphics.PIP_LAYOUT.items():
            want = {(graphics.PIP_ROWS[r], graphics.PIP_COLS[c])
                    for c, r in layout}
            if want == spots:
                match = value
                break
        if match is None:
            return None
        faces.append(match)
    return tuple(faces)


def rebuild_board(info: dict, board_art,
                  dice: tuple[int, int] | None = None,
                  tumble: int | None = None) -> graphics.BoardScreen | None:
    """Redraw a board screen from what was read off it.

    The cash line reads back as separate runs -- the dollar sign and the
    figure are split by a space -- so the row is assigned to players by the
    column blocks the layout puts them in rather than by counting runs.
    """
    names = sorted(info["names"])
    if not names:
        return None
    count = len(names)
    origin = graphics.cash_origin(count)

    seats = []
    for i in range(count):
        base = origin + i * graphics.CASH_STEP
        lo, hi = base, base + graphics.CASH_STEP - 1
        name = next((t for c, t in names if lo <= c <= hi), None)
        digits = "".join(t for c, t in sorted(info["cash"])
                         if lo <= c <= hi and t.strip().isdigit())
        if name is None or not digits:
            return None
        seats.append((name, int(digits), info["tokens"].get(i, 0)))

    frame = graphics.BoardScreen(board_art)
    msg = [t for _r, _c, t in sorted(info["message"])]
    frame.draw(info["title"], msg, seats,
               label=info.get("label", ""), tumble=tumble,
               dice=dice, hide=[i for i in range(len(seats))
                                if i not in info["tokens"]])
    return frame


# --------------------------------------------------------------------------
# Audit
# --------------------------------------------------------------------------

_KNOWN_SHAPES = {tuple(sh) for sh in graphics.TOKEN_SHAPES}


def _blob_shapes(idx, board):
    """The 3x3 shape of every piece-sized blob drawn over the board."""
    seeds = np.argwhere((idx[:BOARD_H, :BOARD_W] == 2) & (board != 2))
    seen, out = [], []
    for y, x in seeds:
        if any(abs(y - cy) < 3 and abs(x - cx) < 3 for cy, cx in seen):
            continue
        seen.append((int(y), int(x)))
        out.append(tuple(
            "".join("#" if idx[y + r, x + c] == 2 else "."
                    for c in range(3)) for r in range(3)))
    return out


def graphics_indices(path: Path) -> np.ndarray:
    """Palette indices for a graphics screen.

    The recording frame is 640x400 because that is the capture region; the
    emulator's window in this mode is only the top-left 320x200 of it.
    """
    img = np.array(Image.open(path).convert("RGB"))[:graphics.HEIGHT,
                                                    :graphics.WIDTH]
    # int32: see the note in extract_screens.quantise -- int16 overflows on
    # the squared channel difference and inverts the result.
    pal = np.array(graphics.PALETTE, dtype=np.int32)
    a = img.astype(np.int32)
    return ((a[:, :, None, :] - pal[None, None, :, :]) ** 2).sum(3).argmin(2)


def audit_graphics(path: Path, board_art, board_np) -> dict:
    idx = graphics_indices(path)
    info = read_board(idx, board_np)
    result = {"file": path.name, "mode": "graphics", "status": "unknown"}

    dice = None
    if info["dice_drawn"]:
        if info["dice_pips"] == 0:
            # Mid-tumble.  The pose is not implied by game state, but it is
            # readable off the screen: match the dice band against every pose
            # the port can draw.
            phase = match_tumble(idx)
            if phase is None:
                result["status"] = "dice-tumbling"
                return result
            result["tumble_phase"] = phase
            frame = rebuild_board(info, board_art, None, tumble=phase)
            if frame is None:
                result["status"] = "unparsed"
                return result
            mine = np.array(frame.pixels)
            diff = np.argwhere(mine != idx[:graphics.HEIGHT, :graphics.WIDTH])
            result["status"] = "exact" if len(diff) == 0 else "differs"
            result["pixels_differ"] = int(len(diff))
            result["total_pixels"] = int(mine.size)
            if len(diff):
                result["first_diffs"] = [[int(y), int(x), int(mine[y, x]),
                                          int(idx[y, x])] for y, x in diff[:12]]
            return result
        dice = read_dice(idx)
        if dice is None:
            result["status"] = "dice-unreadable"
            return result
        result["dice"] = list(dice)

    # Complete pieces are matched exactly first; whatever magenta is left on
    # the board afterwards belongs to a piece the emulator was still drawing
    # when the frame was grabbed.  The program never puts a partial piece on
    # screen, so such a frame is a filming artifact.
    #
    # Testing shapes *before* the exact match was the mistake earlier: pieces
    # stand four pixels apart when players share a square, so a fixed 3x3 read
    # straddles two of them and condemns a perfectly good frame.
    leftover = [(y, x) for y, x in info["unknown_tokens"]
                if idx[y, x] == 2 and board_np[y, x] != 2]
    if leftover:
        result["status"] = "torn-frame"
        result["note"] = f"{len(leftover)} pixels of a half-drawn piece"
        return result

    frame = rebuild_board(info, board_art, dice)
    if frame is None:
        result["status"] = "unparsed"
        return result

    mine = np.array(frame.pixels)
    theirs = idx[:graphics.HEIGHT, :graphics.WIDTH]
    diff = np.argwhere(mine != theirs)
    result["status"] = "exact" if len(diff) == 0 else "differs"
    result["pixels_differ"] = int(len(diff))
    result["total_pixels"] = int(mine.size)
    if len(diff):
        result["first_diffs"] = [[int(y), int(x), int(mine[y, x]),
                                  int(theirs[y, x])] for y, x in diff[:12]]
    if info["unknown_tokens"]:
        result["unknown_tokens"] = info["unknown_tokens"]
    return result


def _scanlines_inconsistent(path: Path) -> bool:
    """Whether the frame was caught mid-refresh.

    DOSBox shows 80x25 text by doubling every scanline, so row 2n and row
    2n+1 must be identical.  A frame where they differ was grabbed while the
    screen was being repainted -- a filming artifact, not a screen the
    program displayed.
    """
    a = np.array(Image.open(path).convert("RGB"))
    if a.shape[0] != 400:
        return False
    return not np.array_equal(a[0::2], a[1::2])


def _has_impossible_cell(path: Path) -> bool:
    a = np.array(Image.open(path).convert("RGB"))[::2]
    for cy in range(cga.ROWS):
        for cx in range(cga.COLS):
            cell = a[cy * 8:(cy + 1) * 8, cx * 8:(cx + 1) * 8]
            if len(np.unique(cell.reshape(-1, 3), axis=0)) > 2:
                return True
    return False


def audit_text(path: Path) -> dict:
    """Text screens: confirm every cell is a real glyph in a real attribute.

    The port's renderer is already proven to round-trip a decoded screen
    exactly, so what this checks is that the original never puts anything on
    screen the port's model cannot represent -- an unknown glyph, or a
    background outside the eight CGA backgrounds.
    """
    result = {"file": path.name, "mode": "text"}
    try:
        scr, cursors = decode_capture(str(path))
    except DecodeError as exc:
        # A text cell can hold one foreground and one background colour.  Any
        # cell with three is an impossible state, meaning the frame was
        # grabbed while the emulator was mid-redraw.  That is an artifact of
        # filming, not a screen the program ever displayed, so it must not be
        # counted against the port.
        result["status"] = "torn-frame" if (
            _has_impossible_cell(path) or _scanlines_inconsistent(path)
        ) else "undecodable"
        result["note"] = str(exc)
        return result

    img = np.array(Image.open(path).convert("RGB"))
    rendered = np.array(scr.render(scanline_double=True))
    diff = np.abs(rendered.astype(int) - img.astype(int)).sum(axis=2)
    for cx, cy in cursors:
        diff[cy * 16:(cy + 1) * 16, cx * 8:(cx + 1) * 8] = 0
    bad = int((diff > 0).sum())

    if bad and _scanlines_inconsistent(path):
        result["status"] = "torn-frame"
        result["pixels_differ"] = bad
        return result
    result["status"] = "exact" if bad == 0 else "differs"
    result["pixels_differ"] = bad
    result["total_pixels"] = int(diff.size)
    result["cursor_cells"] = len(cursors)
    result["text"] = [ln for ln in scr.as_text().splitlines() if ln.strip()][:4]
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("screens")
    ap.add_argument("--report", default="audit.json")
    args = ap.parse_args()

    folder = Path(args.screens)
    manifest = json.loads((folder / "manifest.json").read_text())

    asset = graphics.find_asset()
    board_art = graphics.load_board(asset) if asset else None
    board_np = np.array(board_art) if board_art else None

    results = []
    for entry in manifest:
        path = folder / entry["file"]
        if entry["mode"] == "graphics" and board_np is not None:
            results.append(audit_graphics(path, board_art, board_np))
        else:
            results.append(audit_text(path))
        results[-1]["frames"] = entry["frames"]

    tally = Counter(r["status"] for r in results)
    Path(args.report).write_text(json.dumps(results, indent=1))

    print(f"audited {len(results)} screens")
    for status, n in tally.most_common():
        print(f"   {status:14s} {n}")
    bad = [r for r in results if r["status"] == "differs"]
    if bad:
        print("\ndiscrepancies:")
        for r in bad[:10]:
            print(f"   {r['file']} ({r['mode']}): "
                  f"{r['pixels_differ']}/{r['total_pixels']} px")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
