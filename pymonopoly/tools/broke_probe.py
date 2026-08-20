"""Load a game whose players have no money and catch the raise-money screen.

Editing a saved game is the quickest way into a state the dice would take an
hour to reach: the save is a raw image of the Ply records, cash sits at offset
0x0D of each 34-byte record, and zeroing it means the first forced payment --
a tax, or a card -- cannot be met.  F2 at the name prompt loads it; F2 during
a dice roll is what wrote it in the first place.

    python3 tools/broke_probe.py --out /tmp/broke --save SAVE1
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from play_probe import Dos, read_screen          # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--save", default="SAVE1")
    ap.add_argument("--steps", type=int, default=160)
    ap.add_argument("--pace", type=float, default=0.5)
    ap.add_argument("--prefer", default="fpgry")
    ap.add_argument("--record", action="store_true",
                    help="grab the display so a frame can be cut afterwards")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    scratch = out / ".probe.png"

    grab = None
    dos = Dos()
    time.sleep(6)
    if args.record:
        # Record the display so the moment can be cut out afterwards: the
        # raise-money screen goes by too fast to catch with snapshots, but
        # the speaker log timestamps it exactly.
        t0 = time.time()
        grab = subprocess.Popen(
            ["ffmpeg", "-nostdin", "-y", "-f", "x11grab", "-framerate", "20",
             "-video_size", "1280x800", "-i", ":99.0+0,0",
             "-c:v", "libx264", "-preset", "ultrafast", "-qp", "0",
             str(out / "screen.mkv")],
            stdout=open(out / "ffmpeg.log", "wb"), stderr=subprocess.STDOUT)
        (out / "grab_offset_ms").write_text(f"{(time.time() - t0) * 1000:.0f}\n")
    # F2 at the "Who are the players?" prompt resumes a saved game.
    dos.key("F2", pause=1.5)
    dos.snap(out / "00-load-prompt.png")
    dos.type(args.save)
    dos.key("Return", pause=18)
    dos.snap(out / "01-loaded.png")

    seen: set[str] = set()
    saved = 0
    for step in range(args.steps):
        if not dos.alive():
            print(f"emulator exited at step {step}")
            break
        geo = dos.snap(scratch)
        if geo != "640x400":
            dos.key("Return", pause=0.3)
            continue
        keys, text = read_screen(scratch)
        flat = " ".join(text.split())
        digest = flat[:160]
        if digest and digest not in seen:
            seen.add(digest)
            dest = out / f"scr-{saved:03d}.png"
            scratch.replace(dest)
            saved += 1
            head = next((l.strip() for l in text.splitlines() if l.strip()), "")
            print(f"{step:3d} {dest.name} keys={keys or '-':8s} | {head[:44]}",
                  flush=True)
            dos.snap(scratch)
        if "RAISE SOME MONEY" in flat.upper():
            dos.snap(out / "RAISE-MONEY.png")
            print(f"*** raise-money screen at step {step} ***", flush=True)
        choice = next((k for k in args.prefer if k in keys), None)
        if choice is None and keys:
            choice = keys[0]
        dos.key(choice or "Return", pause=args.pace)

    scratch.unlink(missing_ok=True)
    if grab:
        grab.terminate()
        try:
            grab.wait(timeout=15)
        except subprocess.TimeoutExpired:
            grab.kill()
    subprocess.run(["killall", "dosbox"], capture_output=True)
    print(f"{saved} screens in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
