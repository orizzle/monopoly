"""Static tables recovered from MONOCODE.CHN (Monopoly 5.1, Turbo Pascal 3.0, 1985).

The original program kept three parallel typed-constant arrays in its code
segment.  They are reproduced here with the same split and the same 1-based
indexing the Pascal source used, so that the rule code below reads the way the
original did:

    ColorGroup : array[1..10] of ...   file 0x1431, 35 bytes/record
    Place      : array[1..40] of ...   file 0x158F, 42 bytes/record
    Value      : array[1..40] of ...   file 0x1C5F, 15 bytes/record

Board positions in this port are 0-based (GO == 0) because that is what Python
wants; `PLACE[n]` corresponds to the original's `Place[n + 1]`.  Anywhere a
recovered table stores 1-based indices -- ColorGroup.Members, for instance --
they are converted on load rather than left to trip up the caller.
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------
# Square kinds -- Place.Kind, byte at record offset +23
# --------------------------------------------------------------------------

STREET = 0
RAILROAD = 1
UTILITY = 2
SPECIAL = 3

OWNABLE = (STREET, RAILROAD, UTILITY)


# --------------------------------------------------------------------------
# ColorGroup : array[1..10] of record ... end
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ColorGroup:
    """One color group.  Field offsets are the original record's."""

    name: str  # +0   string[12]
    members: tuple[int, ...]  # +15  board positions (converted to 0-based)
    ttext: int  # +23  CGA foreground on the board
    tback: int  # +25  CGA background on the board
    ttext2: int  # +27  second pair, used on the title deed card
    tback2: int  # +29
    house_cost: int  # +31
    buildable: bool  # +33  1 for streets, 0 for RR/Utilities

    @property
    def size(self) -> int:
        """ColorGroup.NumberIn, +13 -- always len(members) in the shipped data."""
        return len(self.members)


def _grp(name, members, ttext, tback, ttext2, tback2, house_cost, buildable):
    # Members are stored 1-based and in descending order in the binary; the
    # order carries no meaning, so sort them into board order here.
    return ColorGroup(
        name=name,
        members=tuple(sorted(m - 1 for m in members)),
        ttext=ttext,
        tback=tback,
        ttext2=ttext2,
        tback2=tback2,
        house_cost=house_cost,
        buildable=bool(buildable),
    )


# Index 0 is unused so that COLOR_GROUPS[n] matches the original's 1-based
# ColorGroup[n]; Place.Group stores exactly these indices.
COLOR_GROUPS: tuple[ColorGroup | None, ...] = (
    None,
    _grp("DarkPurple", (4, 2), 1, 5, 15, 7, 50, 1),
    _grp("Cyan", (10, 9, 7), 15, 3, 10, 7, 50, 1),
    _grp("LightPurple", (15, 14, 12), 14, 5, 12, 0, 100, 1),
    _grp("Orange", (20, 19, 17), 14, 6, 15, 7, 100, 1),
    _grp("Red", (25, 24, 22), 15, 4, 15, 7, 150, 1),
    _grp("Yellow", (30, 28, 27), 14, 7, 15, 3, 150, 1),
    _grp("Green", (35, 33, 32), 14, 2, 10, 7, 200, 1),
    _grp("Blue", (40, 38), 15, 1, 15, 7, 200, 1),
    _grp("RR", (6, 16, 26, 36), 0, 7, 15, 0, 0, 0),
    _grp("Util", (13, 29), 15, 7, 1, 3, 0, 0),
)

GROUP_RR = 9
GROUP_UTIL = 10


