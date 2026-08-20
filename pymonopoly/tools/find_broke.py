"""Find a game in which someone cannot pay what they owe.

The raise-money screen has a signature on the speaker: a 130 Hz tone held for
about 1.6 s, then a slow descent to 1 Hz.  Nothing else in the program sounds
remotely like it, so sweeping canned-input games and scanning their speaker
logs finds the moment without having to read any screens.  Canned input is
program-timed, so a rate that produces the state reproduces it exactly.

    python3 tools/find_broke.py --rates 8 12 16 --seconds 420
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from find_doubles import DOSBOX, CONF, DISPLAY, KEYS       # noqa: E402
from speaker_tones import parse, tones                     # noqa: E402


def broke_moments(log: Path):
    """Times (ms) where a ~130 Hz tone is held for more than a second."""
    out = []
    for start, freq, dur in tones(parse(str(log))):
        if 125 <= freq <= 135 and dur > 900:
            out.append((start, freq, dur))
    return out


def launch(rate: int, out: Path):
    log = out / f"broke{rate:03d}.log"
    log.unlink(missing_ok=True)
    env = {"DISPLAY": DISPLAY, "HOME": "/tmp", "PATH": "/usr/bin:/bin",
           "MONO_LOG": str(log), "MONO_KEYS": KEYS, "MONO_RATE": str(rate),
           "MONO_LOGIO": "1"}
    p = subprocess.Popen([DOSBOX, "-conf", CONF], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p, log


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rates", type=int, nargs="+", required=True)
    ap.add_argument("--seconds", type=int, default=420)
    ap.add_argument("--parallel", type=int, default=6)
    ap.add_argument("--out", default="/tmp/broke")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rates = list(args.rates)
    found = []
    while rates:
        batch, rates = rates[:args.parallel], rates[args.parallel:]
        procs = [(r,) + launch(r, out) for r in batch]
        time.sleep(args.seconds)
        for _r, p, _log in procs:
            p.terminate()
        time.sleep(2)
        for _r, p, _log in procs:
            if p.poll() is None:
                p.kill()
        for rate, _p, log in procs:
            hits = broke_moments(log) if log.exists() else []
            print(f"rate {rate:4d}: {len(hits)} raise-money moments" +
                  ("  <-- " + ", ".join(f"{h[0]/1000:.1f}s" for h in hits[:4])
                   if hits else ""), flush=True)
            if hits:
                found.append((rate, hits[0][0]))
    print("\nusable:", found)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
