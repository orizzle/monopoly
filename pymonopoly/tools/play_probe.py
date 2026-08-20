"""Play the original for real, logging its speaker and saving its screens.

Earlier drivers pressed Return at everything and deadlocked the moment a
screen wanted a letter -- the INCOME TAX prompt takes F or C, and the game
sat on it until the run timed out, which is why the speaker log went quiet
after the first roll.  This one reads the hot keys off the screen by their
attribute and always presses something the screen will accept, so a game
actually runs long enough to reach jail, the cards and a corner crossing.

    MONO_LOG=/tmp/io.log MONO_LOGIO=1 python3 tools/play_probe.py --out /tmp/p
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Where the instrumented DOSBox build and its config live.  Set MONO_SCRATCH
# to wherever you built it; these tools drive that build, not a stock one.
SCRATCH = os.environ.get("MONO_SCRATCH", "/tmp/monopoly-scratch")
DOSBOX = os.environ.get("PROBE_DOSBOX",
                        f"{SCRATCH}/dbxsrc/dosbox-0.74-3/src/dosbox")
CONF = os.environ.get("PROBE_CONF", f"{SCRATCH}/dosbox-sound.conf")
DISPLAY = ":99"

# Hot keys are drawn in their own attribute inside each prompt style: light
# cyan on blue in the message panel, white on green in the overlay.  Adding
# the *body* attributes here as well made every character look like a hot
# key, so the driver pressed letters out of ordinary words, the prompt
# ignored them, and the game sat still -- which is what made the speaker log
# stop after the first turn.
HOTKEY_ATTRS = (0x1B, 0x2F)


def sh(*args: str) -> str:
    r = subprocess.run(args, capture_output=True, text=True,
                       env={"DISPLAY": DISPLAY, "HOME": "/tmp",
                            "PATH": "/usr/bin:/bin"})
    return r.stdout.strip()


class Dos:
    def __init__(self) -> None:
        subprocess.run(["killall", "dosbox"], capture_output=True)
        time.sleep(1)
        env = {"DISPLAY": DISPLAY, "HOME": "/tmp", "PATH": "/usr/bin:/bin"}
        for k in ("MONO_LOG", "MONO_LOGIO"):
            if os.environ.get(k):
                env[k] = os.environ[k]
        self.proc = subprocess.Popen([DOSBOX, "-conf", CONF],
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, env=env)
        self.win = ""
        for _ in range(40):
            time.sleep(0.5)
            out = sh("xdotool", "search", "--name", "DOSBox")
            if out:
                self.win = out.splitlines()[0]
                return
        raise RuntimeError("DOSBox window never appeared")

    def alive(self) -> bool:
        return bool(sh("xdotool", "search", "--name", "DOSBox"))

    def key(self, k: str, pause: float = 0.45) -> None:
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


def read_screen(path: Path):
    from verify_pixels import DecodeError, NotTextMode, decode_capture
    try:
        scr, _ = decode_capture(str(path))
    except (NotTextMode, DecodeError):
        return "", ""
    keys = ""
    for y in range(1, 26):
        for x in range(1, 81):
            ch, attr = scr.cell(x, y)
            if attr in HOTKEY_ATTRS and 33 <= ch < 127:
                keys += chr(ch).lower()
    return keys, scr.as_text()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--steps", type=int, default=400)
    ap.add_argument("--hold", type=float, default=0.0,
                    help="seconds to let the first roll run untouched")
    ap.add_argument("--prefer", default="pfrgy",
                    help="hot keys to choose, in order of preference")
    ap.add_argument("--names", nargs="*", default=["ALICE", "BOB"])
    ap.add_argument("--pace", type=float, default=0.4,
                    help="seconds to wait after each keypress")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    scratch = out / ".probe.png"

    dos = Dos()
    time.sleep(6)
    for n in args.names:
        dos.type(n)
        dos.key("Return")
    dos.key("Return", pause=18)

    if args.hold:
        time.sleep(args.hold)
        dos.snap(out / "roll-held.png")

    seen: set[str] = set()
    saved = 0
    jailed = False          # once someone is in jail, keep every board frame
    for step in range(args.steps):
        if not dos.alive():
            print(f"emulator exited at step {step}")
            break
        geo = dos.snap(scratch)
        if geo != "640x400":
            # The board.  Keep distinct frames too: the jail prompt and the
            # piece's place in the jail square only exist in graphics mode.
            import hashlib
            h = hashlib.sha1(scratch.read_bytes()).hexdigest()[:12]
            if h not in seen:
                seen.add(h)
                tag = "jail" if jailed else "brd"
                dest = out / f"{tag}-{len(seen):03d}.png"
                scratch.replace(dest)
            dos.key("Return", pause=0.3)
            continue
        keys, text = read_screen(scratch)
        digest = " ".join(text.split())[:160]
        if digest and digest not in seen:
            seen.add(digest)
            dest = out / f"scr-{saved:03d}.png"
            scratch.replace(dest)
            saved += 1
            head = next((l.strip() for l in text.splitlines() if l.strip()), "")
            print(f"{step:3d} {dest.name} keys={keys or '-':10s} | {head[:46]}")
            dos.snap(scratch)
        if "IN JAIL" in text.upper():
            jailed = True
        choice = next((k for k in args.prefer if k in keys), None)
        if choice is None and keys:
            choice = keys[0]
        dos.key(choice or "Return", pause=args.pace)

    scratch.unlink(missing_ok=True)
    subprocess.run(["killall", "dosbox"], capture_output=True)
    print(f"{saved} distinct screens in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