# --------------------------------------------------------------------------
# Place : array[1..40]  +  Value : array[1..40]
#
# Kept as one dataclass here.  The 1985 split existed because Turbo Pascal 3
# could not spare the code space to carry money fields through the drawing
# routines, not because the two describe different things.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Square:
    name: str  # Place +0   string[22]
    kind: int  # Place +23
    group: int  # Place +24  index into COLOR_GROUPS, 0 for non-property
    screen_pos: int  # Place +26  offset along its board edge
    side: int  # Place +28  1 bottom, 2 left, 3 top, 4 right, 5 RR/Util
    short: str  # Place +30  string[5], display form
    short_uc: str  # Place +36  string[5], match form
    cost: int  # Value +0
    rent: tuple[int, ...]  # Value +3   base, 1h, 2h, 3h, 4h, hotel

    @property
    def ownable(self) -> bool:
        return self.kind in OWNABLE

    @property
    def mortgage_value(self) -> int:
        """Trunc(Value[n].Cost / 2), as the recovered source computes it."""
        return self.cost // 2


_Z = (0, 0, 0, 0, 0, 0)  # railroads and utilities ship with a zeroed Rent[]


def _sq(name, kind, group, screen_pos, side, short, short_uc, cost, rent):
    return Square(name, kind, group, screen_pos, side, short, short_uc, cost, rent)


PLACE: tuple[Square, ...] = (
    _sq("GO", SPECIAL, 0, 0, 0, "", "", 0, _Z),
    _sq("Mediterranean Avenue", STREET, 1, 1, 1, "Medit", "MEDIT", 60,
        (2, 10, 30, 90, 160, 250)),
    _sq("Community Chest", SPECIAL, 0, 0, 0, "", "", 0, _Z),
    _sq("Baltic Avenue", STREET, 1, 6, 1, "Balt", "BALT", 60,
        (4, 20, 60, 180, 320, 450)),
    _sq("Income Tax", SPECIAL, 0, 0, 0, "", "", 0, _Z),
    _sq("Reading Railroad", RAILROAD, 9, 1, 5, "Rea", "REA", 200, _Z),
    _sq("Oriental Avenue", STREET, 2, 10, 1, "Ori", "ORI", 100,
        (6, 30, 90, 270, 400, 550)),
    _sq("Chance", SPECIAL, 0, 0, 0, "", "", 0, _Z),
    _sq("Vermont Avenue", STREET, 2, 13, 1, "Ver", "VER", 100,
        (6, 30, 90, 270, 400, 550)),
    _sq("Connecticut Avenue", STREET, 2, 16, 1, "Con", "CON", 120,
        (8, 40, 100, 300, 450, 600)),
    _sq("just visiting...", SPECIAL, 0, 0, 0, "", "", 0, _Z),
    _sq("St. Charles Place", STREET, 3, 1, 2, "StC", "STC", 140,
        (10, 50, 150, 450, 625, 750)),
    _sq("Electric Company", UTILITY, 10, 13, 5, "Ele", "ELE", 150, _Z),
    _sq("States Avenue", STREET, 3, 4, 2, "Sta", "STA", 140,
        (10, 50, 150, 450, 625, 750)),
    _sq("Virginia Avenue", STREET, 3, 7, 2, "Vir", "VIR", 160,
        (12, 60, 180, 500, 700, 900)),
    _sq("Pennsylvania Railroad", RAILROAD, 9, 4, 5, "Prr", "PRR", 200, _Z),
    _sq("St. James Place", STREET, 4, 10, 2, "StJ", "STJ", 180,
        (14, 70, 200, 550, 750, 950)),
    _sq("Community Chest", SPECIAL, 0, 0, 0, "", "", 0, _Z),
    _sq("Tennessee Avenue", STREET, 4, 13, 2, "Ten", "TEN", 180,
        (14, 70, 200, 550, 750, 950)),
    _sq("New York Avenue", STREET, 4, 16, 2, "New", "NEW", 200,
        (16, 80, 220, 600, 800, 1000)),
    _sq("Free Parking", SPECIAL, 0, 0, 0, "", "", 0, _Z),
    _sq("Kentucky Avenue", STREET, 5, 1, 3, "Ken", "KEN", 220,
        (18, 90, 250, 700, 875, 1050)),
    _sq("Chance", SPECIAL, 0, 0, 0, "", "", 0, _Z),
    _sq("Indiana Avenue", STREET, 5, 4, 3, "Ind", "IND", 220,
        (18, 90, 250, 700, 875, 1050)),
    _sq("Illinois Avenue", STREET, 5, 7, 3, "Ill", "ILL", 240,
        (20, 100, 300, 750, 925, 1100)),
    _sq("B & O Railroad", RAILROAD, 9, 7, 5, "B&O", "B&O", 200, _Z),
    _sq("Atlantic Avenue", STREET, 6, 10, 3, "Atl", "ATL", 260,
        (22, 110, 330, 800, 975, 1150)),
    _sq("Ventnor Avenue", STREET, 6, 13, 3, "Ven", "VEN", 260,
        (22, 110, 330, 800, 975, 1150)),
    _sq("Water Works", UTILITY, 10, 16, 5, "Wat", "WAT", 150, _Z),
    _sq("Marvin Gardens", STREET, 6, 16, 3, "Mar", "MAR", 280,
        (24, 120, 360, 850, 1025, 1200)),
    _sq("GO TO JAIL", SPECIAL, 0, 0, 0, "", "", 0, _Z),
    _sq("Pacific Avenue", STREET, 7, 1, 4, "Pac", "PAC", 300,
        (26, 130, 390, 900, 1100, 1275)),
    _sq("North Carolina Avenue", STREET, 7, 4, 4, "Nor", "NOR", 300,
        (26, 130, 390, 900, 1100, 1275)),
    _sq("Community Chest", SPECIAL, 0, 0, 0, "", "", 0, _Z),
    _sq("Pennsylvania Avenue", STREET, 7, 7, 4, "Pen", "PEN", 320,
        (28, 150, 450, 1000, 1200, 1400)),
    _sq("Short Line Railroad", RAILROAD, 9, 10, 5, "Sho", "SHO", 200, _Z),
    _sq("Chance", SPECIAL, 0, 0, 0, "", "", 0, _Z),
    _sq("Park Place", STREET, 8, 10, 4, "Park", "PARK", 350,
        (35, 175, 500, 1100, 1300, 1500)),
    _sq("Luxury Tax", SPECIAL, 0, 0, 0, "", "", 0, _Z),
    _sq("Boardwalk", STREET, 8, 14, 4, "Board", "BOARD", 400,
        (50, 200, 600, 1400, 1700, 2000)),
)

