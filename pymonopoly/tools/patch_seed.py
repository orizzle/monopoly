"""Give the 1985 program a seed that can be set, so it can be raced.

The original has no reproducible seed, which is a measured fact rather than a
guess.  Three things were established from the binary and from running it:

  * Randomize (0x0F14) is never called -- zero call sites in MONOCODE.CHN.
  * RandSeed's initial value is a constant in the .COM image, 0x2E024489.
  * There are exactly seven Random(n) call sites, and every one of them sits
    in a fixed-count `for` loop or straight-line code.

Those three together say the game should be deterministic.  It is not: two
runs driven with byte-identical keystrokes disagree on the very first die.
The remaining explanation is that RandSeed itself does not survive -- it sits
at DS:0x01FC, low in the runtime's data area, where the program's own I/O
scribbles over it.  Stubbing Random to a constant removes every divergence
except one blinking cursor cell, which confirms the dice are the only channel
the nondeterminism travels through.

So the fix is to move the seed somewhere nothing else touches.  Randomize is
dead code, and its fourteen-byte body is the one block in the runtime that is
provably never executed, so the seed lives there now.  The patch only rewrites
displacement bytes inside Random -- every instruction keeps its length and
every address in the binary stays put, so all the offsets this project has
already measured remain valid.

    python3 tools/patch_seed.py --seed 0x2E024489 --out ../game-fixed
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

# File offset = memory address - 0x100 for a .COM.
SEED_STORE = 0x0F14          # the dead Randomize body: low word
SEED_STORE_HI = 0x0F16       # ... and high word
RANDOMIZE_FILE = 0x0E14

# The four displacement sites inside Random that name the seed variable.
# (file offset, original bytes, patched bytes)
SITES = (
    (0x0FE6, "8b1efe01", "8b1e160f"),   # mov bx,[0x1fe] -> [0x0f16]
    (0x0FEA, "8b0efc01", "8b0e140f"),   # mov cx,[0x1fc] -> [0x0f14]
    (0x1010, "891efe01", "891e160f"),   # mov [0x1fe],bx -> [0x0f16]
    (0x1014, "890efc01", "890e140f"),   # mov [0x1fc],cx -> [0x0f14]
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default="/vmstore/claude/monopoly/game")
    ap.add_argument("--out", default="/vmstore/claude/monopoly/game-fixed")
    ap.add_argument("--seed", type=lambda s: int(s, 0), default=0x2E024489,
                    help="32-bit RandSeed; the stock image starts at "
                         "0x2E024489")
    args = ap.parse_args()

    src, dst = Path(args.game), Path(args.out)
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.is_file():
            shutil.copy2(f, dst / f.name)

    com = dst / "MONOPOLY.COM"
    data = bytearray(com.read_bytes())

    for off, want, new in SITES:
        found = bytes(data[off:off + 4]).hex()
        if found != want:
            print(f"Random is not shaped as expected at file 0x{off:04X}: "
                  f"expected {want}, found {found}")
            return 1
        data[off:off + 4] = bytes.fromhex(new)

    # Seed the new home.  Low word first, matching the store order.
    lo, hi = args.seed & 0xFFFF, (args.seed >> 16) & 0xFFFF
    data[RANDOMIZE_FILE:RANDOMIZE_FILE + 2] = lo.to_bytes(2, "little")
    data[RANDOMIZE_FILE + 2:RANDOMIZE_FILE + 4] = hi.to_bytes(2, "little")

    com.write_bytes(bytes(data))
    print(f"patched {com}")
    print(f"  RandSeed moved from DS:0x01FC to DS:0x{SEED_STORE:04X} "
          f"(the dead Randomize body)")
    print(f"  initial seed = 0x{args.seed:08X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
