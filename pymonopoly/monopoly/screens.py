"""Screen layouts, reproduced cell-for-cell from the original.

Each function draws one of the 1985 program's screens onto a cga.Screen using
the primitives Turbo Pascal gave it: filled rectangles for the panels, and
positioned coloured text for everything else.

Every layout constant -- panel corners, text columns, colour attributes -- was
read off a capture of the real program running under DOSBox with
tools/extract_layout.py rather than guessed.  tools/compare_screens.py renders
these functions and diffs them against those captures.

The panels contain no box-drawing characters at all.  The original simply
wrote spaces in the right background colour, which is why every frame has
square corners: a one-cell LightGray border around a coloured interior.

One deliberate substitution is marked in draw_board(): the original switches
the display to CGA 320x200 four-colour graphics to draw the board itself.
Until that renderer exists, the board is drawn in text mode instead.  Every
other screen here is text mode in the original too.
"""

from __future__ import annotations

from . import data, rules
from .cga import (
    BLACK, BLUE, BROWN, DARKGRAY, GREEN, LIGHTCYAN, LIGHTGRAY, LIGHTRED,
    RED, WHITE, YELLOW, Screen,
)
from .state import BANK, GameState

# --------------------------------------------------------------------------
# Panel geometry, in 1-based screen cells, as measured from the captures.
# --------------------------------------------------------------------------

TITLE_PANEL = (25, 6, 55, 10)
ENTRY_PANEL = (15, 14, 65, 23)

MESSAGE_PANEL = (2, 3, 42, 15)  # LightGray frame; Blue interior
DEED_PANEL = (48, 1, 80, 17)  # solid Brown; LightGray card inside
DEED_CARD = (50, 5, 78, 16)

# The dark-red box that drops over the message panel when a player cannot
# meet a payment.  Measured from a capture: columns 5..36, rows 9..23, and it
# hangs below the blue panel rather than sitting inside it.
NO_CASH_PANEL = (5, 9, 36, 23)

# The development mark on a title deed: character 219, the full block.
BLOCK = 219
HOTEL_BLOCKS = 6        # a hotel draws six; houses draw one apiece

CASH_ROW = 19  # top row of the per-player cash boxes (two rows tall)
CASH_BOX_W = 18
CASH_BOX_X = (22, 42, 2, 62)  # left edge per player slot
HOLDINGS_ROW = 22

TRADEMARK_LINE = "MONOPOLY is a registered trademark of Parker Brothers, Inc."
ADAPTATION_LINE = "MS-DOS adaptation (C) 1985 Don Phillip Gibson [5.1]"
KEYS_LINE = "During DiceRoll F1 toggles sound, F2 saves game.  F2 now loads saved game."

NAME_FIELD_WIDTH = 10
FIRST_SLOT_ROW = 18
SLOT_MARKER_COL = 33
SLOT_NAME_COL = 36


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------


def panel(scr: Screen, left: int, top: int, right: int, bottom: int,
          frame: int = LIGHTGRAY, interior: int = BROWN) -> None:
    """A framed panel: one-cell border, filled interior."""
    scr.fill(left, top, right - left + 1, bottom - top + 1,
             0x20, (frame << 4) | frame)
    scr.fill(left + 1, top + 1, right - left - 1, bottom - top - 1,
             0x20, (interior << 4) | interior)


def centered(text: str, left: int, right: int) -> int:
    return left + ((right - left + 1) - len(text)) // 2


def centered_up(text: str, left: int, right: int) -> int:
    """Centre rounding half a column right instead of left.

    The original is not consistent about this: the title deed card's caption
    lines round down, but the cash boxes round up.  Both were measured, so
    both are kept rather than unified into something tidier that would be
    wrong on one of them.
    """
    return left + ((right - left + 1) - len(text) + 1) // 2


# The turn title is centred on a fixed column rather than within the panel.
# Solved from two captures: "alice's turn" (12 chars) starts at column 14 and
# "wilhelmina's turn" (17 chars) starts at column 11, which pins the midpoint
# at column 20 for both.
TITLE_CENTRE = 20


