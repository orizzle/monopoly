"""Drive the original through buying and returning houses, and keep every screen.

The building flow is several prompts deep -- Business, then Houses and
Hotels, then a colour group, then a typed count -- so a probe that presses
whatever key a screen offers never reaches the end of it.  This one is
screen-driven instead: it reads the text off each screen and answers with the
key that particular prompt wants, so the whole sequence can be walked and
photographed.

Feed it a save in which somebody owns a complete colour group; tools/ has no
way to make one, so edit a save directly -- property records start at file
offset 136, five bytes per square, owner at +0 counting players from one.

    MONO_SCRATCH=... python3 tools/build_probe.py --load BUILD1 \
        --group C --units 6 --out /tmp/buildrun
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from play_probe import Dos, read_screen            # noqa: E402


def plan(text: str, args, done: dict) -> list[str]:
    """The keys this screen wants, in order."""
    flat = " ".join(text.split())

    # the building sequence, innermost first
    if "How many units will you buy?" in flat:
        done["asked_buy"] = True
        return list(str(args.units)) + ["Return"]
    if "How many units to return?" in flat:
        done["asked_return"] = True
        return list(str(args.units)) + ["Return"]
    if "you wish to improve" in flat or "to return improvements" in flat:
        return [args.group]
    if "Houses and Hotels" in flat:                 # the business menu
        if not done.get("built"):
            done["built"] = True
            return ["h"]
        if not done.get("returned"):
            done["returned"] = True
            return ["r"]
        return ["g"]
    if "Want to do some Business" in flat:
        return ["b"] if not done.get("returned") else ["g"]

    # anything else: leave the game alone and move on.  The purchase screen
    # offers Business too, which is the only way in when the player lands on
    # a square they do not already own.
    if "Purchase it from the bank" in flat:
        return ["b"] if not done.get("returned") else ["g"]
    if "Do you choose to pay" in flat:
        return ["f"]
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--load", default="BUILD1")
    ap.add_argument("--group", default="C")
    ap.add_argument("--units", type=int, default=6)
    ap.add_argument("--steps", type=int, default=120)
    ap.add_argument("--pace", type=float, default=0.4)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    scratch = out / ".probe.png"

    dos = Dos()
    time.sleep(6)
    dos.key("F2", pause=1.5)
    dos.type(args.load)
    dos.key("Return", pause=18)

    seen: set[str] = set()
    done: dict = {}
    kept = 0
    for step in range(args.steps):
        if not dos.alive():
            print(f"emulator exited at step {step}")
            break
        geo = dos.snap(scratch)
        if geo != "640x400":
            h = hashlib.sha1(scratch.read_bytes()).hexdigest()[:12]
            if h not in seen:
                seen.add(h)
                kept += 1
                scratch.replace(out / f"brd-{step:03d}-{kept:03d}.png")
            dos.key("Return", pause=0.3)
            continue

        keys, text = read_screen(scratch)
        digest = " ".join(text.split())[:160]
        if digest and digest not in seen:
            seen.add(digest)
            kept += 1
            dest = out / f"scr-{step:03d}-{kept:03d}.png"
            scratch.replace(dest)
            head = next((line.strip() for line in text.splitlines()
                         if line.strip()), "")
            print(f"{step:3d} {dest.name} | {head[:52]}")

        wanted = plan(text, args, done)
        if not wanted:
            # no scripted answer: take whatever hot key the screen offers,
            # preferring the ones that do not spend money
            wanted = [next((k for k in "gy" if k in keys), None)
                      or (keys[0] if keys else "Return")]
        for k in wanted:
            dos.key(k, pause=args.pace if len(wanted) == 1 else 0.15)

    scratch.unlink(missing_ok=True)
    subprocess.run(["killall", "dosbox"], capture_output=True)
    print(f"{kept} screens in {out}; reached: {sorted(done)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
