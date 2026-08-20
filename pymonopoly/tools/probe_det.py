"""Try deterministic-input settings until the patched original plays.

Feeding the program a canned key stream only works if the stream answers the
prompts it actually asks.  This patches a build, runs it, and reports how far
it got -- whether the board ever appeared, and what text was on screen -- so
the key table and the KeyPressed cadence can be tuned without guessing.

    python3 tools/probe_det.py --poll 0 --keys 320d410d420d0d20200d6e200d20
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
from capture import Dos  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def build(work: Path, seed: int, poll: int, keys: str | None) -> str:
    game = work / "game"
    cmd = [sys.executable, "tools/patch_deterministic.py",
           "--seed", hex(seed), "--poll", hex(poll), "--out", str(game)]
    if keys:
        cmd += ["--keys", keys]
    subprocess.run(cmd, check=True, capture_output=True, cwd=str(ROOT))
    conf = work / "dosbox.conf"
    base = Path("/vmstore/claude/monopoly/dbx/dosbox.conf").read_text()
    conf.write_text(base.replace("mount c /vmstore/claude/monopoly/game",
                                 f"mount c {game}"))
    return str(conf)


def describe(path: Path) -> str:
    from verify_pixels import DecodeError, NotTextMode, decode_capture
    try:
        scr, _ = decode_capture(str(path))
    except NotTextMode:
        return "BOARD (320x200 graphics mode)"
    except DecodeError as exc:
        return f"undecodable ({exc})"
    lines = [ln.rstrip() for ln in scr.as_text().splitlines() if ln.strip()]
    return " | ".join(lines[:3])[:110] if lines else "(blank)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=lambda s: int(s, 0), default=0x2E024489)
    ap.add_argument("--poll", type=lambda s: int(s, 0), default=0)
    ap.add_argument("--keys")
    ap.add_argument("--samples", type=int, default=8)
    ap.add_argument("--work", default="/tmp/probe")
    args = ap.parse_args()

    work = Path(args.work)
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    capture.CONF = build(work, args.seed, args.poll, args.keys)
    dos = Dos()
    dos.start()
    time.sleep(5)

    boards = 0
    for i in range(args.samples):
        time.sleep(2.5)
        p = work / f"s{i:02d}.png"
        if not dos.snap(p):
            print(f"  {i}: no window")
            continue
        d = describe(p)
        if d.startswith("BOARD"):
            boards += 1
        print(f"  {i}: {d}")
    print(f"\npoll=0x{args.poll:X} keys={args.keys or 'default'} -> "
          f"{boards}/{args.samples} samples showed the board")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
