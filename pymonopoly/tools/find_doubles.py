"""Search the original for a game in which one player throws three doubles.

The tumble spends the generator until a key stops it, so what a player throws
depends on when the key lands.  Canned input makes that reproducible: keys are
offered every MONO_RATE polls of the BIOS keyboard, which is program time, not
wall-clock, so the same rate always produces the same game.  This sweeps the
rate, watches the two dice words in the data segment, and reports any run
where the same player throws three doubles in a row.

    python3 tools/find_doubles.py --rates 24 32 40 --seconds 90
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import time
from pathlib import Path

# Where the instrumented DOSBox build and its config live.  Set MONO_SCRATCH
# to wherever you built it; these tools drive that build, not a stock one.
SCRATCH = os.environ.get("MONO_SCRATCH", "/tmp/monopoly-scratch")
DOSBOX = f"{SCRATCH}/dbxsrc/dosbox-0.74-3/src/dosbox"
CONF = f"{SCRATCH}/dosbox-sound.conf"
DISPLAY = ":99"

# Ply[] dice, DS:0x0264 and DS:0x0266 with DS=0x10DC.
DICE_ADDR = 0x11024

# Two single-letter players.  The stream cycles forever, so every byte in it
# is eventually typed at some prompt; P and G are the two that are always
# safe -- Purchase and Go on -- and P doubles as "Pay $50" in jail.  Longer
# names would put letters like A (auction) and T (title deed) into prompts
# that then wait for input nobody is going to type.
KEYS = "500D470D0D" + "0D500D470D460D430D" * 3


def roll_pairs(log: Path):
    """The dice as the game writes them, in order."""
    out = []
    # The dice go out as whole words, so the line is W16, not WRITE8.
    pat = re.compile(r"W16 ([0-9A-F]{6}) = ([0-9A-F]{4})")
    lo = None
    for line in log.read_text(errors="replace").splitlines():
        m = pat.search(line)
        if not m:
            continue
        addr, val = int(m.group(1), 16), int(m.group(2), 16)
        if addr == DICE_ADDR:
            lo = val
        elif addr == DICE_ADDR + 2 and lo is not None:
            out.append((lo, val))
            lo = None
    # The first pair is written before play starts, when the record is set
    # up; it is not a throw.
    return out[1:]


def triples(pairs):
    """Indices where three consecutive throws are all doubles."""
    hits = []
    for i in range(len(pairs) - 2):
        if all(a == b and 1 <= a <= 6 for a, b in pairs[i:i + 3]):
            hits.append(i)
    return hits


def launch(rate: int, out: Path):
    """Start one emulator on its own log.  Nothing is killed: the runs are
    independent and several are in flight at once."""
    log = out / f"rate{rate:03d}.log"
    log.unlink(missing_ok=True)
    env = {"DISPLAY": DISPLAY, "HOME": "/tmp", "PATH": "/usr/bin:/bin",
           "MONO_LOG": str(log), "MONO_KEYS": KEYS, "MONO_RATE": str(rate),
           "MONO_WATCH": hex(DICE_ADDR), "MONO_WATCHLEN": "4"}
    p = subprocess.Popen([DOSBOX, "-conf", CONF], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p, log


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rates", type=int, nargs="+", required=True)
    ap.add_argument("--seconds", type=int, default=90)
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--early", type=int, default=0,
                    help="only report triples starting at or before this throw")
    ap.add_argument("--out", default=f"{SCRATCH}/doubles")
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
            pairs = roll_pairs(log) if log.exists() else []
            hit = [i for i in triples(pairs)
                   if not args.early or i <= args.early]
            shown = " ".join(f"{a}{b}" for a, b in pairs[:20])
            print(f"rate {rate:4d}: {len(pairs):3d} throws  {shown}"
                  f"{' ...' if len(pairs) > 20 else ''}", flush=True)
            if hit:
                print(f"    *** three doubles from throw {hit[0]} ***",
                      flush=True)
                found.append((rate, hit[0]))
    if found:
        print("\nusable runs:", found)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
