"""Presenting a cga.Screen to a real terminal, and reading keys back.

The game's drawing code targets a cga.Screen -- an 80x25 grid of characters
and attributes -- and nothing else.  That keeps one set of screen code serving
two purposes: this module paints it into a terminal so the game is playable,
and cga.Screen.render() rasterises the identical grid through the CGA ROM font
so it can be diffed against the emulator.

Colour is emitted as 24-bit ANSI using the exact CGA palette rather than the
terminal's own sixteen colours, which are usually a themed approximation.
`--ansi16` falls back for terminals that cannot do truecolor.
"""

from __future__ import annotations

import os
import sys
from typing import Iterable

from . import cga

# CGA attribute index -> classic ANSI SGR codes, for the fallback path.
_ANSI16_FG = (30, 34, 32, 36, 31, 35, 33, 37, 90, 94, 92, 96, 91, 95, 93, 97)
_ANSI16_BG = (40, 44, 42, 46, 41, 45, 43, 47)

ESC = "\x1b"


class Terminal:
    """Raw-mode terminal I/O.  Falls back to line mode where tty control is
    unavailable (pipes, CI), so the game still runs headless."""

    def __init__(self, truecolor: bool = True) -> None:
        self.truecolor = truecolor
        self._fd = None
        self._saved = None
        self._raw_ok = False
        self._last: list[tuple[int, int]] | None = None

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> "Terminal":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def open(self) -> None:
        try:
            import termios
            import tty

            self._fd = sys.stdin.fileno()
            self._saved = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
            self._raw_ok = True
        except Exception:
            self._raw_ok = False
        sys.stdout.write(ESC + "[?25l" + ESC + "[2J")  # hide cursor, clear
        sys.stdout.flush()

    def close(self) -> None:
        if self._raw_ok and self._saved is not None:
            import termios

            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)
        sys.stdout.write(ESC + "[?25h" + ESC + "[0m" + ESC + "[2J" + ESC + "[H")
        sys.stdout.flush()

    # -- painting ----------------------------------------------------------

    def _sgr(self, attr: int) -> str:
        fg = attr & 0x0F
        bg = (attr >> 4) & 0x07
        if self.truecolor:
            fr, fgc, fb = cga.PALETTE[fg]
            br, bgc, bb = cga.PALETTE[bg]
            return f"{ESC}[38;2;{fr};{fgc};{fb};48;2;{br};{bgc};{bb}m"
        return f"{ESC}[{_ANSI16_FG[fg]};{_ANSI16_BG[bg]}m"

    def paint(self, scr: cga.Screen, force: bool = False) -> None:
        """Draw the screen, emitting only rows that changed since last time."""
        cells = list(zip(scr.chars, scr.attrs))
        out: list[str] = []
        for y in range(cga.ROWS):
            row = cells[y * cga.COLS:(y + 1) * cga.COLS]
            if not force and self._last is not None:
                prev = self._last[y * cga.COLS:(y + 1) * cga.COLS]
                if prev == row:
                    continue
            out.append(f"{ESC}[{y + 1};1H")
            attr = None
            for ch, a in row:
                if a != attr:
                    out.append(self._sgr(a))
                    attr = a
                out.append(cga._decode(ch))
            out.append(f"{ESC}[0m")
        if out:
            sys.stdout.write("".join(out))
            sys.stdout.flush()
        self._last = cells

    def invalidate(self) -> None:
        self._last = None

    # -- the text cursor ---------------------------------------------------

    def show_cursor(self, col: int, row: int) -> None:
        """Park the terminal cursor on a cell and reveal it.

        Terminals blink their own cursor, which is what the CGA hardware did,
        so no blink loop is needed here.
        """
        sys.stdout.write(f"{ESC}[{row};{col}H{ESC}[?25h")
        sys.stdout.flush()

    def hide_cursor(self) -> None:
        sys.stdout.write(f"{ESC}[?25l")
        sys.stdout.flush()

    # -- input -------------------------------------------------------------

    def can_poll(self) -> bool:
        """Whether key_ready() means anything on this terminal."""
        return self._raw_ok

    def key_ready(self) -> bool:
        """True if a keystroke is already waiting.

        The dice tumble until the player presses a key, so the roll loop has
        to ask "has one arrived yet" without blocking -- the same question
        the original asks through the runtime's KeyPressed.
        """
        if not self._raw_ok:
            return False
        import select

        return bool(select.select([sys.stdin], [], [], 0)[0])

    def read_key(self) -> str:
        """One keypress.  Returns a single character, or a name for the
        function and arrow keys the game listens for."""
        if not self._raw_ok:
            line = sys.stdin.readline()
            if not line:
                # Piped input ran out.  Signal it rather than spinning on a
                # key the caller will keep rejecting.
                raise EOFError("no more input")
            return line[0] if line.strip() else "\r"

        ch = sys.stdin.read(1)
        if ch != ESC:
            return ch
        # Escape sequence: read the rest without blocking forever.
        seq = ch
        import select

        while select.select([sys.stdin], [], [], 0.05)[0]:
            seq += sys.stdin.read(1)
            if len(seq) > 6:
                break
        return _KEYNAMES.get(seq, seq if len(seq) > 1 else "\x1b")

    def read_line(self, scr: cga.Screen, x: int, y: int, width: int,
                  attr: int, initial: str = "") -> str | None:
        """Read text at a screen position, echoing into the grid.

        Returns None if the player pressed F2 -- the original's save/load key,
        which is live during name entry.
        """
        buf = list(initial)
        while True:
            shown = ("".join(buf) + " " * width)[:width]
            for i, c in enumerate(shown):
                scr.putcell(x + i, y, cga._encode(c), attr)

            # The original uses the CRTC's own cursor here rather than
            # printing a character, so do the same: park the terminal's
            # cursor on the cell and let it blink at its native rate.
            col = x + min(len(buf), width - 1)
            scr.cursor = (col, y)
            self.paint(scr)
            self.show_cursor(col, y)

            try:
                key = self.read_key()
            except EOFError:
                scr.cursor = None
                self.hide_cursor()
                return "".join(buf).strip()
            if key in ("\r", "\n"):
                for i, c in enumerate(("".join(buf) + " " * width)[:width]):
                    scr.putcell(x + i, y, cga._encode(c), attr)
                scr.cursor = None
                self.hide_cursor()
                return "".join(buf).strip()
            if key == "F2":
                scr.cursor = None
                self.hide_cursor()
                return None
            if key in ("\x7f", "\b"):
                if buf:
                    buf.pop()
            elif key == "\x03":
                raise KeyboardInterrupt
            elif len(key) == 1 and 32 <= ord(key) < 127 and len(buf) < width:
                buf.append(key)


