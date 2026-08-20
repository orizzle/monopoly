"""Drive the original under DOSBox and capture its screens.

Screens are the reference the port is measured against, so they have to come
from the real program.  This plays it with xdotool on a headless X display and
saves a PNG whenever the emulator is in 80x25 text mode, skipping the frames
where it has switched to the 320x200 graphics board.

The window resizes when the video mode changes, so the geometry is re-read
before every capture -- capturing a fixed rectangle silently mangles the
graphics-mode frames.

Usage:
    python3 tools/capture.py --out ../shots --prefix play --rounds 30
"""

from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path

CONF = "/vmstore/claude/monopoly/dbx/dosbox.conf"
DISPLAY = ":99"


def sh(*args: str, check: bool = False) -> str:
    env = {"DISPLAY": DISPLAY, "HOME": "/tmp", "PATH": "/usr/bin:/bin"}
    r = subprocess.run(args, capture_output=True, text=True, env=env)
    if check and r.returncode:
        raise RuntimeError(f"{args}: {r.stderr.strip()}")
    return r.stdout.strip()


class Dos:
    def __init__(self) -> None:
        self.win = ""

    def start(self) -> None:
        sh("pkill", "dosbox")
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

    def alive(self) -> bool:
        return bool(sh("xdotool", "search", "--name", "DOSBox"))

    def key(self, k: str, pause: float = 0.9) -> None:
        sh("xdotool", "key", "--window", self.win, "--clearmodifiers", k)
        time.sleep(pause)

    def type(self, text: str, pause: float = 0.6) -> None:
        sh("xdotool", "type", "--window", self.win, "--delay", "50", text)
        time.sleep(pause)

    def geometry(self) -> str:
        out = sh("xdotool", "getwindowgeometry", self.win)
        for line in out.splitlines():
            if "Geometry" in line:
                return line.split()[-1]
        return ""

    def snap(self, path: Path) -> str | None:
        geo = self.geometry()
        if not geo:
            return None
        sh("import", "-window", "root", "-crop", f"{geo}+0+0", "+repage",
           str(path))
        return geo


# Hot keys are drawn in a distinct attribute inside each prompt style, which
# makes them findable without knowing what the prompt says: light cyan on blue
# in the message panel, white on green in the overlay panel.
HOTKEY_ATTRS = (0x1B, 0x2F)


def read_hotkeys(path: Path) -> tuple[str, str]:
    """Returns (available hot keys, full screen text) for a text-mode capture."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
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
    ap.add_argument("--out", default="../shots")
    ap.add_argument("--prefix", default="play")
    ap.add_argument("--rounds", type=int, default=25)
    ap.add_argument("--names", nargs="*", default=["ALICE", "BOB"])
    ap.add_argument("--prefer", default="pg",
                    help="hot keys to choose, in order of preference")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    scratch = out / f".{args.prefix}-probe.png"

    dos = Dos()
    dos.start()
    time.sleep(6)

    for n in args.names:
        dos.type(n)
        dos.key("Return")
    dos.key("Return", pause=16)  # board draw is slow

    saved = 0
    seen: set[str] = set()
    for rnd in range(args.rounds):
        if not dos.alive():
            print(f"emulator exited after round {rnd}")
            break

        geo = dos.snap(scratch)
        if geo != "640x400":
            dos.key("space")  # graphics-mode board: step past it
            continue

        keys, text = read_hotkeys(scratch)
        digest = text.strip()
        if digest and digest not in seen:
            seen.add(digest)
            target = out / f"{args.prefix}-{saved:02d}.png"
            scratch.replace(target)
            saved += 1
            head = next((ln.strip() for ln in text.splitlines() if ln.strip()),
                        "")
            print(f"round {rnd:2d}: saved {target.name}  keys={keys or '-':8s} "
                  f"| {head[:44]}")

        choice = next((k for k in args.prefer if k in keys), None)
        dos.key(choice if choice else "space")

    scratch.unlink(missing_ok=True)
    print(f"{saved} distinct text-mode screens in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
