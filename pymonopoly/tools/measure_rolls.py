"""Read the dice the original actually rolls, for a given seed.

With RandSeed relocated to a place the program cannot scribble on (see
tools/patch_seed.py), the original becomes a pure function of its seed, so
its rolls can be predicted -- but only once the number of Random draws it
spends before the first roll is known.  Two 16-card Fisher-Yates shuffles
account for thirty of them; this measures the rest by playing the real thing
and decoding the pips off the board.

    python3 tools/measure_rolls.py --seed 0x2E024489 --steps 8
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import capture  # noqa: E402
from capture import Dos  # noqa: E402
from monopoly import graphics as g  # noqa: E402

MAGENTA = (255, 85, 255)
WHITE = (255, 255, 255)


def read_die(a: np.ndarray, x: int) -> int | None:
    """Decode one die face, or None if it is mid-tumble.

    A settled face draws its pips in white on black.  While the die is
    tumbling it is a blank magenta wireframe cube with no pips at all, so any
    magenta among the pip positions means the roll has not landed.
    """
    on = []
    for ri, r in enumerate(g.PIP_ROWS):
        for ci, c in enumerate(g.PIP_COLS):
            px = tuple(int(v) for v in a[g.DIE_Y + r, x + c])
            if px == MAGENTA:
                return None
            if px == WHITE:
                on.append((ci, ri))
    want = set(on)
    for face, pips in g.PIP_LAYOUT.items():
        if set(pips) == want:
            return face
    return None


def read_dice(path: Path) -> tuple[int, int] | None:
    im = Image.open(path).convert("RGB")
    if im.size != (320, 200):
        return None
    a = np.array(im)
    d1 = read_die(a, g.DIE_LEFT_X)
    d2 = read_die(a, g.DIE_RIGHT_X)
    return (d1, d2) if d1 and d2 else None


def build(seed: int, out: Path) -> str:
    """Patch a copy of the game with the given seed; return a dosbox.conf."""
    game = out / "game"
    subprocess.run([sys.executable, "tools/patch_seed.py",
                    "--seed", hex(seed), "--out", str(game)],
                   check=True, capture_output=True,
                   cwd=str(Path(__file__).resolve().parents[1]))
    conf = out / "dosbox.conf"
    base = Path("/vmstore/claude/monopoly/dbx/dosbox.conf").read_text()
    conf.write_text(base.replace("mount c /vmstore/claude/monopoly/game",
                                 f"mount c {game}"))
    return str(conf)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=lambda s: int(s, 0), default=0x2E024489)
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--names", nargs="*", default=["ANN", "BEN"])
    ap.add_argument("--work", default="/tmp/rolls")
    args = ap.parse_args()

    work = Path(args.work)
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    capture.CONF = build(args.seed, work)
    dos = Dos()
    dos.start()
    time.sleep(6)
    for n in args.names:
        dos.type(n)
        dos.key("Return")
    dos.key("Return", pause=16)

    seen: list[tuple[int, int]] = []
    for i in range(args.steps * 6):
        if not dos.alive():
            break
        shot = work / f"s{i:03d}.png"
        dos.snap(shot)
        d = read_dice(shot)
        if d and (not seen or d != seen[-1]):
            seen.append(d)
            print(f"  settled roll {len(seen)}: {d[0]} + {d[1]}")
        if len(seen) >= args.steps:
            break
        time.sleep(0.45)
        if i % 3 == 2:
            dos.key("space")
    print(f"seed 0x{args.seed:08X} rolls: {seen}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
