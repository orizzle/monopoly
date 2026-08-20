"""Turn a MONO_LOGIO speaker log into the tones the program actually played.

The 8253's channel 2 drives the PC speaker: OUT 43 selects the channel and
access mode, two OUT 42 bytes set the divisor, and bits 0-1 of port 61 gate
the output.  Frequency is 1193182 / divisor.  This reassembles those writes
into (start, frequency, duration) so a cue can be read off the hardware rather
than guessed from the source.

    python3 tools/speaker_tones.py io.log --gap 150
"""

from __future__ import annotations

import argparse
import re

PIT_HZ = 1193182


def parse(path):
    """Yield (ms, port, value) for each logged write."""
    pat = re.compile(r"^\s*([\d.]+)\s+OUT ([0-9A-Fa-f]{2}) ([0-9A-Fa-f]{2})")
    with open(path) as fh:
        for line in fh:
            m = pat.match(line)
            if m:
                yield float(m.group(1)), int(m.group(2), 16), int(m.group(3), 16)


def tones(events):
    """Reduce the write stream to sounding intervals."""
    out = []
    divisor = 0
    half = []            # pending divisor bytes
    on = False
    start = None
    freq = 0
    for ms, port, val in events:
        if port == 0x43:
            half = []
        elif port == 0x42:
            half.append(val)
            if len(half) == 2:
                divisor = half[0] | (half[1] << 8)
                half = []
                f = PIT_HZ / divisor if divisor else 0
                if on and start is not None and f != freq:
                    out.append((start, freq, ms - start))
                    start = ms
                freq = f
        elif port == 0x61:
            gate = (val & 3) == 3
            if gate and not on:
                on, start = True, ms
            elif not gate and on:
                if start is not None:
                    out.append((start, freq, ms - start))
                on, start = False, None
    return [t for t in out if t[1] > 0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--gap", type=float, default=150.0,
                    help="silence in ms that separates one cue from the next")
    ap.add_argument("--min-tones", type=int, default=2)
    args = ap.parse_args()

    ts = tones(parse(args.log))
    print(f"{len(ts)} sounding intervals\n")

    groups, cur = [], []
    for t in ts:
        if cur and t[0] - (cur[-1][0] + cur[-1][2]) > args.gap:
            groups.append(cur)
            cur = []
        cur.append(t)
    if cur:
        groups.append(cur)

    for g in groups:
        if len(g) < args.min_tones:
            continue
        span = (g[-1][0] + g[-1][2]) - g[0][0]
        freqs = [f for _, f, _ in g]
        durs = [d for _, _, d in g]
        print(f"--- cue at {g[0][0]:9.1f} ms: {len(g)} tones over {span:7.1f} ms")
        print(f"    freq {min(freqs):7.1f}..{max(freqs):7.1f} Hz, "
              f"step {sum(durs) / len(durs):5.2f} ms avg")
        head = ", ".join(f"{f:.0f}" for _, f, _ in g[:14])
        print(f"    first: {head}{' ...' if len(g) > 14 else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