def centered_on(text: str, centre: int = TITLE_CENTRE) -> int:
    return centre - (len(text) + 1) // 2


def hotkey_text(scr: Screen, x: int, y: int, text: str,
                fg: int, bg: int, key_fg: int = LIGHTCYAN) -> None:
    """Write text where '~' marks the next character as the hot key.

    The original highlights the letter you press in LightCyan inside the
    otherwise white prompt -- "~Purchase it from the bank?" renders the P in
    cyan and the rest in white.
    """
    col = x
    i = 0
    while i < len(text):
        if text[i] == "~" and i + 1 < len(text):
            scr.write_at(col, y, text[i + 1], key_fg, bg)
            col += 1
            i += 2
        else:
            scr.write_at(col, y, text[i], fg, bg)
            col += 1
            i += 1


def hotkey_of(text: str) -> str:
    """The letter '~' marks, lowercased."""
    i = text.find("~")
    return text[i + 1].lower() if i >= 0 and i + 1 < len(text) else ""


def plain(text: str) -> str:
    return text.replace("~", "")


# --------------------------------------------------------------------------
# Title / player entry
# --------------------------------------------------------------------------


def draw_title(scr: Screen, names: list[str] | None = None,
               show_prompt: bool = True) -> None:
    """The opening screen: credits, logo panel, and the player entry list.

    Verified pixel-exact against shots/01-player1.png and 02-player2.png
    (256000 pixels, zero differences).
    """
    names = names or []

    scr.set_attr(LIGHTGRAY, BLACK)
    scr.clrscr()

    scr.write_at(10, 1, TRADEMARK_LINE, DARKGRAY, BLACK)
    scr.write_at(14, 2, ADAPTATION_LINE, DARKGRAY, BLACK)

    panel(scr, *TITLE_PANEL)
    scr.write_at(36, 8, "Monopoly", WHITE, BROWN)

    scr.write_at(27, 13, "Welcome to the Monopoly Game", GREEN, BLACK)

    panel(scr, *ENTRY_PANEL)
    scr.write_at(31, 16, "Who are the players?", YELLOW, BROWN)

    for i in range(len(names) + (1 if show_prompt else 0)):
        row = FIRST_SLOT_ROW + i
        scr.write_at(SLOT_MARKER_COL, row, f"{i + 1}>", LIGHTGRAY, BROWN)
        if i < len(names):
            scr.write_at(SLOT_NAME_COL, row, names[i], WHITE, BROWN)
        else:
            scr.write_at(SLOT_NAME_COL, row, "." * NAME_FIELD_WIDTH,
                         LIGHTGRAY, BROWN)

    scr.write_at(3, 25, KEYS_LINE, DARKGRAY, BLACK)


# --------------------------------------------------------------------------
# The message panel -- the blue box every turn talks through
# --------------------------------------------------------------------------


def message_panel(scr: Screen, title: str, lines: list[str],
                  options: list[str] | None = None) -> None:
    """Draw the left-hand panel: whose turn it is, what happened, what to do.

    `lines` is plain text; `options` may use '~' to mark hot keys.
    """
    left, top, right, bottom = MESSAGE_PANEL
    panel(scr, left, top, right, bottom, LIGHTGRAY, BLUE)

    inner_l, inner_r = left + 1, right - 1
    if title:
        scr.write_at(centered_on(title), top + 1, title, WHITE, BLUE)

    row = top + 3
    for line in lines:
        if row > bottom - 1:
            break
        scr.write_at(inner_l + 2, row, line[:inner_r - inner_l - 2], WHITE, BLUE)
        row += 1

    if options:
        row += 1
        for opt in options:
            if row > bottom - 1:
                break
            hotkey_text(scr, inner_l + 2, row, opt, WHITE, BLUE, LIGHTCYAN)
            row += 1


