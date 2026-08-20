"""Export the port's static data for the browser build.

The HTML port is a reimplementation, not a wrapper, but there is no reason to
retype the tables: the font, the board figure, the die drawings and the square
and card data are already decoded here and checked by the test suite.  This
writes them out as one JavaScript module so the browser build and the Python
build cannot drift apart.

    python3 tools/export_web.py --out web/data.js
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from monopoly import (cards, cga, data, diceart, graphics,  # noqa: E402
                      screens, sound)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="web/data.js")
    args = ap.parse_args()

    asset = graphics.find_asset()
    if asset is None:
        print("MONOGRAF.GRA not found; the board figure cannot be exported")
        return 1
    board = graphics.load_board(asset)
    flat = bytes(v for row in board for v in row)

    font = bytes(b for glyph in cga.FONT for b in glyph)
    vga_path = Path(__file__).resolve().parents[1] / "assets" / "vga8x16.bin"
    vga16 = vga_path.read_bytes() if vga_path.exists() else b""

    squares = []
    for sq in data.PLACE:
        squares.append({
            "name": sq.name,
            "short": sq.short,
            "shortUc": sq.short_uc,
            "cost": sq.cost,
            "rent": list(sq.rent) if sq.rent else [],
            "group": sq.group,
            "kind": sq.kind,
            "mortgage": sq.mortgage_value,
            "screenPos": sq.screen_pos,
            "side": sq.side,
            "ownable": bool(sq.ownable),
        })

    def deck(entries):
        return [{"text": c.text, "action": c.action, "amount": c.amount,
                 "target": c.target, "note": c.note} for c in entries]

    groups = []
    for g in data.COLOR_GROUPS:
        if g is None:
            groups.append(None)
            continue
        groups.append({
            "name": g.name,
            "members": list(g.members),
            # the record's own order, descending, which the build cursor walks
            "buildOrder": list(g.build_order),
            "size": g.size,
            "houseCost": g.house_cost,
            "buildable": bool(g.buildable),
            # Two attribute pairs per group: the first colours the board and
            # the deed card's title band, the second the card interior.
            "ttext": g.ttext, "tback": g.tback,
            "ttext2": g.ttext2, "tback2": g.tback2,
        })

    payload = {
        "font": base64.b64encode(font).decode(),
        # The VGA 8x16 text font, taken from the emulated VGA BIOS at
        # C000:14F0 and checked against a real capture -- all 217 glyph cells
        # of the name-entry screen matched.  A DOS 6.22 machine had VGA, so
        # its 80x25 screens use this, not the chunky CGA 8x8.  The board is
        # unaffected: that is 320x200 graphics, where the game draws its own
        # 8x8 glyphs whatever the adapter.
        "fontVga": base64.b64encode(vga16).decode() if vga16 else "",
        "textPalette": [list(c) for c in cga.PALETTE],
        "gfxPalette": [list(c) for c in graphics.PALETTE],
        "board": {
            "w": len(board[0]), "h": len(board),
            "px": base64.b64encode(flat).decode(),
        },
        "diceArt": [list(a) for a in diceart.TUMBLE_ART],
        "diceOrigin": list(diceart.ART_ORIGIN),
        "diceSpacing": diceart.ART_SPACING,
        "squares": squares,
        "groups": groups,
        "chance": deck(cards.CHANCE),
        "chest": deck(cards.COMMUNITY_CHEST),
        "geom": {
            "dividers": list(graphics.DIVIDERS),
            "tokenShapes": [list(s) for s in graphics.TOKEN_SHAPES],
            "tokenSize": graphics.TOKEN_SIZE,
            "tokenStep": graphics.TOKEN_STEP,
            "tokenInset": graphics.TOKEN_INSET,
            "tokenEdge": graphics.TOKEN_EDGE,
            "tokenReverse": graphics.TOKEN_REVERSE,
            "tokenCorner": graphics.TOKEN_CORNER,
            "dieFace": graphics.DIE_FACE,
            "dieDepth": graphics.DIE_DEPTH,
            "dieTopDrop": graphics.DIE_TOP_DROP,
            "dieBottomDrop": graphics.DIE_BOTTOM_DROP,
            "textLeft": graphics.TEXT_LEFT,
            "textRight": graphics.TEXT_RIGHT,
            "titleRow": graphics.TITLE_ROW,
            "messageRow": graphics.MESSAGE_ROW,
            "cashNameRow": graphics.CASH_NAME_ROW,
            "cashMoneyRow": graphics.CASH_MONEY_ROW,
            "dieLeftX": graphics.DIE_LEFT_X,
            "dieRightX": graphics.DIE_RIGHT_X,
            "dieY": graphics.DIE_Y,
            "pipCols": list(graphics.PIP_COLS),
            "pipRows": list(graphics.PIP_ROWS),
            "pipLayout": {str(k): [list(p) for p in v]
                          for k, v in graphics.PIP_LAYOUT.items()},
            "labelRow": graphics.LABEL_ROW,
            "cashStep": graphics.CASH_STEP,
            "cashField": graphics.CASH_FIELD,
            "cashAmountWidth": graphics.CASH_AMOUNT_WIDTH,
            "tumbleHoldMs": graphics.TUMBLE_HOLD_MS,
            "stepMs": graphics.STEP_MS,
            "cornerMs": graphics.CORNER_MS,
            "jailInsetX": graphics.JAIL_INSET_X,
            "jailInsetY": graphics.JAIL_INSET_Y,
            "raisePauseMs": graphics.RAISE_PAUSE_MS,
            "jailFineMs": graphics.JAIL_FINE_MS,
            "jailRollPauseMs": graphics.JAIL_ROLL_PAUSE_MS,
            "buildUnitMs": graphics.BUILD_UNIT_MS,
            "returnUnitMs": graphics.RETURN_UNIT_MS,
            "jailPromptCol": graphics.JAIL_PROMPT_COL,
            "jailPromptRow": graphics.JAIL_PROMPT_ROW,
            "jailOptionRow": graphics.JAIL_OPTION_ROW,
            "jailHotkeyCol": graphics.JAIL_HOTKEY_COL,
            "flashToggles": graphics.FLASH_TOGGLES,
            "flashToggleMs": graphics.FLASH_TOGGLE_MS,
            "advanceBlits": graphics.ADVANCE_BLITS,
            "advanceBlitMs": graphics.ADVANCE_BLIT_MS,
            # one cube's clicks come round every 41.5 ms, so a pair -- a whole
            # animation frame -- is twice that
            "rattlePeriodMs": sound.RATTLE_PERIOD_MS,
            "rattleHoldMs": sound.RATTLE_HOLD_MS,
            "rollFrameMs": round(2 * sound.RATTLE_PERIOD_MS),
            # measured: the cash counter moves $5 every ~19 ms.  This used
            # to be exported as "cashStep" too, which silently replaced the
            # board's ten-column block step above -- the cash blocks ended up
            # five columns apart and the second player's "$" landed on top of
            # the first player's figure.
            "cashStepMs": 19,
            "cashStepAmount": 5,
            "blinkOnMs": graphics.BLINK_ON_MS,
            "blinkOffMs": graphics.BLINK_OFF_MS,
            "blinkCycles": graphics.BLINK_CYCLES,
        },
        # The real speaker cues, recovered from the Sound call sites in the
        # original rather than invented to taste.
        "cues": {name: [list(t) for t in cue.tones]
                 for name, cue in sound.CUES.items()},
        # Where a cue is one of the original's frequency loops, its endpoints
        # and duration: the browser can ramp a frequency smoothly, which the
        # sampled `tones` form cannot do without audibly staircasing.
        # from, to, ramp ms, then the hold on the first and last note
        "glides": {name: list(cue.glide) + list(cue.hold)
                   for name, cue in sound.CUES.items() if cue.glide},
        # No roll tones: the tumble's sound is the frames' own random draws.
        # The timings live in "geom" with every other one -- they were up here
        # once, where the code that reads them off DATA.geom got undefined and
        # spun the tumble at the browser's timer floor.
        "text": {
            "titlePanel": list(screens.TITLE_PANEL),
            "entryPanel": list(screens.ENTRY_PANEL),
            "messagePanel": list(screens.MESSAGE_PANEL),
            "promptPanel": list(screens.PROMPT_PANEL),
            "deedPanel": list(screens.DEED_PANEL),
            "noCashPanel": list(screens.NO_CASH_PANEL),
            "deedCard": list(screens.DEED_CARD),
            "trademark": screens.TRADEMARK_LINE,
            "adaptation": screens.ADAPTATION_LINE,
            "keysLine": screens.KEYS_LINE,
            "nameFieldWidth": screens.NAME_FIELD_WIDTH,
            "firstSlotRow": screens.FIRST_SLOT_ROW,
            "slotMarkerCol": screens.SLOT_MARKER_COL,
            "slotNameCol": screens.SLOT_NAME_COL,
            "cashBoxX": list(screens.CASH_BOX_X),
            "cashBoxW": screens.CASH_BOX_W,
            "cashRow": screens.CASH_ROW,
            "holdingsBaseCol": screens.HOLDINGS_BASE_COL,
            "holdingsPlayerStep": screens.HOLDINGS_PLAYER_STEP,
            "holdingsBaseRow": screens.HOLDINGS_BASE_ROW,
            "businessPanel": list(screens.BUSINESS_PANEL),
            "businessTitleCentre": screens.BUSINESS_TITLE_CENTRE,
            "businessOptions": list(screens.BUSINESS_OPTIONS),
            # The build/return screens take one keypress, not a typed name.
            "groupKeys": [list(x) for x in data.GROUP_KEYS],
            "groupCancelKey": data.GROUP_CANCEL_KEY,
            "colours": {n: getattr(cga, n) for n in
                        ("BLACK", "BLUE", "GREEN", "CYAN", "RED", "MAGENTA",
                         "BROWN", "LIGHTGRAY", "DARKGRAY", "YELLOW", "WHITE",
                         "LIGHTCYAN", "LIGHTRED")},
        },
        "cards": {
            "railroadSquares": list(data.RAILROAD_SQUARES),
            "utilitySquares": list(data.UTILITY_SQUARES),
            "goSalary": data.GO_SALARY,
        },
        "rules": {
            "startingCash": data.STARTING_CASH,
            "go": data.GO,
            "minPlayers": data.MIN_PLAYERS,
            "maxPlayers": data.MAX_PLAYERS,
            "housesPerHotel": data.HOUSES_PER_HOTEL,
            "jailFine": data.JAIL_FINE,
            "incomeTaxFlat": data.INCOME_TAX_FLAT,
            "incomeTaxRate": data.INCOME_TAX_RATE,
            "businessPrompt": ["Want to do some ~Business?",
                               "    or ready to ~Go on?"],
        },
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("// Generated by tools/export_web.py -- do not edit.\n"
                   "export const DATA = "
                   + json.dumps(payload, separators=(",", ":")) + ";\n")
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")
    print(f"  board {payload['board']['w']}x{payload['board']['h']}, "
          f"{len(squares)} squares, {len(payload['chance'])} chance, "
          f"{len(payload['chest'])} chest, "
          f"{len(payload['diceArt'])} die drawings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
