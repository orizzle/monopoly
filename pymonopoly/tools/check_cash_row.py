"""Measure the board's name and cash rows in the browser.

The layout is measured geometry, so a complaint about it is settled by
measuring what the page actually draws rather than by reading the constants
back.  This plays a few turns, screenshots the board, and reports which
character cells on the two cash rows have ink in them.

    python3 tools/check_cash_row.py --url http://localhost:8000/
"""

from __future__ import annotations

import argparse
import os
import base64
import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_check import Chrome                       # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url",
                    default=os.environ.get("MONOPOLY_URL",
                                           "http://localhost:8000/"))
    ap.add_argument("--names", nargs="*", default=["ALICE", "BOB"])
    ap.add_argument("--out", default="/tmp/cashrow.png")
    args = ap.parse_args()

    c = Chrome()
    try:
        c.send("Page.enable")
        c.send("Runtime.enable")
        c.send("Page.navigate", url=args.url)
        c.pump(4)
        c.eval("document.getElementById('go').click()")
        c.pump(2)
        for n in args.names:
            for ch in n.lower():
                c.key(ch)
            c.enter()
        c.enter()
        c.pump(4)

        # the board canvas, straight out of the page
        data = c.eval(
            "(() => { const el = document.getElementById('screen');"
            " return el ? el.toDataURL('image/png') : null; })()")
        if not data:
            print("no canvas")
            return 1
        from PIL import Image
        im = Image.open(io.BytesIO(base64.b64decode(data.split(",", 1)[1])))
        im.save(args.out)
        w, h = im.size
        print(f"canvas {w}x{h}")
        # the board is 320x200 logical; work out the scale from the width
        scale = w // 320 if w % 320 == 0 else None
        if scale is None:
            print("not a board frame (text mode?)")
            return 1
        rgb = im.convert("RGB")
        for label, row in (("names", 23), ("money", 24)):
            cols = []
            for col in range(40):
                box = rgb.crop((col * 8 * scale, row * 8 * scale,
                                (col + 1) * 8 * scale, (row + 1) * 8 * scale))
                if any(p != (0, 0, 0) for p in box.getdata()):
                    cols.append(col)
            print(f"  row {row} ({label}): {cols}")
        return 0
    finally:
        c.close()


if __name__ == "__main__":
    raise SystemExit(main())