# The second prompt style: a brown-framed green box laid over the message
# panel, used for the Business / Go on question.  Its hot keys are white on
# yellow text rather than the blue panel's light cyan on white.
PROMPT_PANEL = (1, 9, 35, 14)


def prompt_panel(scr: Screen, options: list[str],
                 bounds: tuple[int, int, int, int] = PROMPT_PANEL) -> None:
    left, top, right, bottom = bounds
    panel(scr, left, top, right, bottom, BROWN, GREEN)
    row = top + 2
    for opt in options:
        if row > bottom - 1:
            break
        hotkey_text(scr, left + 2, row, opt, YELLOW, GREEN, WHITE)
        row += 1


# The business menu is a third panel: the same brown-on-green styling as the
# small prompt, but tall enough for all eight choices.  Measured from
# shots/biz-01.png -- frame (2,2)-(41,17), title centred in columns 2..40.
BUSINESS_PANEL = (2, 2, 40, 17)

BUSINESS_OPTIONS = [
    "Want to ~Buy from another player?",
    "     or ~Sell to another player?",
    " or buy ~Houses and Hotels?",
    " or see ~Title Deed card?",
    "     or ~Mortgage property?",
    "     or ~Return Houses?",
    "     or ~Unmortgage property?",
    "     or ~Go on with game?",
]


def business_panel(scr: Screen, title: str,
                   options: list[str] | None = None) -> None:
    left, top, right, bottom = BUSINESS_PANEL
    panel(scr, left, top, right, bottom, BROWN, GREEN)
    scr.write_at(centered(title, left, right), top + 1, title, WHITE, GREEN)
    # Note the colours are the reverse of the small prompt panel: here the
    # body is white and the hot key is yellow.
    row = top + 3
    for opt in options or BUSINESS_OPTIONS:
        if row > bottom - 1:
            break
        hotkey_text(scr, left + 3, row, opt, WHITE, GREEN, YELLOW)
        row += 1


def draw_no_cash(scr: Screen, name: str) -> None:
    """The red box telling a player they cannot pay.

    Captured from the original: a dark-red panel over the message panel with
    the player's name between dashes and "YOU DON'T HAVE ENOUGH CASH." -- not
    the "YOU MUST RAISE SOME MONEY." this port used to print, which belongs
    to the routine behind it (CHN file 0x2A89 holds the real line).
    """
    left, top, right, bottom = NO_CASH_PANEL
    scr.fill(left, top, right - left + 1, bottom - top + 1, 0x20,
             (RED << 4) | WHITE)
    tag = f"--{name}--"
    scr.write_at(centered(tag, left, right), top + 1, tag, WHITE, RED)
    line = "YOU DON'T HAVE ENOUGH CASH."
    col = centered(line, left, right)
    scr.write_at(col, top + 2, line, WHITE, RED)
    # The original leaves its cursor on the line below, where it waits.
    scr.cursor = (col, top + 3)


def paint_short_names(scr: Screen, panel: tuple[int, int, int, int],
                      positions, first_line: int) -> None:
    """Repaint the property picker's short names in their group's colours.

    Measured from a capture of the picker: every name carries the colour pair
    its group wears on the board -- Medit and Balt on 0x51, Ori/Ver/Con on
    0x3F, and so on for all ten groups.  Drawing them in the panel's own
    colours, which this port did, loses the only cue that tells you which
    group a name belongs to.
    """
    left, top = panel[0], panel[1]
    keep = sorted(set(positions))
    for r, groups in enumerate(data.SHORT_NAME_ROWS):
        col = left + 3 + data.SHORT_NAME_INDENT
        row = top + 3 + first_line + r
        for g in groups:
            grp = data.COLOR_GROUPS[g]
            for p in keep:
                sq = data.PLACE[p]
                if sq.short and sq.group == g:
                    scr.write_at(col, row, sq.short, grp.ttext, grp.tback)
                    col += len(sq.short)