assert len(PLACE) == 40


# --------------------------------------------------------------------------
# Token placement offsets -- the 32-word table at file 0x1C1F
#
# Sixteen (dx, dy) pairs: four token slots arranged 2x2 inside a square,
# listed four times, each a cyclic rotation of the last.  Place.Side selects
# the rotation so a given player keeps the same visual corner as the board
# turns.  Preserved for fidelity; the terminal front-end does not use it.
# --------------------------------------------------------------------------

TOKEN_OFFSETS: tuple[tuple[tuple[int, int], ...], ...] = (
    ((1, 3), (-3, 3), (-3, -1), (1, -1)),
    ((-3, 3), (-3, -1), (1, -1), (1, 3)),
    ((1, -1), (1, 3), (-3, 3), (-3, -1)),
    ((-3, -1), (1, -1), (1, 3), (-3, 3)),
)


# --------------------------------------------------------------------------
# Fixed board positions and amounts referenced by the rules
# --------------------------------------------------------------------------

GO = 0

# The four corner squares: GO, Jail, Free Parking, Go To Jail.
CORNERS = (0, 10, 20, 30)

# The build/return screens do not read a typed name: the original tests a
# single upper-cased keypress against this set (the letters are pushed one at
# a time at CHN 0x93EB..0x941B) and echoes the group's name back.  'N' is the
# way out -- "one... changed my mind."  The screen order is the original's,
# which separates the two Purples rather than listing them together.
GROUP_KEYS = (
    ("L", "LightPurple"),
    ("C", "Cyan"),
    ("D", "DarkPurple"),
    ("O", "Orange"),
    ("R", "Red"),
    ("Y", "Yellow"),
    ("G", "Green"),
    ("B", "Blue"),
)
GROUP_CANCEL_KEY = "N"
JAIL = 10
FREE_PARKING = 20
GO_TO_JAIL = 30

