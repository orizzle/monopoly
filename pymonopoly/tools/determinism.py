"""Does the original play the same game twice, given the same keystrokes?

Everything about matching the port's dice to the original's rests on this
question.  Turbo Pascal 3.0 only reseeds when the program calls Randomize,
and nothing in this binary reads the BIOS tick (no INT 1Ah) or the 8253
(no `in al,40h`), so the seed is very likely a compile-time constant and the
whole game is reproducible.  That is a claim about the program, though, and
it is cheap to just measure it.

Method: drive the emulator twice with a byte-identical key script and save
every screen in sequence.  Two runs that agree pixel for pixel, roll for
roll, prove determinism far more directly than reading the RNG out of the
disassembly -- and if they disagree, the divergence point says where the
entropy came in.

    python3 tools/determinism.py --steps 60 --out /tmp/det
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import capture  # noqa: E402
from capture import Dos  # noqa: E402

# A fixed cycle, chosen so the game keeps making progress without anything
# ever depending on what is on screen.  The moment a key is picked by reading
# the screen, the two runs are no longer guaranteed the same input.
SCRIPT = ("Return", "space", "space", "n", "space")


def wait_stable(dos: Dos, probe: Path, tries: int = 40,
                interval: float = 0.25) -> bool:
    """Block until the emulator stops redrawing.

    Sending keys on a timer races the game's animations: a key that lands
    while the board is still drawing is swallowed, and one that lands a
    moment later is not, which sends the two runs down different branches.
    That is a harness bug rather than a property of the program, and it is
    what made a longer settle look like nondeterminism.  Waiting for two
    consecutive identical frames ties input to game state instead of to the
    clock.
    """
    prev = None
    for _ in range(tries):
        time.sleep(interval)
        if not dos.snap(probe):
            continue
        cur = probe.read_bytes()
        if prev is not None and cur == prev:
            return True
        prev = cur
    return False


def run(tag: str, out: Path, steps: int, names: list[str],
        settle: float) -> list[Path]:
    dos = Dos()
    dos.start()
    time.sleep(6)

    probe = out / f".{tag}-probe.png"
    for n in names:
        wait_stable(dos, probe)
        dos.type(n)
        wait_stable(dos, probe)
        dos.key("Return")
    wait_stable(dos, probe)
    dos.key("Return")

    shots: list[Path] = []
    for i in range(steps):
        if not dos.alive():
            print(f"  {tag}: emulator exited at step {i}")
            break
        if not wait_stable(dos, probe):
            print(f"  {tag}: screen never settled at step {i}")
        time.sleep(settle)
        path = out / f"{tag}-{i:03d}.png"
        if dos.snap(path):
            shots.append(path)
        dos.key(SCRIPT[i % len(SCRIPT)], pause=0.4)
    probe.unlink(missing_ok=True)
    return shots


def compare(a: list[Path], b: list[Path]) -> int:
    import numpy as np
    from PIL import Image

    n = min(len(a), len(b))
    if len(a) != len(b):
        print(f"run lengths differ: {len(a)} vs {len(b)}")
    same = 0
    first_bad = None
    for i in range(n):
        ia = np.array(Image.open(a[i]).convert("RGB"))
        ib = np.array(Image.open(b[i]).convert("RGB"))
        if ia.shape == ib.shape and not (ia != ib).any():
            same += 1
        elif first_bad is None:
            first_bad = i
            diff = ("different size" if ia.shape != ib.shape
                    else f"{int((ia != ib).any(axis=2).sum())} px differ")
            print(f"first divergence at step {i}: {diff}")
    print(f"\n{same}/{n} steps identical between the two runs")
    if same == n:
        print("the original is DETERMINISTIC: same keys in, same game out")
    return 0 if same == n else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=60)
    ap.add_argument("--out", default="/tmp/det")
    ap.add_argument("--names", nargs="*", default=["ANN", "BEN"])
    ap.add_argument("--settle", type=float, default=1.2)
    ap.add_argument("--conf", help="dosbox.conf to use; the default drives "
                                   "the unpatched original")
    args = ap.parse_args()

    if args.conf:
        capture.CONF = args.conf

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    print("run A ...")
    a = run("a", out, args.steps, args.names, args.settle)
    print("run B ...")
    b = run("b", out, args.steps, args.names, args.settle)
    print(f"captured {len(a)} + {len(b)} screens")
    return compare(a, b)


if __name__ == "__main__":
    raise SystemExit(main())