_KEYNAMES = {
    ESC + "OP": "F1", ESC + "OQ": "F2", ESC + "OR": "F3", ESC + "OS": "F4",
    ESC + "[11~": "F1", ESC + "[12~": "F2",
    ESC + "[A": "UP", ESC + "[B": "DOWN", ESC + "[C": "RIGHT", ESC + "[D": "LEFT",
}


class NullTerminal(Terminal):
    """A Terminal that draws nothing and replays a scripted key sequence.

    Used by the tests to drive whole games without a tty.
    """

    def __init__(self, keys: Iterable[str] = ()) -> None:
        super().__init__(truecolor=False)
        self.keys = list(keys)
        self.frames: list[cga.Screen] = []

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def paint(self, scr: cga.Screen, force: bool = False) -> None:
        pass

    def show_cursor(self, col: int, row: int) -> None:
        pass

    def hide_cursor(self) -> None:
        pass

    def can_poll(self) -> bool:
        return False

    def key_ready(self) -> bool:
        return False

    def read_key(self) -> str:
        return self.keys.pop(0) if self.keys else "\r"

    def read_line(self, scr, x, y, width, attr, initial=""):
        out = []
        while self.keys:
            k = self.keys.pop(0)
            if k in ("\r", "\n"):
                break
            if k == "F2":
                return None
            out.append(k)
        return "".join(out).strip()


def supports_truecolor() -> bool:
    return os.environ.get("COLORTERM", "") in ("truecolor", "24bit")
