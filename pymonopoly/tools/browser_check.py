"""Drive the deployed HTML port in a real browser and report what breaks.

The renderer is pixel-checked against the Python build and the generator
against the original, but none of that exercises the interactive path: the
key handling, the async turn loop, or WebAudio starting on a gesture.  This
loads the real page in headless Chromium over the DevTools protocol, plays a
few turns, and reports console errors and screenshots.

    python3 tools/browser_check.py --url http://localhost:8000/
"""

from __future__ import annotations

import argparse
import os
import base64
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import websocket


class Chrome:
    def __init__(self, port: int = 9222, profile: str = os.environ.get("CHROME_PROFILE", "/tmp/chromedata")):
        self.port = port
        # A stray browser from an earlier run holds the debugging port and the
        # new one fails to bind it, so clear it first.  Match on the process
        # name, not the command line: the snap wrapper runs as "chrome", and
        # `pkill -f chromium` would also match this script's own invocation.
        for name in ("chrome", "chromium"):
            subprocess.run(["killall", name], capture_output=True)
        time.sleep(2)
        shutil.rmtree(profile, ignore_errors=True)
        Path(profile).mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(
            ["chromium-browser", "--headless=new", "--no-sandbox",
             "--disable-gpu", "--disable-dev-shm-usage",
             "--autoplay-policy=no-user-gesture-required",
             # Chromium refuses DevTools websockets whose Origin it does
             # not know, and websocket-client always sends one.
             "--remote-allow-origins=*",
             f"--remote-debugging-port={port}",
             f"--user-data-dir={profile}", "about:blank"],
            stdout=open("/tmp/chrome_drv.log", "wb"),
            stderr=subprocess.STDOUT)
        self.ws = None
        self.msg_id = 0
        self.events: list[dict] = []
        self._connect()

    def _connect(self, tries: int = 40) -> None:
        # DevTools binds IPv4 here, but try both rather than assume.
        for _ in range(tries):
            time.sleep(1)
            for host in ("127.0.0.1", "[::1]"):
                try:
                    raw = urllib.request.urlopen(
                        f"http://{host}:{self.port}/json", timeout=3).read()
                    tabs = [t for t in json.loads(raw) if t["type"] == "page"]
                    if tabs:
                        self.ws = websocket.create_connection(
                            tabs[0]["webSocketDebuggerUrl"], timeout=30,
                            max_size=64 * 1024 * 1024)
                        return
                except Exception:
                    continue
        raise RuntimeError("chromium never came up")

    def send(self, method: str, **params):
        self.msg_id += 1
        mid = self.msg_id
        self.ws.send(json.dumps({"id": mid, "method": method,
                                 "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                return msg.get("result", {})
            if "method" in msg:
                self.events.append(msg)

    def pump(self, seconds: float) -> None:
        """Let the page run, collecting events."""
        end = time.time() + seconds
        self.ws.settimeout(0.4)
        while time.time() < end:
            try:
                msg = json.loads(self.ws.recv())
                if "method" in msg:
                    self.events.append(msg)
            except Exception:
                pass
        self.ws.settimeout(30)

    def key(self, text: str, code: str = "", key: str = "") -> None:
        k = key or text
        base = {"key": k, "code": code or f"Key{text.upper()}",
                "windowsVirtualKeyCode": ord(text.upper()) if text else 13}
        self.send("Input.dispatchKeyEvent", type="keyDown", text=text, **base)
        self.send("Input.dispatchKeyEvent", type="keyUp", **base)
        time.sleep(0.12)

    def enter(self) -> None:
        for t in ("keyDown", "keyUp"):
            self.send("Input.dispatchKeyEvent", type=t, key="Enter",
                      code="Enter", windowsVirtualKeyCode=13, text="\r")
        time.sleep(0.2)

    def shot(self, path: Path) -> None:
        r = self.send("Page.captureScreenshot", format="png")
        path.write_bytes(base64.b64decode(r["data"]))

    def eval(self, expr: str):
        r = self.send("Runtime.evaluate", expression=expr, returnByValue=True)
        return r.get("result", {}).get("value")

    def close(self) -> None:
        try:
            self.ws.close()
        finally:
            self.proc.terminate()


def errors(events) -> list[str]:
    out = []
    for e in events:
        m = e.get("method")
        p = e.get("params", {})
        if m == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails", {})
            txt = d.get("exception", {}).get("description") or d.get("text")
            out.append(f"exception: {txt}")
        elif m == "Log.entryAdded" and p.get("entry", {}).get("level") == "error":
            out.append(f"log: {p['entry'].get('text')}")
        elif m == "Runtime.consoleAPICalled" and p.get("type") == "error":
            args = " ".join(str(a.get("value", a.get("description", "")))
                            for a in p.get("args", []))
            out.append(f"console: {args}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url",
                    default=os.environ.get("MONOPOLY_URL",
                                           "http://localhost:8000/"))
    ap.add_argument("--out", default="/tmp/browser")
    ap.add_argument("--turns", type=int, default=6)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    c = Chrome()
    try:
        c.send("Page.enable")
        c.send("Runtime.enable")
        c.send("Log.enable")
        c.send("Emulation.setDeviceMetricsOverride", width=1400, height=900,
               deviceScaleFactor=1, mobile=False)

        c.send("Page.navigate", url=args.url)
        c.pump(4)
        c.shot(out / "01-landing.png")
        print("landing page loaded")

        # start the game
        c.eval("document.getElementById('go').click()")
        c.pump(2)
        c.shot(out / "02-nameentry.png")
        print("clicked start")

        # two players, then a blank line
        for name in ("ANN", "BEN"):
            for ch in name.lower():
                c.key(ch)
            c.enter()
        c.enter()
        c.pump(3)
        c.shot(out / "03-board.png")
        print("names entered")

        # play: each turn needs a key to roll, then keys to clear panels
        for i in range(args.turns):
            for _ in range(9):
                c.enter()
                c.pump(0.5)
            c.shot(out / f"04-turn{i + 1}.png")
        print(f"played {args.turns} turns")

        # what does the page think happened?
        state = c.eval(
            "(() => { const c = document.getElementById('screen');"
            " return c ? c.width + 'x' + c.height : 'no canvas'; })()")
        blank = c.eval(
            "(() => { const c = document.getElementById('screen');"
            " const d = c.getContext('2d').getImageData(0,0,c.width,c.height).data;"
            " let lit = 0; for (let i = 0; i < d.length; i += 4)"
            "   if (d[i] || d[i+1] || d[i+2]) lit++;"
            " return lit; })()")
        print(f"canvas {state}, lit pixels {blank}")

        errs = errors(c.events)
        print(f"\n{len(errs)} error(s)")
        for e in errs[:20]:
            print("   " + e)
        return 1 if errs else 0
    finally:
        c.close()


if __name__ == "__main__":
    raise SystemExit(main())
