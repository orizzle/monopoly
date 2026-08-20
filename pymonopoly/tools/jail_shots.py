"""Snapshot a canned-input run losslessly, to catch the piece inside the jail.

The three-doubles game (rate 8) jails a player around 190 s in, and the AVI of
it is JPEG-coded -- fine for watching, useless for asking which pixel a 3x3
token starts on.  This replays the same deterministic game and takes PNG
grabs of the window instead, so the jail corner can be diffed against the
board figure exactly.

    python3 tools/jail_shots.py --rate 8 --from 150 --to 215 --out /tmp/shots
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from find_doubles import DICE_ADDR, KEYS          # noqa: E402

# Where the instrumented DOSBox build and its config live.  Set MONO_SCRATCH
# to wherever you built it; these tools drive that build, not a stock one.
SCRATCH = os.environ.get("MONO_SCRATCH", "/tmp/monopoly-scratch")
DOSBOX = f"{SCRATCH}/dbxsrc/dosbox-0.74-3/src/dosbox"
CONF = f"{SCRATCH}/dosbox-sound.conf"
DISPLAY = ":99"


def sh(*args: str) -> str:
    r = subprocess.run(args, capture_output=True, text=True,
                       env={"DISPLAY": DISPLAY, "HOME": "/tmp",
                            "PATH": "/usr/bin:/bin"})
    return r.stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=int, default=8)
    ap.add_argument("--from", dest="start", type=float, default=150.0)
    ap.add_argument("--to", dest="stop", type=float, default=215.0)
    ap.add_argument("--every", type=float, default=0.4)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()

    env = {"DISPLAY": DISPLAY, "HOME": "/tmp", "PATH": "/usr/bin:/bin",
           "MONO_LOG": str(out / "run.log"), "MONO_KEYS": KEYS,
           "MONO_RATE": str(args.rate), "MONO_WATCH": hex(DICE_ADDR),
           "MONO_WATCHLEN": "4", "MONO_LOGIO": "1"}
    subprocess.run(["killall", "dosbox"], capture_output=True)
    time.sleep(1)
    t0 = time.time()
    proc = subprocess.Popen([DOSBOX, "-conf", CONF], env=env,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    win = ""
    for _ in range(40):
        time.sleep(0.4)
        got = sh("xdotool", "search", "--name", "DOSBox")
        if got:
            win = got.splitlines()[0]
            break
    if not win:
        proc.kill()
        raise RuntimeError("DOSBox window never appeared")

    while time.time() - t0 < args.start:
        time.sleep(0.2)
    shot = 0
    while time.time() - t0 < args.stop:
        at = time.time() - t0
        geo = ""
        for line in sh("xdotool", "getwindowgeometry", win).splitlines():
            if "Geometry" in line:
                geo = line.split()[-1]
        sh("import", "-window", "root", "-crop", f"{geo}+0+0", "+repage",
           str(out / f"s{at:07.2f}.png"))
        shot += 1
        time.sleep(args.every)

    subprocess.run(["killall", "dosbox"], capture_output=True)
    print(f"{shot} shots in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
