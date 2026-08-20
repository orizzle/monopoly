"""CGA text-mode screen -- the exact display surface the 1985 game drew on.

Monopoly 5.1 runs in 80x25 colour text mode.  Every screen it draws is a grid
of (character, attribute) cells; there is no bitmap anywhere in the program.
So an exact recreation is possible: reproduce the cell grid, then render it
through the same 8x8 CGA ROM font and the same 16-colour palette the hardware
used.

The font below was extracted from the running emulator rather than typed in by
hand.  A 24-byte COM program filled video memory at B800:0000 with characters
0..255; the resulting screen was captured and each 8x16 cell de-doubled back
to its native 8x8 bitmap.  tools/verify_pixels.py closes the loop, re-rendering
captured game screens and diffing them against the emulator's own output.

Screen coordinates follow Turbo Pascal 3, which is what the original called:
GotoXY is 1-based with (1, 1) at the top left.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image

import base64

COLS = 80
ROWS = 25
CELL_W = 8
CELL_H = 8

# Scanlines the text cursor occupies within a cell, and how fast it blinks.
# The two rows are measured; the rate is the CGA hardware default, which the
# emulator draws as a steady bar in a still capture.
CURSOR_ROWS = (6, 7)
CURSOR_BLINK_MS = 266

# --------------------------------------------------------------------------
# The 16 CGA text-mode colours in hardware attribute order.  Turbo Pascal 3
# exposed these under the names below, and the source recovered from
# MONOGRAF.GRA uses them directly -- TextColor(LightCyan), TextColor(red).
# --------------------------------------------------------------------------

PALETTE: tuple[tuple[int, int, int], ...] = (
    (0x00, 0x00, 0x00),  #  0 Black
    (0x00, 0x00, 0xAA),  #  1 Blue
    (0x00, 0xAA, 0x00),  #  2 Green
    (0x00, 0xAA, 0xAA),  #  3 Cyan
    (0xAA, 0x00, 0x00),  #  4 Red
    (0xAA, 0x00, 0xAA),  #  5 Magenta
    (0xAA, 0x55, 0x00),  #  6 Brown
    (0xAA, 0xAA, 0xAA),  #  7 LightGray
    (0x55, 0x55, 0x55),  #  8 DarkGray
    (0x55, 0x55, 0xFF),  #  9 LightBlue
    (0x55, 0xFF, 0x55),  # 10 LightGreen
    (0x55, 0xFF, 0xFF),  # 11 LightCyan
    (0xFF, 0x55, 0x55),  # 12 LightRed
    (0xFF, 0x55, 0xFF),  # 13 LightMagenta
    (0xFF, 0xFF, 0x55),  # 14 Yellow
    (0xFF, 0xFF, 0xFF),  # 15 White
)

# The original disables the blink attribute, which turns the top attribute bit
# from "blink" into the background's intensity bit and makes all sixteen
# colours available as backgrounds.  Its Chance and Community Chest cards are
# drawn on a white background, which a three-bit background cannot express --
# found by auditing captured screens against this renderer.
BLINK_DISABLED = True

BLACK, BLUE, GREEN, CYAN, RED, MAGENTA, BROWN, LIGHTGRAY = range(8)
DARKGRAY, LIGHTBLUE, LIGHTGREEN, LIGHTCYAN = 8, 9, 10, 11
LIGHTRED, LIGHTMAGENTA, YELLOW, WHITE = 12, 13, 14, 15

COLOR_NAMES = (
    "Black", "Blue", "Green", "Cyan", "Red", "Magenta", "Brown", "LightGray",
    "DarkGray", "LightBlue", "LightGreen", "LightCyan", "LightRed",
    "LightMagenta", "Yellow", "White",
)

# --------------------------------------------------------------------------
# IBM CGA 8x8 ROM font: 256 glyphs x 8 rows, one byte per row,
# MSB = leftmost pixel.
# --------------------------------------------------------------------------

_FONT_B64 = (
    "AAAAAAAAAAB+gaWBvZmBfn7/2//D5/9+bP7+/nw4EAAQOHz+fDgQADh8OP7+fDh8EBA4fP58"
    "OHwAABg8PBgAAP//58PD5///ADxmQkJmPAD/w5m9vZnD/w8HD33MzMx4PGZmZjwYfhg/Mz8w"
    "MHDw4H9jf2NjZ+bAmVo85+c8WpmA4Pj++OCAAAIOPv4+DgIAGDx+GBh+PBhmZmZmZgBmAH/b"
    "23sbGxsAPmM4bGw4zHgAAAAAfn5+ABg8fhh+PBj/GDx+GBgYGAAYGBgYfjwYAAAYDP4MGAAA"
    "ADBg/mAwAAAAAMDAwP4AAAAkZv9mJAAAABg8fv//AAAA//9+PBgAAAAAAAAAAAAAMHh4MDAA"
    "MABsbGwAAAAAAGxs/mz+bGwAMHzAeAz4MAAAxswYMGbGADhsOHbczHYAYGDAAAAAAAAYMGBg"
    "YDAYAGAwGBgYMGAAAGY8/zxmAAAAMDD8MDAAAAAAAAAAMDBgAAAA/AAAAAAAAAAAADAwAAYM"
    "GDBgwIAAfMbO3vbmfAAwcDAwMDD8AHjMDDhgzPwAeMwMOAzMeAAcPGzM/gweAPzA+AwMzHgA"
    "OGDA+MzMeAD8zAwYMDAwAHjMzHjMzHgAeMzMfAwYcAAAMDAAADAwAAAwMAAAMDBgGDBgwGAw"
    "GAAAAPwAAPwAAGAwGAwYMGAAeMwMGDAAMAB8xt7e3sB4ADB4zMz8zMwA/GZmfGZm/AA8ZsDA"
    "wGY8APhsZmZmbPgA/mJoeGhi/gD+Ymh4aGDwADxmwMDOZj4AzMzM/MzMzAB4MDAwMDB4AB4M"
    "DAzMzHgA5mZseGxm5gDwYGBgYmb+AMbu/v7WxsYAxub23s7GxgA4bMbGxmw4APxmZnxgYPAA"
    "eMzMzNx4HAD8ZmZ8bGbmAHjM4HAczHgA/LQwMDAweADMzMzMzMz8AMzMzMzMeDAAxsbG1v7u"
    "xgDGxmw4OGzGAMzMzHgwMHgA/saMGDJm/gB4YGBgYGB4AMBgMBgMBgIAeBgYGBgYeAAQOGzG"
    "AAAAAAAAAAAAAAD/MDAYAAAAAAAAAHgMfMx2AOBgYHxmZtwAAAB4zMDMeAAcDAx8zMx2AAAA"
    "eMz8wHgAOGxg8GBg8AAAAHbMzHwM+OBgbHZmZuYAMABwMDAweAAMAAwMDMzMeOBgZmx4bOYA"
    "cDAwMDAweAAAAMz+/tbGAAAA+MzMzMwAAAB4zMzMeAAAANxmZnxg8AAAdszMfAweAADcdmZg"
    "8AAAAHzAeAz4ABAwfDAwNBgAAADMzMzMdgAAAMzMzHgwAAAAxtb+/mwAAADGbDhsxgAAAMzM"
    "zHwM+AAA/JgwZPwAHDAw4DAwHAAYGBgAGBgYAOAwMBwwMOAAdtwAAAAAAAAAEDhsxsb+AHjM"
    "wMx4GAx4AMwAzMzMfgAcAHjM/MB4AH7DPAY+Zj8AzAB4DHzMfgDgAHgMfMx+ADAweAx8zH4A"
    "AAB4wMB4DDh+wzxmfmA8AMwAeMz8wHgA4AB4zPzAeADMAHAwMDB4AHzGOBgYGDwA4ABwMDAw"
    "eADGOGzG/sbGADAwAHjM/MwAHAD8YHhg/AAAAH8Mf8x/AD5szP7MzM4AeMwAeMzMeAAAzAB4"
    "zMx4AADgAHjMzHgAeMwAzMzMfgAA4ADMzMx+AADMAMzMfAz4wxg8ZmY8GADMAMzMzMx4ABgY"
    "fsDAfhgYOGxk8GDm/ADMzHj8MPwwMPjMzPrGz8bHDhsYPBgY2HAcAHgMfMx+ADgAcDAwMHgA"
    "ABwAeMzMeAAAHADMzMx+AAD4APjMzMwA/ADM7PzczAA8bGw+AH4AADhsbDgAfAAAMAAwYMDM"
    "eAAAAAD8wMAAAAAAAPwMDAAAw8bM3jNmzA/DxszbN2/PAxgYABgYGBgAADNmzGYzAAAAzGYz"
    "ZswAACKIIogiiCKIVapVqlWqVarbd9vu23fb7hgYGBgYGBgYGBgYGPgYGBgYGPgY+BgYGDY2"
    "Njb2NjY2AAAAAP42NjYAAPgY+BgYGDY29gb2NjY2NjY2NjY2NjYAAP4G9jY2NjY29gb+AAAA"
    "NjY2Nv4AAAAYGPgY+AAAAAAAAAD4GBgYGBgYGB8AAAAYGBgY/wAAAAAAAAD/GBgYGBgYGB8Y"
    "GBgAAAAA/wAAABgYGBj/GBgYGBgfGB8YGBg2NjY2NzY2NjY2NzA/AAAAAAA/MDc2NjY2NvcA"
    "/wAAAAAA/wD3NjY2NjY3MDc2NjYAAP8A/wAAADY29wD3NjY2GBj/AP8AAAA2NjY2/wAAAAAA"
    "/wD/GBgYAAAAAP82NjY2NjY2PwAAABgYHxgfAAAAAAAfGB8YGBgAAAAAPzY2NjY2Njb/NjY2"
    "GBj/GP8YGBgYGBgY+AAAAAAAAAAfGBgY//////////8AAAAA//////Dw8PDw8PDwDw8PDw8P"
    "Dw//////AAAAAAAAdtzI3HYAAHjM+Mz4wMAA/MzAwMDAAAD+bGxsbGwA/MxgMGDM/AAAAH7Y"
    "2NhwAABmZmZmfGDAAHbcGBgYGAD8MHjMzHgw/Dhsxv7GbDgAOGzGxmxs7gAcMBh8zMx4AAAA"
    "ftvbfgAABgx+29t+YMA4YMD4wGA4AHjMzMzMzMwAAPwA/AD8AAAwMPwwMAD8AGAwGDBgAPwA"
    "GDBgMBgA/AAOGxsYGBgYGBgYGBgY2NhwMDAA/AAwMAAAdtwAdtwAADhsbDgAAAAAAAAAGBgA"
    "AAAAAAAAGAAAAA8MDAzsbDwceGxsbGwAAABwGDBgeAAAAAAAPDw8PAAAAAAAAAAAAAA="
)

_raw = base64.b64decode("".join(_FONT_B64))
assert len(_raw) == 2048, "CGA font must be 256 glyphs x 8 rows"
FONT: tuple[tuple[int, ...], ...] = tuple(
    tuple(_raw[n * 8:(n + 1) * 8]) for n in range(256)
)
del _raw


# --------------------------------------------------------------------------
# The screen itself
# --------------------------------------------------------------------------


class Screen:
    """An 80x25 cell grid with the Turbo Pascal 3 CRT primitives on top.

    The original drew everything through GotoXY / TextColor / TextBackground /
    Write / ClrEol / ClrScr, so those are the operations modelled here.  Cells
    hold a character code (0..255, interpreted in the CGA ROM font, not
    Unicode) and an attribute byte: low nibble foreground, high nibble
    background.
    """

    __slots__ = ("chars", "attrs", "x", "y", "textattr", "_win", "cursor")

    def __init__(self) -> None:
        # (column, row) of the hardware text cursor, or None.  The original
        # relies on the CRTC's own cursor for text entry rather than printing
        # a character, so it is drawn at render time, not stored in a cell.
        self.cursor: tuple[int, int] | None = None
        self.chars = bytearray(COLS * ROWS)
        self.attrs = bytearray(COLS * ROWS)
        self.x = 1
        self.y = 1
        self.textattr = LIGHTGRAY
        self._win = (1, 1, COLS, ROWS)
        self.clrscr()

    # -- colour ------------------------------------------------------------

    def textcolor(self, c: int) -> None:
        self.textattr = (self.textattr & 0xF0) | (c & 0x0F)

    def textbackground(self, c: int) -> None:
        self.textattr = (self.textattr & 0x0F) | ((c & 0x0F) << 4)

    def set_attr(self, fg: int, bg: int) -> None:
        self.textattr = (fg & 0x0F) | ((bg & 0x0F) << 4)

    # -- cursor ------------------------------------------------------------

    def gotoxy(self, x: int, y: int) -> None:
        """1-based, relative to the active window, exactly as TP3's GotoXY."""
        left, top, right, bottom = self._win
        self.x = min(max(x, 1), right - left + 1)
        self.y = min(max(y, 1), bottom - top + 1)

    def window(self, left: int, top: int, right: int, bottom: int) -> None:
        self._win = (left, top, right, bottom)
        self.x = self.y = 1

    def full_window(self) -> None:
        self.window(1, 1, COLS, ROWS)

    @property
    def abs_x(self) -> int:
        return self._win[0] + self.x - 1

    @property
    def abs_y(self) -> int:
        return self._win[1] + self.y - 1

    # -- clearing ----------------------------------------------------------

    def clrscr(self) -> None:
        """Clear the active window to the current background colour."""
        left, top, right, bottom = self._win
        blank = self.textattr & 0xF0
        for row in range(top, bottom + 1):
            base = (row - 1) * COLS
            for col in range(left, right + 1):
                self.chars[base + col - 1] = 0x20
                self.attrs[base + col - 1] = blank
        self.x = self.y = 1

    def clreol(self) -> None:
        left, top, right, bottom = self._win
        row = self.abs_y
        base = (row - 1) * COLS
        blank = self.textattr & 0xF0
        for col in range(self.abs_x, right + 1):
            self.chars[base + col - 1] = 0x20
            self.attrs[base + col - 1] = blank

    # -- output ------------------------------------------------------------

    def putcell(self, x: int, y: int, ch: int, attr: int) -> None:
        """Write one cell at absolute 1-based coordinates."""
        if 1 <= x <= COLS and 1 <= y <= ROWS:
            i = (y - 1) * COLS + (x - 1)
            self.chars[i] = ch & 0xFF
            self.attrs[i] = attr & 0xFF

    def write(self, text: str) -> None:
        """Write at the cursor, wrapping inside the active window."""
        left, top, right, bottom = self._win
        for ch in text:
            if ch == "\n":
                self.x = 1
                self.y += 1
                continue
            if ch == "\r":
                self.x = 1
                continue
            self.putcell(self.abs_x, self.abs_y, _encode(ch), self.textattr)
            self.x += 1
            if self.abs_x > right:
                self.x = 1
                self.y += 1
            if self.abs_y > bottom:
                self.y = bottom - top + 1

    def writeln(self, text: str = "") -> None:
        self.write(text)
        self.x = 1
        self.y += 1

    def write_at(self, x: int, y: int, text: str,
                 fg: int | None = None, bg: int | None = None) -> None:
        """The common case: position, colour, and write in one call."""
        saved = self.textattr
        if fg is not None or bg is not None:
            self.set_attr(self.textattr & 0x0F if fg is None else fg,
                          (self.textattr >> 4) & 0x0F if bg is None else bg)
        self.gotoxy(x - self._win[0] + 1, y - self._win[1] + 1)
        self.write(text)
        self.textattr = saved

    def fill(self, x: int, y: int, w: int, h: int,
             ch: int = 0x20, attr: int | None = None) -> None:
        """Paint a solid rectangle -- how the original drew its panels."""
        a = self.textattr if attr is None else attr
        for row in range(y, y + h):
            for col in range(x, x + w):
                self.putcell(col, row, ch, a)

    # -- readback ----------------------------------------------------------

    def cell(self, x: int, y: int) -> tuple[int, int]:
        i = (y - 1) * COLS + (x - 1)
        return self.chars[i], self.attrs[i]

    def text_row(self, y: int) -> str:
        base = (y - 1) * COLS
        return "".join(_decode(c) for c in self.chars[base:base + COLS])

    def as_text(self) -> str:
        return "\n".join(self.text_row(y).rstrip() for y in range(1, ROWS + 1))

    # -- rendering ---------------------------------------------------------

    def render(self, scanline_double: bool = True) -> "Image":
        """Render to a PIL image: 640x400 doubled (as DOSBox shows CGA text),
        or 640x200 native."""
        from PIL import Image

        w, h = COLS * CELL_W, ROWS * CELL_H
        buf = bytearray(w * h * 3)
        pal = PALETTE
        font = FONT
        for cy in range(ROWS):
            for cx in range(COLS):
                i = cy * COLS + cx
                glyph = font[self.chars[i]]
                attr = self.attrs[i]
                fg = pal[attr & 0x0F]
                bg = pal[(attr >> 4) & 0x0F]
                px = cx * CELL_W
                for gy in range(CELL_H):
                    bits = glyph[gy]
                    o = ((cy * CELL_H + gy) * w + px) * 3
                    for gx in range(CELL_W):
                        r, g, b = fg if bits & (0x80 >> gx) else bg
                        buf[o] = r
                        buf[o + 1] = g
                        buf[o + 2] = b
                        o += 3
        if self.cursor is not None:
            self._paint_cursor(buf, w)
        img = Image.frombytes("RGB", (w, h), bytes(buf))
        if scanline_double:
            img = img.resize((w, h * 2), Image.NEAREST)
        return img

    def _paint_cursor(self, buf: bytearray, w: int) -> None:
        """A two-scanline underline across the cell, in its foreground colour.

        Measured from a capture of the original's name prompt: the bar covers
        the full eight pixels of the cell and occupies rows 6 and 7.
        """
        cx, cy = self.cursor
        if not (1 <= cx <= COLS and 1 <= cy <= ROWS):
            return
        attr = self.attrs[(cy - 1) * COLS + (cx - 1)]
        r, g, b = PALETTE[attr & 0x0F]
        for gy in CURSOR_ROWS:
            o = (((cy - 1) * CELL_H + gy) * w + (cx - 1) * CELL_W) * 3
            for _ in range(CELL_W):
                buf[o], buf[o + 1], buf[o + 2] = r, g, b
                o += 3

    def save_png(self, path: str, scanline_double: bool = True) -> None:
        self.render(scanline_double).save(path)


