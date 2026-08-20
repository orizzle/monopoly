"""Turn the 1985 program into a closed, reproducible system.

Two things make the original impossible to race against the port, and both
are addressed here.

1. The seed.  Randomize (0x0F14) is never called, so RandSeed starts from a
   constant in the .COM image -- but it lives at DS:0x01FC, low in the
   runtime's data area, where the program scribbles over it.  The seed is
   moved into the dead Randomize body, which is the one block in the runtime
   provably never executed.

2. The input.  Keystrokes arrive from a human (or from xdotool) in real time,
   so the number of prompts answered before a given roll varies, which shifts
   the Random sequence and sends two runs down different games.  Every
   keystroke in the program funnels through exactly two routines -- they hold
   the only two `int 16h` instructions in the whole binary --

       0x0853  KeyPressed : int 16h / AH=1
       0x086C  ReadKey    : int 16h / AH=0

   so replacing those two with table-driven versions removes real time from
   the program entirely.  ReadKey returns bytes from a 16-entry table that
   cycles forever; KeyPressed reports a key ready every 16th poll, which
   keeps `repeat ... until KeyPressed` animation loops running for a fixed
   number of iterations instead of a clock-dependent one.

Both routines are self-contained: the only references into 0x0853..0x089E
from outside are calls to the two entry points, so the blocks can be
rewritten without moving anything else.  Every other address in the binary
stays exactly where it was.

    python3 tools/patch_deterministic.py --seed 0x2E024489
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

# --- layout, in memory addresses (file offset = memory - 0x100) -----------
KEYPRESSED = 0x0853        # 0x0853..0x086B is free once rewritten
POLL_COUNT = 0x086A        # 2 bytes, in that block's tail
READKEY = 0x086C           # 0x086C..0x089E likewise
KEY_INDEX = 0x0884         # 2 bytes
KEY_TABLE = 0x0886         # 16 bytes, ending at 0x0895 inside the block
TABLE_LEN = 16

SEED_LOW = 0x0F14          # the dead Randomize body
SEED_HIGH = 0x0F16

# Random's four references to the seed variable.
SEED_SITES = (
    (0x0FE6, "8b1efe01", "8b1e160f"),
    (0x0FEA, "8b0efc01", "8b0e140f"),
    (0x1010, "891efe01", "891e160f"),
    (0x1014, "890efc01", "890e140f"),
)

# The original first bytes of each routine, checked before patching.
KEYPRESSED_HEAD = "803e920100"
READKEY_HEAD = "a09201"

# A cycle that answers the game's prompts.  It also supplies the player
# names, since name entry reads through the same routine: "A", "B".
DEFAULT_KEYS = bytes([
    0x32, 0x0D,              # "2" players <enter>
    0x41, 0x0D,              # name "A" <enter>
    0x42, 0x0D,              # name "B" <enter>
    0x0D, 0x20,              # then a fixed repeating answer pattern
    0x20, 0x0D, 0x6E, 0x20,
    0x0D, 0x20, 0x20, 0x0D,
])


def w16(v: int) -> bytes:
    return (v & 0xFFFF).to_bytes(2, "little")


def keypressed_code(mask: int) -> bytes:
    """Report a key ready deterministically.

    mask 0 means "always ready", which collapses every
    `repeat ... until KeyPressed` to a single pass.  A non-zero mask reports
    ready once every mask+1 polls, keeping those loops spinning for a fixed
    number of iterations so the animations still play.
    """
    if mask == 0:
        return b"\xb8\x01\x00\xc2\x01\x00"     # mov ax,1 / ret 1
    return (b"\xff\x06" + w16(POLL_COUNT)      # inc word [count]
            + b"\xa1" + w16(POLL_COUNT)        # mov ax,[count]
            + b"\x25" + w16(mask)              # and ax,mask
            + b"\xf7\xd8"                      # neg ax   (CF=0 iff ax==0)
            + b"\x1b\xc0"                      # sbb ax,ax
            + b"\x40"                          # inc ax   -> 1 when ax was 0
            + b"\xc2\x01\x00")                 # ret 1


def readkey_code() -> bytes:
    """Return the next byte of the cycling table.

    BX is saved and restored: the routine this replaces only ever touches
    AX, so a caller is entitled to hold a value in BX across the call, and
    clobbering it corrupts the callers in the runtime's own text-input path.
    """
    return (b"\x53"                            # push bx
            + b"\x8b\x1e" + w16(KEY_INDEX)     # mov bx,[index]
            + b"\x8a\x87" + w16(KEY_TABLE)     # mov al,[bx+table]
            + b"\x43"                          # inc bx
            + b"\x83\xe3\x0f"                  # and bx,0x0f
            + b"\x89\x1e" + w16(KEY_INDEX)     # mov [index],bx
            + b"\x5b"                          # pop bx
            + b"\x32\xe4"                      # xor ah,ah
            + b"\xc2\x01\x00")                 # ret 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default="/vmstore/claude/monopoly/game")
    ap.add_argument("--out", default="/vmstore/claude/monopoly/game-det")
    ap.add_argument("--seed", type=lambda s: int(s, 0), default=0x2E024489)
    ap.add_argument("--keys", help="16 key bytes as hex; default is built in")
    ap.add_argument("--poll", type=lambda s: int(s, 0), default=0x0F,
                    help="KeyPressed reports ready every poll+1 calls; "
                         "0 means always ready")
    args = ap.parse_args()

    keys = bytes.fromhex(args.keys) if args.keys else DEFAULT_KEYS
    if len(keys) != TABLE_LEN:
        print(f"the key table must be exactly {TABLE_LEN} bytes")
        return 1

    src, dst = Path(args.game), Path(args.out)
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.is_file():
            shutil.copy2(f, dst / f.name)

    com = dst / "MONOPOLY.COM"
    data = bytearray(com.read_bytes())

    def put(mem: int, blob: bytes) -> None:
        off = mem - 0x100
        data[off:off + len(blob)] = blob

    def head(mem: int, n: int) -> str:
        off = mem - 0x100
        return bytes(data[off:off + n]).hex()

    # -- sanity: everything must be where the disassembly said ------------
    if head(KEYPRESSED, 5) != KEYPRESSED_HEAD:
        print(f"KeyPressed not found at 0x{KEYPRESSED:04X}: {head(KEYPRESSED, 5)}")
        return 1
    if head(READKEY, 3) != READKEY_HEAD:
        print(f"ReadKey not found at 0x{READKEY:04X}: {head(READKEY, 3)}")
        return 1
    for off, want, _ in SEED_SITES:
        if bytes(data[off:off + 4]).hex() != want:
            print(f"Random not shaped as expected at file 0x{off:04X}")
            return 1

    # -- seed --------------------------------------------------------------
    for off, _, new in SEED_SITES:
        data[off:off + 4] = bytes.fromhex(new)
    put(SEED_LOW, w16(args.seed))
    put(SEED_HIGH, w16(args.seed >> 16))

    # -- input -------------------------------------------------------------
    kp, rk = keypressed_code(args.poll), readkey_code()
    put(KEYPRESSED, kp.ljust(POLL_COUNT - KEYPRESSED, b"\x90"))
    put(POLL_COUNT, w16(0))
    put(READKEY, rk.ljust(KEY_INDEX - READKEY, b"\x90"))
    put(KEY_INDEX, w16(0))
    put(KEY_TABLE, keys)

    com.write_bytes(bytes(data))
    print(f"patched {com}")
    print(f"  seed      0x{args.seed:08X} at DS:0x{SEED_LOW:04X}")
    print(f"  KeyPressed {len(kp)} bytes, ready every 16th poll")
    print(f"  ReadKey    {len(rk)} bytes, cycling {TABLE_LEN} keys: "
          f"{keys.hex()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
