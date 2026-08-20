"""Record the original's audio and log every speaker write behind it.

The dice, the corner chime and the go-to-jail warble have all been ported from
a reading of the disassembly, and the reading has been wrong more than once.
This drives the real program with real keystrokes -- so a key can be withheld
during the roll, which canned input cannot do -- while the instrumented
emulator logs each OUT to the PIT and the speaker gate with a millisecond
timestamp, and DOSBox's own AVI capture records what it sounds like.

    python3 tools/sound_probe.py --out /tmp/snd --hold 6 --turns 20
"""

from __future__ import annotations

import argparse
import os
import subprocess
import time
from pathlib import Path

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


class Dos:
    def __init__(self, log: Path) -> None:
        self.win = ""
        env = {"DISPLAY": DISPLAY, "HOME": "/tmp", "PATH": "/usr/bin:/bin",
               "MONO_LOG": str(log), "MONO_LOGIO": "1"}
        subprocess.run(["pkill", "dosbox"], capture_output=True)
        time.sleep(1)
        self.proc = subprocess.Popen([DOSBOX, "-conf", CONF],
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, env=env)
        for _ in range(40):
            time.sleep(0.5)
            out = sh("xdotool", "search", "--name", "DOSBox")
            if out:
                self.win = out.splitlines()[0]
                return
        raise RuntimeError("DOSBox window never appeared")

    def alive(self) -> bool:
        return bool(sh("xdotool", "search", "--name", "DOSBox"))

    def key(self, k: str, pause: float = 0.6) -> None:
        sh("xdotool", "key", "--window", self.win, "--clearmodifiers", k)
        time.sleep(pause)

    def type(self, text: str, pause: float = 0.5) -> None:
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
    ap.add_argument("--out", required=True)
    ap.add_argument("--hold", type=float, default=6.0,
                    help="seconds to wait after starting a roll, pressing nothing")
    ap.add_argument("--turns", type=int, default=20)
    ap.add_argument("--names", nargs="*", default=["ALICE", "BOB"])
    ap.add_argument("--step", type=float, default=0.7)
    ap.add_argument("--shot-every", type=int, default=5)
    ap.add_argument("--record", action="store_true",
                    help="also run DOSBox's AVI capture")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    log = out / "io.log"
    log.unlink(missing_ok=True)

    dos = Dos(log)
    time.sleep(6)
    for n in args.names:
        dos.type(n)
        dos.key("Return")
    dos.key("Return", pause=18)          # the board draw is slow
    dos.snap(out / "00-board.png")

    # DOSBox's own recorder: video and PCM audio, started from inside.
    if args.record:
        dos.key("ctrl+alt+F5", pause=1.0)
    mark = time.time()
    print(f"capture started at log time ~{(time.time() - mark) * 1000:.0f}ms")

    # The dice are already tumbling -- they start when the turn does -- so the
    # recording just has to sit still and let them rattle.  Pressing a key
    # first, which this used to do, stopped them before the tape rolled.
    print(f"letting the dice run for {args.hold}s with no keys pressed")
    t0 = time.time()
    time.sleep(args.hold)
    dos.snap(out / "01-during-roll.png")
    dos.key("Return", pause=0.6)      # now stop them
    print(f"held {time.time() - t0:.1f}s, then stopped the dice")

    for i in range(args.turns):
        if not dos.alive():
            print(f"emulator exited after {i} steps")
            break
        # "p" buys when the purchase prompt is up and is harmless elsewhere;
        # owning property is what eventually produces rent, jail and cards.
        dos.key("p" if i % 3 == 0 else "Return", pause=args.step)
        if i % args.shot_every == 0:
            dos.snap(out / f"02-step{i:03d}.png")

    if args.record:
        dos.key("ctrl+alt+F5", pause=1.5)    # stop capture
    time.sleep(1)
    subprocess.run(["pkill", "dosbox"], capture_output=True)
    print(f"log: {log} ({log.stat().st_size if log.exists() else 0} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