def paint_group_rows(scr: Screen, panel: tuple[int, int, int, int],
                     groups: list[int], first_line: int) -> None:
    """Draw the colour-group rows of the picker in each group's own colours.

    The original sets TextBackground from the ColorGroup record's +25 field
    and TextColor from +23 before writing a two-space swatch and the name,
    and puts the first letter in LightCyan -- CHN 0x9282-0x92B8.  The five
    spaces before the swatch keep the panel's own colours, so they are left
    as the panel drew them.
    """
    left, top = panel[0], panel[1]
    lead = data.GROUP_ROW_INDENT - data.GROUP_SWATCH_WIDTH
    for i, g in enumerate(groups):
        grp = data.COLOR_GROUPS[g]
        row = top + 3 + first_line + i
        col = left + 3 + lead
        scr.write_at(col, row, " " * data.GROUP_SWATCH_WIDTH,
                     grp.ttext, grp.tback)
        col += data.GROUP_SWATCH_WIDTH
        scr.write_at(col, row, grp.name[:1], LIGHTCYAN, grp.tback)
        scr.write_at(col + 1, row, grp.name[1:], grp.ttext, grp.tback)


def draw_business_screen(scr: Screen, state: GameState, lines: list[str],
                         deed: int | None = None) -> None:
    """Every screen reached from the business menu keeps that menu's panel.

    Measured against the real program: the header stays "<name> on <square>."
    on row 3 and the body starts on row 5 -- one row above the ordinary turn
    panel -- and the frame stays green on brown throughout, including the
    error answers and the short-name prompt.  Drawing these in the blue
    message panel, which this port used to do, put every line a row too low
    and in the wrong colours.
    """
    scr.set_attr(LIGHTGRAY, BLACK)
    scr.clrscr()
    pos = state.player.position
    title = f"{state.player.name} on {data.PLACE[pos].name}."
    business_panel(scr, title, lines)
    if deed is None and data.PLACE[pos].ownable:
        deed = pos
    if deed is not None and data.PLACE[deed].ownable:
        draw_deed_card(scr, deed, state)
    cash_line(scr, state)


# --------------------------------------------------------------------------
# Title deed cards
# --------------------------------------------------------------------------


def _deed_colors(pos: int) -> tuple[int, int, int, int]:
    """The card's two colour pairs: (title fg, title bg, body fg, body bg).

    Each ColorGroup record carries two attribute pairs.  The first colours the
    group on the board and the card's title band; the second colours the card
    interior.  Confirmed from captures -- St. James Place (Orange) draws its
    body white on light grey, Connecticut Avenue (Cyan) draws light green on
    light grey, and both match their group's second pair exactly.
    """
    sq = data.PLACE[pos]
    grp = data.COLOR_GROUPS[sq.group] if sq.group else None
    if grp is None:
        return YELLOW, BROWN, WHITE, LIGHTGRAY
    return grp.ttext, grp.tback, grp.ttext2, grp.tback2


def deed_houses(scr: Screen, houses: int, body_bg: int) -> None:
    """Mark a developed property on its card with solid blocks.

    The original writes character 219 -- a full block -- at the card's (3,2),
    which is the title band, and the count is the development itself: one
    block per house, and six for a hotel.  The colour is chosen for contrast
    against the card: houses come out white on backgrounds 2 and 3 and green
    otherwise, a hotel white on 4 and 6 and red otherwise (CHN file 0x3BF0
    and 0x3C95).  The "1 HOUSE" / "HOTEL" caption this port used to print
    appears nowhere in the program.
    """
    left, top = DEED_PANEL[0], DEED_PANEL[1]
    if houses >= data.HOUSES_PER_HOTEL:
        count = HOTEL_BLOCKS
        fg = WHITE if body_bg in (4, 6) else RED
    else:
        count = houses
        fg = WHITE if body_bg in (2, 3) else GREEN
    scr.write_at(left + 2, top + 1, chr(BLOCK) * count, fg, body_bg)


