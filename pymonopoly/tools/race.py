"""Run the original twice on video and compare the screens it shows.

Polling screenshots cannot settle the determinism question.  The board
animates -- the dice tumble for over a second after every roll -- so a
screenshot taken on a timer catches whatever phase the animation happens to
be in, and two runs disagree on frames whose *game state* is identical.  That
is a property of the measuring instrument, not the program.

Recording continuously and then reducing each run to its sequence of distinct
settled screens removes the sampling entirely: transient and duplicate frames
are dropped, so what remains is what the program actually displayed, in
order.  Two runs that produce the same sequence played the same game.

    python3 tools/race.py --conf ../dbx/dosbox-fixed.conf --seconds 90
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import capture  # noqa: E402
from capture import Dos, sh  # noqa: E402

# Same fixed cycle as tools/determinism.py: nothing may depend on what is on
# screen, or the two runs stop receiving identical input.
SCRIPT = ("Return", "space", "space", "n", "space")


def record(tag: str, out: Path, seconds: float, names: list[str],
           beat: float) -> Path:
    dos = Dos()
    dos.start()
    time.sleep(6)

    geo = sh("xdotool", "getwindowgeometry", "--shell", dos.win)
    pos = {k: v for k, v in
           (ln.split("=") for ln in geo.splitlines() if "=" in ln)}
    x, y = pos.get("X", "0"), pos.get("Y", "0")

    video = out / f"{tag}.mkv"
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab",
         "-framerate", "20", "-video_size", "640x400",
         "-i", f":99.0+{x},{y}", "-c:v", "libx264", "-preset", "ultrafast",
         "-qp", "0", str(video)],
        env={"DISPLAY": ":99", "HOME": "/tmp", "PATH": "/usr/bin:/bin"},
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)

    for n in names:
        dos.type(n)
        dos.key("Return")
    dos.key("Return", pause=16)

    end = time.time() + seconds
    i = 0
    while time.time() < end and dos.alive():
        dos.key(SCRIPT[i % len(SCRIPT)], pause=beat)
        i += 1

    ff.communicate(b"q", timeout=20)
    sh("pkill", "dosbox")
    time.sleep(1)
    return video


def screens(video: Path, out: Path) -> list[bytes]:
    d = out / (video.stem + "-screens")
    subprocess.run([sys.executable, "tools/extract_screens.py", str(video),
                    "--out", str(d)], check=True, capture_output=True,
                   cwd=str(Path(__file__).resolve().parents[1]))
    return [p.read_bytes() for p in sorted(d.glob("*.png"))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--conf", default="/vmstore/claude/monopoly/dbx/"
                                      "dosbox-fixed.conf")
    ap.add_argument("--seconds", type=float, default=90)
    ap.add_argument("--beat", type=float, default=1.6)
    ap.add_argument("--names", nargs="*", default=["ANN", "BEN"])
    ap.add_argument("--out", default="/tmp/race")
    args = ap.parse_args()

    capture.CONF = args.conf
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    print("run A ...")
    a = screens(record("a", out, args.seconds, args.names, args.beat), out)
    print("run B ...")
    b = screens(record("b", out, args.seconds, args.names, args.beat), out)

    print(f"\nrun A showed {len(a)} distinct screens, run B showed {len(b)}")
    n = min(len(a), len(b))
    same = 0
    for i in range(n):
        if a[i] == b[i]:
            same += 1
        else:
            print(f"first differing screen: index {i}")
            break
    else:
        print("every screen in the common prefix is identical")
    print(f"{same}/{n} leading screens identical")
    return 0 if same == n and len(a) == len(b) else 1


if __name__ == "__main__":
    raise SystemExit(main())
