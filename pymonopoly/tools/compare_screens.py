"""Diff the port's screens against captures of the 1985 program.

verify_pixels.py calibrates the renderer -- it proves that a cell grid decoded
from a capture renders back to identical pixels.  This tool is the actual test
of the port: it draws a screen from monopoly/screens.py and diffs the result
against what DOSBox produced, cell by cell and pixel by pixel.

A mismatch prints the offending cells so the layout can be corrected, rather
than just a percentage.

Usage:
    python3 tools/compare_screens.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image

from monopoly import cga, screens
from verify_pixels import decode_capture

SHOTS = Path(__file__).resolve().parents[2] / "shots"


def build_title_1() -> cga.Screen:
    scr = cga.Screen()
    screens.draw_title(scr, ["alice"])
    return scr


def build_title_2() -> cga.Screen:
    scr = cga.Screen()
    screens.draw_title(scr, ["alice", "bob"])
    return scr


def _two_players():
    from monopoly.state import GameState

    st = GameState.new_game(["alice", "bob"], seed=1)
    return st


def build_offer_purchase() -> cga.Screen:
    """shots/11-bob-land.png: alice has landed on unowned St. James Place."""
    st = _two_players()
    st.players[0].position = 16
    scr = cga.Screen()
    screens.draw_turn_screen(
        scr, st, "alice's turn",
        ["St. James Place isn't owned."],
        ["Want to ~Purchase it from the bank?",
         "     or ~Auction it off?",
         "do some ~Business first?",
         "     or ~Go on with the game?"],
        deed=16)
    return scr


def build_purchased() -> cga.Screen:
    """shots/12-purchased.png: alice has just bought St. James Place."""
    st = _two_players()
    st.players[0].position = 16
    st.players[0].cash = 1320
    st.props[16].owner = 0
    scr = cga.Screen()
    screens.draw_turn_screen(
        scr, st, "alice's turn",
        ["St. James Place purchased."],
        None, deed=16)
    screens.prompt_panel(scr, ["Want to do some ~Business?",
                               "    or ready to ~Go on?"])
    return scr


def _mid_game(cash, holdings):
    """A state with given cash and {player: [board positions]}."""
    from monopoly.state import GameState

    st = GameState.new_game(["alice", "bob"], seed=1)
    for i, c in enumerate(cash):
        st.players[i].cash = c
    for who, positions in holdings.items():
        for pos in positions:
            st.props[pos].owner = who
    return st


OFFER = ["Want to ~Purchase it from the bank?",
         "     or ~Auction it off?",
         "do some ~Business first?",
         "     or ~Go on with the game?"]

BUSINESS = ["Want to do some ~Business?", "    or ready to ~Go on?"]


def build_railroad_card() -> cga.Screen:
    """shots/play-16.png: a railroad title deed card."""
    st = _mid_game([1168, 1202], {0: [9, 14], 1: [8, 19, 28]})
    st.players[0].position = 35
    scr = cga.Screen()
    screens.draw_turn_screen(scr, st, "alice's turn",
                             ["Short Line Railroad isn't owned."],
                             OFFER, deed=35)
    return scr


def build_utility_card() -> cga.Screen:
    """shots/play-09.png: a utility title deed card."""
    st = _mid_game([1204, 1216], {0: [9, 14], 1: [8, 19]})
    st.players[1].position = 28
    st.current = 1
    scr = cga.Screen()
    screens.draw_turn_screen(scr, st, "bob's turn",
                             ["Water Works isn't owned."],
                             OFFER, deed=28)
    return scr


def build_street_rent() -> cga.Screen:
    """shots/play-08.png: rent owed on a developed-group street."""
    st = _mid_game([1204, 1216], {0: [9, 14], 1: [8, 19]})
    st.players[0].position = 19
    scr = cga.Screen()
    screens.draw_turn_screen(scr, st, "alice's turn",
                             ["bob owns New York Avenue.",
                              "Your rent is $16."],
                             None, deed=19)
    screens.prompt_panel(scr, BUSINESS)
    return scr


def build_utility_rent() -> cga.Screen:
    """shots/play-11.png: utility rent, four times the dice."""
    st = _mid_game([1168, 1070], {0: [9, 14], 1: [8, 19, 28]})
    st.players[0].position = 28
    scr = cga.Screen()
    screens.draw_turn_screen(scr, st, "alice's turn",
                             ["bob owns Water Works.",
                              "You had rolled a 9 so",
                              "your rent is $36."],
                             None, deed=28)
    return scr


def build_business_menu() -> cga.Screen:
    """shots/biz-01.png: the eight-choice business menu."""
    st = _mid_game([1500, 1500], {})
    st.players[0].position = 8
    scr = cga.Screen()
    scr.set_attr(cga.LIGHTGRAY, cga.BLACK)
    scr.clrscr()
    screens.draw_deed_card(scr, 8, st)
    screens.cash_line(scr, st)
    screens.business_panel(scr, "alice on Vermont Avenue.")
    return scr


CASES = [
    ("01-player1.png", build_title_1, "title screen, one name entered"),
    ("02-player2.png", build_title_2, "title screen, two names entered"),
    ("11-bob-land.png", build_offer_purchase, "landed on unowned property"),
    ("12-purchased.png", build_purchased, "property purchased"),
    ("play-16.png", build_railroad_card, "railroad title deed card"),
    ("play-09.png", build_utility_card, "utility title deed card"),
    ("play-08.png", build_street_rent, "street rent owed"),
    ("play-11.png", build_utility_rent, "utility rent owed"),
    ("biz-01.png", build_business_menu, "business menu"),
]


def _renders_same(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """True when two cells produce identical pixels despite differing bytes.

    A blank glyph shows only its background, so the foreground nibble is free;
    the original often leaves stale foreground colours in cleared cells.  Two
    different character codes with the same ROM bitmap are equivalent too.
    """
    ga, gb = cga.FONT[a[0]], cga.FONT[b[0]]
    if ga != gb:
        return False
    if not any(ga):  # blank glyph: only the background matters
        return (a[1] >> 4) == (b[1] >> 4)
    if not all(row == 0xFF for row in ga):
        return a[1] == b[1]
    return (a[1] & 0x0F) == (b[1] & 0x0F)  # solid glyph: only foreground shows


def cell_diff(mine: cga.Screen, theirs: cga.Screen):
    """Yields (x, y, mine, theirs, visible)."""
    for y in range(1, cga.ROWS + 1):
        for x in range(1, cga.COLS + 1):
            a, b = mine.cell(x, y), theirs.cell(x, y)
            if a != b:
                yield x, y, a, b, not _renders_same(a, b)


def run_case(shot: str, build, label: str) -> bool:
    path = SHOTS / shot
    if not path.exists():
        print(f"SKIP  {shot}  (capture not found)")
        return True

    reference, cursors = decode_capture(str(path))
    mine = build()

    diffs = list(cell_diff(mine, reference))
    visible = [d for d in diffs if d[4]]
    invisible = len(diffs) - len(visible)

    original = Image.open(path).convert("RGB")
    rendered = mine.render(scanline_double=(original.size[1] == 400))
    pix = np.abs(np.array(rendered).astype(int)
                 - np.array(original).astype(int)).sum(axis=2)

    # The CRTC draws the text cursor; it is not a character the port emits.
    scale = 2 if original.size[1] == 400 else 1
    for cx, cy in cursors:
        pix[cy * 8 * scale:(cy + 1) * 8 * scale, cx * 8:(cx + 1) * 8] = 0

    bad_px = int((pix > 0).sum())

    status = "PASS" if bad_px == 0 else "FAIL"
    print(f"{status}  {shot:<20s} {label}")
    print(f"        {bad_px}/{pix.size} pixels differ; "
          f"{len(visible)} visible cell diffs"
          + (f", {invisible} attribute-only (render identically)"
             if invisible else ""))
    for x, y, a, b, _ in visible[:12]:
        print(f"        ({x:2d},{y:2d}) port={a[0]:3d}/{a[1]:#04x}  "
              f"orig={b[0]:3d}/{b[1]:#04x}")
    if len(visible) > 12:
        print(f"        ... and {len(visible) - 12} more")
    return bad_px == 0


def main() -> int:
    ok = all([run_case(*c) for c in CASES])
    print("\nall exact" if ok else "\nmismatches above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