def _deed_frame(scr: Screen, pos: int) -> tuple[int, int]:
    """Paint the card body and its title; returns the card's x bounds."""
    sq = data.PLACE[pos]
    title_fg, title_bg, _body_fg, body_bg = _deed_colors(pos)

    pl, pt, pr, pb = DEED_PANEL
    scr.fill(pl, pt, pr - pl + 1, pb - pt + 1, 0x20, (title_bg << 4) | title_bg)
    scr.write_at(centered_up(sq.name, pl, pr), 3, sq.name, title_fg, title_bg)

    cl, ct, cr, cb = DEED_CARD
    scr.fill(cl, ct, cr - cl + 1, cb - ct + 1, 0x20, (body_bg << 4) | body_bg)
    return cl, cr


def _money(scr: Screen, y: int, dollar_x: int, right_x: int, amount: int,
           fg: int, bg: int) -> None:
    text = str(amount)
    scr.write_at(dollar_x, y, "$", fg, bg)
    scr.write_at(right_x - len(text) + 1, y, text, fg, bg)


def draw_deed_card(scr: Screen, pos: int, state: GameState | None = None) -> None:
    """The title deed card on the right of the screen.

    Column positions match the capture in shots/11-bob-land.png: the Cost row
    sits one column left of the rent ladder, which is an artefact of the
    original writing fixed-width label strings before each figure.
    """
    sq = data.PLACE[pos]
    if not sq.ownable:
        return
    _deed_frame(scr, pos)
    _t_fg, _t_bg, fg, bg = _deed_colors(pos)

    # Row and column positions differ per card type; all measured from
    # captures, and none of them are centred -- the original writes
    # fixed-width label strings and then the figure.
    scr.write_at(58, 6, "Cost", fg, bg)
    _money(scr, 6, 67, 71, sq.cost, fg, bg)

    if sq.kind == data.STREET:
        scr.write_at(57, 8, "Rent", fg, bg)
        _money(scr, 8, 68, 72, sq.rent[0], fg, bg)
        for n in range(1, 5):
            scr.write_at(58, 8 + n, str(n), fg, bg)
            scr.write_at(60, 8 + n, "house" if n == 1 else "houses", fg, bg)
            _money(scr, 8 + n, 68, 72, sq.rent[n], fg, bg)
        scr.write_at(60, 13, "hotel", fg, bg)
        _money(scr, 13, 68, 72, sq.rent[5], fg, bg)
        scr.write_at(51, 15,
                     f"Cost of each house is ${rules.house_cost(sq.group)}.",
                     fg, bg)
        mortgage_row = 16

    elif sq.kind == data.RAILROAD:
        scr.write_at(57, 8, "Rent", fg, bg)
        _money(scr, 8, 69, 73, rules.railroad_rent(1), fg, bg)
        for n in (2, 3, 4):
            scr.write_at(59, 7 + n, "if", fg, bg)
            scr.write_at(62, 7 + n, str(n), fg, bg)
            scr.write_at(64, 7 + n, "RRs", fg, bg)
            _money(scr, 7 + n, 69, 73, rules.railroad_rent(n), fg, bg)
        mortgage_row = 13

    else:  # utility -- four fixed lines, the indent carried in the strings
        for row, line in ((8, "Rent if one utility owned is"),
                          (9, "  four times amount on dice."),
                          (11, "If both utilities are owned"),
                          (12, "  then ten times the dice.")):
            scr.write_at(50, row, line, fg, bg)
        mortgage_row = 14

    scr.write_at(54, mortgage_row,
                 f"Mortgage value is ${rules.mortgage_value(pos)}.", fg, bg)

    if state is not None and state.props[pos].houses:
        deed_houses(scr, state.props[pos].houses, bg)

    if state is not None and state.props[pos].mortgaged:
        scr.write_at(centered("MORTGAGED", 51, 78), mortgage_row - 2,
                     "MORTGAGED", LIGHTRED, bg)