INCOME_TAX = 4
LUXURY_TAX = 38

CHANCE_SQUARES = (7, 22, 36)
CHEST_SQUARES = (2, 17, 33)

RAILROAD_SQUARES = tuple(COLOR_GROUPS[GROUP_RR].members)
UTILITY_SQUARES = tuple(COLOR_GROUPS[GROUP_UTIL].members)

GO_SALARY = 200
JAIL_FINE = 50
LUXURY_TAX_AMOUNT = 75
INCOME_TAX_FLAT = 200
INCOME_TAX_RATE = 10  # per cent

STARTING_CASH = 1500
MAX_PLAYERS = 4
MIN_PLAYERS = 2

# Houses per property before a hotel; "Zoning Regulations allow N units..."
HOUSES_PER_HOTEL = 5


def square(pos: int) -> Square:
    """PLACE[pos] with the board's wraparound applied."""
    return PLACE[pos % 40]


def group_of(pos: int) -> ColorGroup | None:
    g = PLACE[pos % 40].group
    return COLOR_GROUPS[g] if g else None


def find_by_short_name(text: str) -> int | None:
    """Resolve a typed short name to a board position.

    The original stored each short name twice -- mixed case for display and
    uppercase for matching -- because Turbo Pascal 3 had no string-level
    uppercase.  Python does, so the second copy is only carried for fidelity
    and the match happens against it directly.
    """
    key = text.strip().upper()
    if not key:
        return None
    for pos, sq in enumerate(PLACE):
        if sq.ownable and sq.short_uc == key:
            return pos
    # Fall back to an unambiguous prefix of the full name.
    hits = [p for p, s in enumerate(PLACE)
            if s.ownable and s.name.upper().startswith(key)]
    return hits[0] if len(hits) == 1 else None


def find_group(text: str) -> int | None:
    """Resolve a typed color group name.

    The recovered source dispatches on the first letter, which collides for
    Dark/LightPurple and for Green/Cyan; it resolved those by asking for the
    leading D/L/C explicitly.  Matching on a case-insensitive prefix here gives
    the same answers without the special cases.
    """
    key = text.strip().upper()
    if not key:
        return None
    hits = [i for i, g in enumerate(COLOR_GROUPS)
            if g is not None and g.buildable and g.name.upper().startswith(key)]
    return hits[0] if len(hits) == 1 else None

# The property prompt lists short names in a five-row block; the original
# opens a window at columns 12-30, rows 8-12 (CHN 0x7C7F) and fills it.  Each
# row is one pair of colour groups in board order, which is why every row
# comes to exactly eighteen columns: the two browns beside the three light
# blues, the purples beside the oranges, and so on, with the four railroads
# and two utilities sharing the last row.  Names are run together with no
# separator -- "MeditBaltOriVerCon" -- exactly as captured from the real
# program.
SHORT_NAME_ROWS = ((1, 2), (3, 4), (5, 6), (7, 8), (9, 10))
SHORT_NAME_INDENT = 7


def short_name_rows(positions) -> list[str]:
    """Lay the given board positions out the way the original's prompt does."""
    keep = set(positions)
    rows = []
    for groups in SHORT_NAME_ROWS:
        names = ""
        for g in groups:
            names += "".join(PLACE[p].short for p in sorted(keep)
                             if PLACE[p].short and PLACE[p].group == g)
        rows.append(" " * SHORT_NAME_INDENT + names)
    return rows


def color_group_ids() -> list[int]:
    """The eight colour-group indices, in the order the picker lists them."""
    out = []
    for _key, name in GROUP_KEYS:
        for i, g in enumerate(COLOR_GROUPS):
            if g and g.name == name:
                out.append(i)
                break
    return out

# Seven columns of lead-in before each colour-group name: five spaces in the
# panel's own colours and two more the original repaints in the group's
# colours, making a small swatch (CHN 0x9265-0x928E).
GROUP_ROW_INDENT = 7
GROUP_SWATCH_WIDTH = 2
