"""Race two runs of the original against each other, deterministically.

This is the harness the whole seed question was waiting on.  The original
blocks in INT 16h until a key arrives, so no external driver can feed it
reproducibly -- a keystroke lands whenever the window manager delivers it,
and the game branches on when.  The instrumented DOSBox (see
scratchpad/dbxsrc, include/monolog.h) supplies the keys from inside the
emulator instead, offering one every MONO_RATE polls of INT 16h AH=01.  The
pacing is a count of polls rather than a reading of the clock, which is the
whole point: two runs see the same keys at the same points in the program.

The guest binary is untouched.  Nothing is patched into the game to make
this work, so what runs here is the real 1985 program.

    python3 tools/race_det.py --seconds 90
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
# Set MONO_SCRATCH to wherever the instrumented DOSBox was built.
SCRATCH = Path(os.environ.get("MONO_SCRATCH", "/tmp/monopoly-scratch"))
DOSBOX = SCRATCH / "dbxsrc/dosbox-0.74-3/src/dosbox"

# "ALICE<enter>BOB<enter><enter>" then a fixed answer pattern, repeated.
DEFAULT_KEYS = "414c4943450d424f420d0d" + "200d" * 80


def sh(*args: str) -> str:
    env = {"DISPLAY": ":99", "HOME": "/tmp", "PATH": "/usr/bin:/bin"}
    r = subprocess.run(args, capture_output=True, text=True, env=env)
    return r.stdout.strip()


def run(tag: str, out: Path, seconds: float, conf: str, keys: str,
        rate: int) -> Path:
    env = dict(os.environ)
    env.update({"DISPLAY": ":99", "HOME": "/tmp", "PATH": "/usr/bin:/bin",
                "MONO_KEYS": keys, "MONO_RATE": str(rate),
                "MONO_LOG": str(out / f"{tag}.log")})
    subprocess.run(["pkill", "dosbox"], capture_output=True)
    time.sleep(1)
    proc = subprocess.Popen([str(DOSBOX), "-conf", conf], env=env,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    win = ""
    for _ in range(40):
        time.sleep(0.5)
        win = sh("xdotool", "search", "--name", "DOSBox")
        if win:
            win = win.splitlines()[0]
            break
    if not win:
        raise RuntimeError("DOSBox never appeared")

    geo = sh("xdotool", "getwindowgeometry", "--shell", win)
    pos = {k: v for k, v in
           (ln.split("=") for ln in geo.splitlines() if "=" in ln)}
    x, y = pos.get("X", "0"), pos.get("Y", "0")

    video = out / f"{tag}.mkv"
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab",
         "-framerate", "20", "-video_size", "640x400",
         "-i", f":99.0+{x},{y}", "-c:v", "libx264", "-preset", "ultrafast",
         "-qp", "0", str(video)],
        env=env, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)

    time.sleep(seconds)
    ff.communicate(b"q", timeout=20)
    proc.terminate()
    subprocess.run(["pkill", "dosbox"], capture_output=True)
    time.sleep(1)
    return video


def screens(video: Path, out: Path) -> list[bytes]:
    d = out / (video.stem + "-screens")
    subprocess.run([sys.executable, "tools/extract_screens.py", str(video),
                    "--out", str(d)], check=True, capture_output=True,
                   cwd=str(ROOT))
    return [p.read_bytes() for p in sorted(d.glob("*.png"))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--conf", default="/vmstore/claude/monopoly/dbx/dosbox.conf")
    ap.add_argument("--seconds", type=float, default=90)
    ap.add_argument("--keys", default=DEFAULT_KEYS)
    ap.add_argument("--rate", type=int, default=64)
    ap.add_argument("--out", default=str(SCRATCH / "racedet"))
    args = ap.parse_args()

    if not DOSBOX.exists():
        print(f"instrumented DOSBox not built at {DOSBOX}")
        return 2

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    print("run A ...")
    a = screens(run("a", out, args.seconds, args.conf, args.keys, args.rate),
                out)
    print("run B ...")
    b = screens(run("b", out, args.seconds, args.conf, args.keys, args.rate),
                out)

    print(f"\nrun A showed {len(a)} distinct screens, run B showed {len(b)}")
    n = min(len(a), len(b))
    same = sum(1 for i in range(n) if a[i] == b[i])
    for i in range(n):
        if a[i] != b[i]:
            print(f"first differing screen: index {i}")
            break
    else:
        print("every screen in the common prefix is identical")
    print(f"{same}/{n} leading screens identical")
    if len(a) == len(b) and same == n:
        print("\nthe original is now DETERMINISTIC end to end")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