# --------------------------------------------------------------------------
# Cash line and holdings
# --------------------------------------------------------------------------

_GROUP_FG = {}


def cash_line(scr: Screen, state: GameState) -> None:
    """The per-player cash boxes and the short names of what they hold."""
    for i, ply in enumerate(state.players):
        if i >= len(CASH_BOX_X):
            break
        x = CASH_BOX_X[i]
        fg = DARKGRAY if ply.bankrupt else WHITE
        scr.fill(x, CASH_ROW, CASH_BOX_W, 2, 0x20,
                 (LIGHTGRAY << 4) | LIGHTGRAY)
        scr.write_at(centered_up(ply.name, x, x + CASH_BOX_W - 1), CASH_ROW,
                     ply.name[:CASH_BOX_W], fg, LIGHTGRAY)
        cash = "BANKRUPT" if ply.bankrupt else f"$ {ply.cash}"
        scr.write_at(centered_up(cash, x, x + CASH_BOX_W - 1), CASH_ROW + 1,
                     cash, fg, LIGHTGRAY)

        holdings_map(scr, state, i)


# --------------------------------------------------------------------------
# Holdings map
#
# The short names of what a player owns are not listed under their cash box.
# Each player gets a miniature board: the marker's row comes from the square's
# Side field (1 bottom, 2 left, 3 top, 4 right, 5 railroads and utilities) and
# its column from the ScreenPos field, offset by the player's slot.  Those two
# fields in the Place[] record exist for exactly this.
#
# Solved from captures: Connecticut (ScreenPos 16, Side 1) drew at column 37
# for player one, Virginia (7, 2) at column 28, and for player two Vermont
# (13, 1) at column 54 and New York (16, 2) at 57.
# --------------------------------------------------------------------------

HOLDINGS_BASE_COL = 21
HOLDINGS_PLAYER_STEP = 20
HOLDINGS_BASE_ROW = 20


def holdings_map(scr: Screen, state: GameState, player: int) -> None:
    for pos in state.holdings(player):
        sq = data.PLACE[pos]
        st = state.props[pos]
        grp = data.COLOR_GROUPS[sq.group]

        # The short name keeps its capitalisation; a mortgaged holding is
        # distinguished by colour rather than by case, which is what the
        # original does and what lower-casing it here got wrong.
        mark = sq.short
        if not st.mortgaged and st.houses:
            mark = f"{mark}{st.houses}"

        col = sq.screen_pos + HOLDINGS_BASE_COL + HOLDINGS_PLAYER_STEP * player
        row = HOLDINGS_BASE_ROW + sq.side
        if 1 <= row <= ROWS_LIMIT and col >= 1:
            # A mortgaged holding overrides the group's colours with
            # LightGray on Black -- TextColor(7)/TextBackground(0) at CHN
            # 0x5E41, reached when Owner[sq].Mort is set.  The name itself is
            # written the same either way, which is why the case must not
            # change.
            if st.mortgaged:
                fg, bg = LIGHTGRAY, BLACK
            elif grp is None:
                # Only ownable squares reach here in play, and every one of
                # them has a group; be explicit rather than fall over if a
                # caller ever hands us a corner.
                fg, bg = WHITE, BLACK
            else:
                fg, bg = grp.ttext, grp.tback
            scr.write_at(col, row, mark, fg, bg)


ROWS_LIMIT = 25


# --------------------------------------------------------------------------
# The board
# --------------------------------------------------------------------------

CELL_W = 5
CELL_H = 2
BOARD_X = 1
BOARD_Y = 2

# Ring order: index 0..39 mapped to (col, row) on an 11x11 ring, GO at the
# bottom-right corner and play running anticlockwise, as on the real board.
def _ring_cell(pos: int) -> tuple[int, int]:
    if pos <= 10:  # bottom edge, right to left
        return 10 - pos, 10
    if pos <= 20:  # left edge, bottom to top
        return 0, 10 - (pos - 10)
    if pos <= 30:  # top edge, left to right
        return pos - 20, 0
    return 10, pos - 30  # right edge, top to bottom


