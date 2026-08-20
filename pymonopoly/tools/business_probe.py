"""Drive the original into the business menu and capture every frame.

The business flows were ported from a reading of the disassembly, and static
analysis cannot settle screen layout: the colour-group list is drawn by a loop
over the ColorGroup records, so the spacing only exists at run time.  This
plays the real program, presses a given key sequence, and saves a capture
after every key -- in whatever video mode the emulator happens to be in.

    python3 tools/business_probe.py --seq b,h,l --out /tmp/biz/h
"""

from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path

CONF = "/vmstore/claude/monopoly/dbx/dosbox.conf"
DISPLAY = ":99"


def sh(*args: str) -> str:
    r = subprocess.run(args, capture_output=True, text=True,
                       env={"DISPLAY": DISPLAY, "HOME": "/tmp",
                            "PATH": "/usr/bin:/bin"})
    return r.stdout.strip()


class Dos:
    def __init__(self) -> None:
        self.win = ""

    def start(self) -> None:
        subprocess.run(["pkill", "dosbox"], capture_output=True)
        time.sleep(1)
        subprocess.Popen(["dosbox", "-conf", CONF],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         env={"DISPLAY": DISPLAY, "HOME": "/tmp",
                              "PATH": "/usr/bin:/bin"})
        for _ in range(40):
            time.sleep(0.5)
            out = sh("xdotool", "search", "--name", "DOSBox")
            if out:
                self.win = out.splitlines()[0]
                return
        raise RuntimeError("DOSBox window never appeared")

    def key(self, k: str, pause: float = 1.0) -> None:
        sh("xdotool", "key", "--window", self.win, "--clearmodifiers", k)
        time.sleep(pause)

    def type(self, text: str, pause: float = 0.6) -> None:
        sh("xdotool", "type", "--window", self.win, "--delay", "60", text)
        time.sleep(pause)

    def geometry(self) -> str:
        for line in sh("xdotool", "getwindowgeometry", self.win).splitlines():
            if "Geometry" in line:
                return line.split()[-1]
        return ""

    def snap(self, path: Path) -> str:
        geo = self.geometry()
        if geo:
            sh("import", "-window", "root", "-crop", f"{geo}+0+0", "+repage",
               str(path))
        return geo


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seq", required=True,
                    help="comma-separated xdotool keys pressed in order")
    ap.add_argument("--out", required=True)
    ap.add_argument("--names", nargs="*", default=["ALICE", "BOB"])
    ap.add_argument("--settle", type=float, default=1.4)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    dos = Dos()
    dos.start()
    time.sleep(6)
    for n in args.names:
        dos.type(n)
        dos.key("Return")
    dos.key("Return", pause=18)          # the board draw is slow
    dos.snap(out / "00-board.png")

    for i, k in enumerate(args.seq.split(","), start=1):
        dos.key(k.strip(), pause=args.settle)
        geo = dos.snap(out / f"{i:02d}-{k.strip()}.png")
        print(f"  after {k.strip():8s} mode={geo}")

    subprocess.run(["pkill", "dosbox"], capture_output=True)
    print(f"frames in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
