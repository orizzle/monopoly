"""Play the original greedily until someone owns a colour group, then tour
every business-menu option and capture what the real program draws.

The group picker, the unit prompts and the buy/sell flows only appear once a
player actually owns property, so they cannot be reached by pressing keys at
the opening board.  This drives a real game, reading each text-mode screen to
decide the next key, and captures the business screens when they are finally
reachable.

    python3 tools/business_tour.py --out /tmp/tour --steps 400
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CONF = os.environ.get("TOUR_CONF", "/vmstore/claude/monopoly/dbx/dosbox.conf")
DOSBOX = os.environ.get("TOUR_DOSBOX", "dosbox")
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
        env = {"DISPLAY": DISPLAY, "HOME": "/tmp", "PATH": "/usr/bin:/bin"}
        for k in ("MONO_LOG", "MONO_LOGIO"):
            if os.environ.get(k):
                env[k] = os.environ[k]
        subprocess.Popen([DOSBOX, "-conf", CONF],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         env=env)
        for _ in range(40):
            time.sleep(0.5)
            out = sh("xdotool", "search", "--name", "DOSBox")
            if out:
                self.win = out.splitlines()[0]
                return
        raise RuntimeError("DOSBox window never appeared")

    def alive(self) -> bool:
        return bool(sh("xdotool", "search", "--name", "DOSBox"))

    def key(self, k: str, pause: float = 0.55) -> None:
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


def text_of(path: Path) -> str:
    from verify_pixels import DecodeError, NotTextMode, decode_capture
    try:
        scr, _ = decode_capture(str(path))
    except (NotTextMode, DecodeError):
        return ""
    return scr.as_text()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--steps", type=int, default=400)
    ap.add_argument("--names", nargs="*", default=["ALICE", "BOB"])
    ap.add_argument("--save-as", default="",
                    help="press F2 and save under this name at --save-step")
    ap.add_argument("--save-step", type=int, default=60)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    scratch = out / ".probe.png"

    dos = Dos()
    dos.start()
    time.sleep(6)
    for n in args.names:
        dos.type(n)
        dos.key("Return")
    dos.key("Return", pause=18)

    saved = 0
    tour: list[str] = []          # keys queued for the current menu visit
    tries = 0
    for step in range(args.steps):
        if not dos.alive():
            print(f"emulator exited at step {step}")
            break
        geo = dos.snap(scratch)
        if geo != "640x400":
            dos.key("Return", pause=0.35)
            continue
        txt = text_of(scratch)
        flat = " ".join(txt.split())

        # Anything with a colour-group list, a unit prompt or a price prompt is
        # a screen the port has never been measured against: keep it.
        interesting = any(s in flat for s in (
            "changed my mind", "Zoning Regulations", "units to return",
            "units will you buy", "Give me the name", "What price",
            "conduct an auction", "Mortgage value is", "unmortgaged for",
            "mortgaged for", "no houses or", "already fully developed",
            "Tell me the color"))
        if interesting:
            dest = out / f"biz-{saved:02d}.png"
            scratch.replace(dest)
            saved += 1
            head = next((l.strip() for l in txt.splitlines() if l.strip()), "")
            print(f"step {step:3d}  saved {dest.name}  | {head[:52]}")
            dos.snap(scratch)

        # "During DiceRoll F1 toggles sound, F2 saves game" (MONOCODE.000
        # 0x0D0C): the save key is only live while the dice are rolling, so
        # it has to follow the key that starts the roll.  Pressed at any
        # prompt it is simply swallowed, which is what an earlier run did.
        if (args.save_as and step >= args.save_step
                and "'s turn" in flat and "?" not in flat):
            dos.key("Return", pause=0.05)
            dos.key("F2", pause=1.5)
            dos.snap(out / "save-prompt.png")
            dos.type(args.save_as)
            dos.key("Return", pause=1.5)
            dos.snap(out / "save-done.png")
            print(f"step {step}: saved as {args.save_as}")
            args.save_as = ""
            continue

        if tour:
            dos.key(tour.pop(0))
            continue

        # The purchase prompt offers Purchase / Auction / Business / Go on, so
        # "b" there opens the business menu instead of buying -- which is how
        # an earlier run went round the same square forever, never owning
        # anything and never reaching a colour group.
        if "isn't owned" in flat and "Purchase" in flat:
            dos.key("p")
            continue
        if "some Business" in flat:
            tries += 1
            if tries % 3 == 0:
                tour = ["Return", "g"]
                dos.key("b")           # look at the group picker
                time.sleep(0.2)
                dos.key("h")
                continue
            dos.key("g")
            continue
        m = re.search(r"How many units[^?]*\?", flat)
        if m:
            dos.type("1")
            dos.key("Return")
            continue
        dos.key("Return", pause=0.35)

    scratch.unlink(missing_ok=True)
    subprocess.run(["pkill", "dosbox"], capture_output=True)
    print(f"{saved} business screens in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