# --------------------------------------------------------------------------
# Code page 437 <-> str
#
# The font is indexed by CP437 code point, not Unicode.  Text written by the
# game is plain ASCII, but the box and block characters it draws panels with
# live in the high half, so both directions are needed.
# --------------------------------------------------------------------------

_CP437_HIGH = (
    "Çüéâäàåçêëèï"
    "îìÄÅÉæÆôöòûù"
    "ÿÖÜ¢£¥₧ƒáíóú"
    "ñÑªº¿⌐¬½¼¡«»"
    "░▒▓│┤╡╢╖╕╣║╗"
    "╝╜╛┐└┴┬├─┼╞╟"
    "╚╔╩╦╠═╬╧╨╤╥╙"
    "╘╒╓╫╪┘┌█▄▌▐▀"
    "αßΓπΣσµτΦΘΩδ"
    "∞φε∩≡±≥≤⌠⌡÷≈"
    "°∙·√ⁿ²■ "
)

_TO_CP437 = {c: 128 + i for i, c in enumerate(_CP437_HIGH)}
_FROM_CP437 = {128 + i: c for i, c in enumerate(_CP437_HIGH)}


def _encode(ch: str) -> int:
    o = ord(ch)
    if 32 <= o < 127:
        return o
    if ch in _TO_CP437:
        return _TO_CP437[ch]
    return o if o < 256 else 0x3F  # '?'


def _decode(code: int) -> str:
    if 32 <= code < 127:
        return chr(code)
    if code in _FROM_CP437:
        return _FROM_CP437[code]
    return " " if code in (0, 255) else "."


# Block and box characters the panels are built from, by CP437 code.
BLOCK_FULL = 219
BLOCK_LOWER = 220
BLOCK_LEFT = 221
BLOCK_RIGHT = 222
BLOCK_UPPER = 223
SHADE_LIGHT = 176
SHADE_MEDIUM = 177
SHADE_DARK = 178
