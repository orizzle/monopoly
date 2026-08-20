"""Play the original until someone is jailed, then always choose Roll.

The jail prompt is drawn on the board, in graphics mode, so play_probe's
text-mode hot-key reader cannot see it: that probe presses Return at every
graphics frame, which the jail prompt ignores, and a canned-key run answers
it with P because P is already in the stream for Purchase.  Neither reaches
the roll-out-of-jail path -- the three rolls, what the board says after each,
and the forced $50 on the third.

This one cycles a few keys at every graphics frame instead.  A prompt ignores
what it does not accept, so `r` answers "or Roll?" and is inert at the
Business/Go on prompt, `g` answers that one and is inert in jail.  Every
distinct board frame is kept, which is the only way to see the piece drawn
inside the jail square.

    MONO_LOG=/tmp/jail.iolog MONO_LOGIO=1 \
        python3 tools/jail_probe.py --out /tmp/jailrun --steps 400
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from play_probe import Dos, read_screen           # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--steps", type=int, default=400)
    ap.add_argument("--pace", type=float, default=0.35)
    ap.add_argument("--names", nargs="*", default=["ALICE", "BOB"])
    # Never P: paying $50 leaves jail at once and skips the whole path.
    ap.add_argument("--prefer", default="rgy",
                    help="text-mode hot keys, in order of preference")
    ap.add_argument("--load", default="",
                    help="F2 at the name prompt and resume this saved game")
    ap.add_argument("--board-keys", default="r,g,Return",
                    help="keys to cycle at each graphics-mode frame")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    scratch = out / ".probe.png"
    board_keys = args.board_keys.split(",")

    dos = Dos()
    time.sleep(6)
    if args.load:
        # F2 at "Who are the players?" resumes a saved game.  Editing one is
        # the only quick way into jail: 500 steps of ordinary play never got
        # there.  Ply record +15 is the in-jail flag and +18 the roll count.
        dos.key("F2", pause=1.5)
        dos.type(args.load)
        dos.key("Return", pause=18)
    else:
        for n in args.names:
            dos.type(n)
            dos.key("Return")
        dos.key("Return", pause=18)

    seen: set[str] = set()
    frames = 0
    turn = 0
    for step in range(args.steps):
        if not dos.alive():
            print(f"emulator exited at step {step}")
            break
        geo = dos.snap(scratch)
        if geo != "640x400":
            h = hashlib.sha1(scratch.read_bytes()).hexdigest()[:12]
            if h not in seen:
                seen.add(h)
                frames += 1
                scratch.replace(out / f"brd-{step:03d}-{frames:03d}.png")
            # Cycle rather than hammer one key: the board carries two
            # different prompts and each ignores the other's letter.
            dos.key(board_keys[turn % len(board_keys)], pause=0.3)
            turn += 1
            continue
        keys, text = read_screen(scratch)
        digest = " ".join(text.split())[:160]
        if digest and digest not in seen:
            seen.add(digest)
            dest = out / f"scr-{step:03d}.png"
            scratch.replace(dest)
            head = next((l.strip() for l in text.splitlines() if l.strip()), "")
            print(f"{step:3d} {dest.name} keys={keys or '-':10s} | {head[:46]}")
        choice = next((k for k in args.prefer if k in keys), None)
        if choice is None and keys:
            choice = keys[0]
        dos.key(choice or "Return", pause=args.pace)

    scratch.unlink(missing_ok=True)
    subprocess.run(["killall", "dosbox"], capture_output=True)
    print(f"{frames} board frames in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
