"""Measure how fast the browser port actually tumbles the dice.

A timing constant that resolves to undefined does not raise: setTimeout takes
it as zero and the animation runs flat out.  This loads the real page, wraps
setTimeout to record the delays the game asks for, lets a roll run, and
reports what it saw -- so the roll's frame rate is measured in the browser
rather than inferred from the source.

    python3 tools/check_roll_timing.py --url http://localhost:8000/
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_check import Chrome, errors            # noqa: E402

HOOK = """
window.__delays = [];
window.__stamps = [];
(() => {
  const orig = window.setTimeout;
  window.setTimeout = function (fn, ms) {
    window.__delays.push(ms);
    window.__stamps.push(performance.now());
    return orig.apply(this, arguments);
  };
})();
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url",
                    default=os.environ.get("MONOPOLY_URL",
                                           "http://localhost:8000/"))
    ap.add_argument("--roll-seconds", type=float, default=4.0)
    ap.add_argument("--expect", type=float, default=41.5)
    args = ap.parse_args()

    c = Chrome()
    try:
        c.send("Page.enable")
        c.send("Runtime.enable")
        c.send("Log.enable")
        c.send("Page.navigate", url=args.url)
        c.pump(4)
        c.eval("document.getElementById('go').click()")
        c.pump(2)
        for name in ("ANN", "BEN"):
            for ch in name.lower():
                c.key(ch)
            c.enter()
        c.enter()
        c.pump(3)

        # The dice are already tumbling once the board is up: hook the clock
        # and just watch, without pressing anything.
        c.eval(HOOK)
        time.sleep(args.roll_seconds)
        delays = c.eval("window.__delays.slice()") or []
        stamps = c.eval("window.__stamps.slice()") or []

        undef = sum(1 for d in delays if d is None)
        nums = [d for d in delays if isinstance(d, (int, float))]
        near = [d for d in nums if abs(d - args.expect) < 1]
        print(f"{len(delays)} timer calls while the dice tumbled")
        print(f"  undefined delays : {undef}")
        if nums:
            print(f"  distinct delays  : "
                  f"{sorted({round(float(d), 1) for d in nums})[:12]}")
            print(f"  at {args.expect} ms      : {len(near)}")
        # What matters is the interval the dice actually turn at, not the
        # number handed to setTimeout: the loop asks for the time remaining
        # to its next deadline, so the requested values are all smaller than
        # the beat and vary.  Judge the beat itself.
        median = None
        if len(stamps) > 6:
            gaps = [stamps[i + 1] - stamps[i] for i in range(len(stamps) - 1)]
            gaps = [g for g in gaps if g > 1]
            if gaps:
                median = statistics.median(gaps)
                print(f"  observed interval: median {median:.1f} ms"
                      f" over {len(gaps)} frames")
        errs = errors(c.events)
        print(f"{len(errs)} console error(s)")
        for e in errs[:6]:
            print("   " + e)
        ok = (undef == 0 and median is not None
              and abs(median - args.expect) <= 3)
        print("PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        c.close()


if __name__ == "__main__":
    raise SystemExit(main())
