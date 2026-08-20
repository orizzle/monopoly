"""Pull the distinct screens out of a recording of the game.

A recording holds the same screen for many frames at a time, so the useful
unit is the distinct screen, not the frame.  This walks a video, drops
duplicate and transitional frames, and writes one PNG per screen along with a
manifest saying which video mode it was in.

Frames captured while the emulator is mid-redraw are discarded: a screen has
to persist for at least `--settle` frames to count, which throws away the
partially-drawn intermediates without losing anything real.

    python3 tools/extract_screens.py recording.mp4 --out screens/
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image

WIDTH, HEIGHT = 640, 400
GRAPHICS = (320, 200)

# CGA text palette, and the four colours the graphics board uses.
from monopoly import cga, graphics  # noqa: E402

TEXT_COLORS = set(cga.PALETTE)
GFX_COLORS = set(graphics.PALETTE)


def frames(path: str):
    """Yield every frame of the video as an HxWx3 uint8 array."""
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE)
    size = WIDTH * HEIGHT * 3
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        yield np.frombuffer(buf, np.uint8).reshape(HEIGHT, WIDTH, 3)
    proc.stdout.close()
    proc.wait()


# Lossy encoding leaves a scatter of near-black pixels where the desktop
# should be pure black, so "empty" needs a tolerance rather than an exact
# zero test.
DARK = 24
DARK_PIXEL_BUDGET = 400


def classify(frame: np.ndarray) -> str:
    """Which video mode the frame shows.

    In graphics mode the emulator's window is only 320x200, so everything
    outside that rectangle is desktop, and near-black.
    """
    outside = frame.copy()
    outside[:GRAPHICS[1], :GRAPHICS[0]] = 0
    lit = int((outside.max(axis=2) > DARK).sum())
    return "graphics" if lit < DARK_PIXEL_BUDGET else "text"


def quantise(frame: np.ndarray, mode: str) -> np.ndarray:
    """Snap to the exact palette, undoing the encoder's colour drift."""
    # int32, not int16: a squared channel difference reaches 255**2 = 65025,
    # which overflows a signed 16-bit accumulator and wraps negative, so
    # argmin then picks the *furthest* colour.  That silently inverted every
    # graphics screen this tool produced.
    pal = np.array(sorted(GFX_COLORS if mode == "graphics" else TEXT_COLORS),
                   dtype=np.int32)
    a = frame.astype(np.int32)
    idx = ((a[:, :, None, :] - pal[None, None, :, :]) ** 2).sum(axis=3).argmin(2)
    return pal[idx].astype(np.uint8)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", default="screens")
    ap.add_argument("--settle", type=int, default=3,
                    help="frames a screen must persist to count as real")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()

    manifest = []
    run_key, run_len, run_frame, run_mode, run_start = None, 0, None, None, 0
    kept = 0

    def flush(end_index):
        nonlocal kept
        if run_frame is None or run_len < args.settle:
            return
        name = f"s{kept:04d}.png"
        Image.fromarray(quantise(run_frame, run_mode)).save(out / name)
        manifest.append({"file": name, "mode": run_mode,
                         "first_frame": run_start, "frames": run_len})
        kept += 1

    for i, fr in enumerate(frames(args.video)):
        if args.limit and i >= args.limit:
            break
        mode = classify(fr)
        key = (mode, fr.tobytes())
        if key == run_key:
            run_len += 1
            continue
        flush(i)
        run_key, run_len, run_frame, run_mode, run_start = key, 1, fr, mode, i
    flush(-1)

    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    modes = {}
    for m in manifest:
        modes[m["mode"]] = modes.get(m["mode"], 0) + 1
    print(f"{kept} distinct screens from {args.video}: {modes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
