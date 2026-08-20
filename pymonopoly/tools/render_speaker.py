"""Render a speaker log into a WAV.

The MONO_LOGIO log is a complete record of what the PC speaker did: every
divisor written to the 8253 and every open and close of the gate, each with a
millisecond timestamp.  Rendering it directly gives cleaner audio than
recording the emulator's mixer -- no DC offset, no resampling -- and it is the
measurement itself rather than a copy of it.

    python3 tools/render_speaker.py run.log out.wav --offset 2000 --length 175
"""

from __future__ import annotations

import argparse
import math
import struct
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from speaker_tones import parse, tones          # noqa: E402

RATE = 44100
LEVEL = 9000


def render(events, offset_ms: float, length_s: float) -> bytes:
    import array

    n = int(length_s * RATE)
    buf = array.array("h", bytes(2 * n))
    for start, freq, dur in events:
        if freq <= 20:
            continue
        t0 = (start - offset_ms) / 1000.0
        if t0 + dur / 1000.0 < 0 or t0 > length_s:
            continue
        i0 = max(0, int(t0 * RATE))
        i1 = min(n, int((t0 + dur / 1000.0) * RATE))
        if i1 <= i0:
            i1 = min(n, i0 + 1)          # a click still needs one sample
        period = RATE / freq
        half = period / 2
        for i in range(i0, i1):
            # square wave, phase measured from the tone's own start
            buf[i] = LEVEL if ((i - i0) % period) < half else -LEVEL
    return buf.tobytes()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("out")
    ap.add_argument("--offset", type=float, default=0.0,
                    help="log time in ms that lines up with the video's start")
    ap.add_argument("--length", type=float, required=True, help="seconds")
    args = ap.parse_args()

    ev = tones(parse(args.log))
    data = render(ev, args.offset, args.length)
    with wave.open(args.out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(data)
    import array
    a = array.array("h"); a.frombytes(data)
    lit = sum(1 for v in a if v)
    print(f"{len(ev)} tones -> {args.out}, {args.length:.1f}s, "
          f"{lit * 100.0 / len(a):.1f}% sounding")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
