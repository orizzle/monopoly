"""Record a deterministic run of the original, start to finish.

Canned input is program-timed, so a given MONO_RATE always produces the same
game -- the same throws in the same order.  find_doubles.py picks a rate; this
replays it with DOSBox's own AVI capture running, so the video shows exactly
the game the search found.

    python3 tools/capture_run.py --rate 26 --seconds 240 --out /tmp/cap
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from find_doubles import DICE_ADDR, KEYS, roll_pairs, triples   # noqa: E402

# Where the instrumented DOSBox build and its config live.  Set MONO_SCRATCH
# to wherever you built it; these tools drive that build, not a stock one.
SCRATCH = os.environ.get("MONO_SCRATCH", "/tmp/monopoly-scratch")
DOSBOX = f"{SCRATCH}/dbxsrc/dosbox-0.74-3/src/dosbox"
DISPLAY = ":99"


def sh(*args: str) -> str:
    r = subprocess.run(args, capture_output=True, text=True,
                       env={"DISPLAY": DISPLAY, "HOME": "/tmp",
                            "PATH": "/usr/bin:/bin"})
    return r.stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=int, required=True)
    ap.add_argument("--seconds", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--capdir", default=f"{SCRATCH}/cap")
    ap.add_argument("--conf", default="",
                    help="dosbox conf to use (defaults by --fullscreen)")
    ap.add_argument("--fullscreen", action="store_true",
                    help="run fullscreen and grab the display instead of "
                         "using DOSBox's own AVI recorder")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    capdir = Path(args.capdir)
    for f in capdir.glob("*.avi"):
        f.unlink()
    capdir.mkdir(parents=True, exist_ok=True)

    # DOSBox's AVI recorder closes its file at every video-mode change and
    # does not reopen, so a run that moves between the board and the panels
    # comes out as a second and a half.  Instead: DOSBox runs fullscreen so
    # both modes fill the same 1280x800 frame, its WAV recorder takes the
    # audio (which is continuous across mode changes), and ffmpeg grabs the
    # X display for the video.  The two are muxed afterwards.
    # An OpenGL window pinned to 1280x800 keeps one frame size across both
    # video modes, which a screen grab needs; the surface driver resizes the
    # window with the mode, and DOSBox's own fullscreen renders garbled on a
    # virtual display.
    base = args.conf or (f"{SCRATCH}/dosbox-gl.conf" if args.fullscreen
                         else f"{SCRATCH}/dosbox-sound.conf")
    conf = out / "capture.conf"
    conf.write_text(Path(base).read_text()
                    .replace(f"captures={SCRATCH}/cap", f"captures={capdir}"))

    log = out / "run.log"
    log.unlink(missing_ok=True)
    env = {"DISPLAY": DISPLAY, "HOME": "/tmp", "PATH": "/usr/bin:/bin",
           "MONO_LOG": str(log), "MONO_KEYS": KEYS, "MONO_RATE": str(args.rate),
           "MONO_WATCH": hex(DICE_ADDR), "MONO_WATCHLEN": "4",
           # the speaker log doubles as the soundtrack: it is rendered to a
           # WAV afterwards rather than recording the emulator's mixer
           "MONO_LOGIO": "1"}
    subprocess.run(["killall", "dosbox"], capture_output=True)
    time.sleep(1)
    t_launch = time.time()
    proc = subprocess.Popen([DOSBOX, "-conf", str(conf)], env=env,
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

    # DOSBox handles its own hotkeys in the SDL loop, so the recorders still
    # start even though the guest's keyboard is fed from the canned stream.
    grab = None
    if args.fullscreen:
        sh("xdotool", "key", "--window", win, "--clearmodifiers", "ctrl+alt+F6")
        errlog = open(out / "ffmpeg.log", "wb")
        grab = subprocess.Popen(
            ["ffmpeg", "-nostdin", "-y", "-f", "x11grab",
             "-framerate", "30", "-video_size", "1280x800",
             "-i", f"{DISPLAY}.0+0,0", "-c:v", "libx264",
             "-preset", "ultrafast", "-qp", "0", str(out / "screen.mkv")],
            stdout=errlog, stderr=errlog)
        # how far into the emulator's life the recording starts, so the
        # rendered speaker track can be lined up with it
        (out / "offset_ms").write_text(
            f"{(time.time() - t_launch) * 1000:.0f}\n")
    else:
        sh("xdotool", "key", "--window", win, "--clearmodifiers", "ctrl+alt+F5")
    print("capture started", flush=True)

    time.sleep(args.seconds)
    if args.fullscreen:
        sh("xdotool", "key", "--window", win, "--clearmodifiers", "ctrl+alt+F6")
        if grab:
            grab.terminate()
            try:
                grab.wait(timeout=15)
            except subprocess.TimeoutExpired:
                grab.kill()
    else:
        sh("xdotool", "key", "--window", win, "--clearmodifiers", "ctrl+alt+F5")
    time.sleep(1.5)
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    subprocess.run(["killall", "dosbox"], capture_output=True)

    pairs = roll_pairs(log) if log.exists() else []
    hits = triples(pairs)
    print(f"{len(pairs)} throws: " + " ".join(f"{a}{b}" for a, b in pairs))
    print(f"triples at {hits}")
    print("segments:", sorted(p.name for p in capdir.glob("*")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