def draw_board(scr: Screen, state: GameState) -> None:
    """The board.

    SUBSTITUTION: the original switches to CGA 320x200 four-colour graphics
    here and draws a bitmap board built from the arrays in MONOGRAF.GRA.  This
    is a text-mode stand-in with the same information -- square, owner and
    development -- pending that renderer.  It is the one screen in this module
    that is not a reproduction.
    """
    scr.set_attr(LIGHTGRAY, BLACK)
    scr.clrscr()

    for pos in range(40):
        col, row = _ring_cell(pos)
        x = BOARD_X + col * CELL_W
        y = BOARD_Y + row * CELL_H
        sq = data.PLACE[pos]
        st = state.props[pos]

        if sq.group:
            grp = data.COLOR_GROUPS[sq.group]
            fg, bg = grp.ttext, grp.tback
        else:
            fg, bg = BLACK, LIGHTGRAY

        label = (sq.short or sq.name[:CELL_W]).ljust(CELL_W)[:CELL_W]
        scr.fill(x, y, CELL_W, CELL_H, 0x20, (bg << 4) | fg)
        scr.write_at(x, y, label, fg, bg)

        marks = ""
        if st.owner != BANK:
            marks = str(st.owner + 1)
            if st.mortgaged:
                marks += "m"
            elif st.houses == data.HOUSES_PER_HOTEL:
                marks += "H"
            elif st.houses:
                marks += str(st.houses)
        scr.write_at(x, y + 1, marks.ljust(CELL_W)[:CELL_W], fg, bg)

    # Tokens
    for i, ply in enumerate(state.players):
        if ply.bankrupt:
            continue
        col, row = _ring_cell(ply.position)
        x = BOARD_X + col * CELL_W + CELL_W - 1
        y = BOARD_Y + row * CELL_H + 1
        scr.write_at(x, y, str(i + 1), WHITE, RED)


def draw_turn_screen(scr: Screen, state: GameState, title: str,
                     lines: list[str], options: list[str] | None = None,
                     deed: int | None = None) -> None:
    """The standard in-play screen: message panel, cash line, optional card."""
    scr.set_attr(LIGHTGRAY, BLACK)
    scr.clrscr()
    message_panel(scr, title, lines, options)
    if deed is not None and data.PLACE[deed].ownable:
        draw_deed_card(scr, deed, state)
    cash_line(scr, state)


def dice_faces(scr: Screen, x: int, y: int, a: int, b: int) -> None:
    """The two dice, drawn as pip faces."""
    for i, value in enumerate((a, b)):
        _die(scr, x + i * DIE_PITCH, y, value)


_PIPS = {
    1: ((0, 0, 0), (0, 1, 0), (0, 0, 0)),
    2: ((1, 0, 0), (0, 0, 0), (0, 0, 1)),
    3: ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    4: ((1, 0, 1), (0, 0, 0), (1, 0, 1)),
    5: ((1, 0, 1), (0, 1, 0), (1, 0, 1)),
    6: ((1, 0, 1), (1, 0, 1), (1, 0, 1)),
}


# A CGA text-mode background can only be one of the low eight colours, so the
# brightest die face available is light grey; white would silently mask down
# to the same thing.  The original draws its dice as isometric cubes in
# graphics mode instead -- see the note in graphics.py.
DIE_ATTR = (LIGHTGRAY << 4) | BLACK
DIE_W, DIE_H = 5, 3
DIE_PITCH = 6


def _die(scr: Screen, x: int, y: int, value: int) -> None:
    scr.fill(x, y, DIE_W, DIE_H, 0x20, DIE_ATTR)
    for r, rowdef in enumerate(_PIPS.get(value, ())):
        for c, on in enumerate(rowdef):
            if on:
                # CP437 bullet; no Python character maps to it.
                scr.putcell(x + 1 + c, y + r, 0x07, DIE_ATTR)
