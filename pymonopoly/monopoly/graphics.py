"""CGA 320x200 four-colour graphics -- the mode the board is drawn in.

The original runs almost entirely in 80x25 text, but switches the display to
CGA graphics for the board itself and switches back for menus and title deed
cards.  This module is that second display.

The board artwork is not reproduced here.  It lives in MONOGRAF.GRA, which
ships with the original game, and `load_board()` reads it from a copy the user
already has.  Without that file the port falls back to the text-mode board in
screens.draw_board().

Format, recovered by decoding and then diffing against the emulator:

    offset 0   word  2        (count -- two figures in the file)
    offset 2   word  123      width in pixels
    offset 4   word  123      height in pixels
    offset 6   123 rows of 31 bytes, four pixels per byte, two bits each,
                  high bits leftmost, **rows stored bottom to top**

Decoded that way and blitted at (0, 0) it matches a capture of the running
program to within the nine pixels of the player tokens drawn over it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image

from . import diceart
import math
import struct
from pathlib import Path

from .cga import FONT, _encode

WIDTH = 320
HEIGHT = 200
COLS = WIDTH // 8  # 40 columns of 8x8 text in graphics mode
ROWS = HEIGHT // 8

# CGA palette 1, high intensity: the four colours the board uses.
PALETTE: tuple[tuple[int, int, int], ...] = (
    (0x00, 0x00, 0x00),  # 0 background (black)
    (0x55, 0xFF, 0xFF),  # 1 light cyan
    (0xFF, 0x55, 0xFF),  # 2 light magenta
    (0xFF, 0xFF, 0xFF),  # 3 white
)

BLACK, CYAN, MAGENTA, WHITE = 0, 1, 2, 3

DEFAULT_ASSET = "MONOGRAF.GRA"


class MissingArtwork(Exception):
    """MONOGRAF.GRA was not found; the caller should fall back to text mode."""


def load_board(path: str | Path = DEFAULT_ASSET) -> list[list[int]]:
    """Decode the board figure from the original's graphics file.

    Returns a height-by-width grid of palette indices.
    """
    p = Path(path)
    if not p.exists():
        raise MissingArtwork(f"{p} not found")
    raw = p.read_bytes()
    if len(raw) < 6:
        raise ValueError("graphics file is truncated")

    _count, width, height = struct.unpack_from("<3H", raw, 0)
    if not (0 < width <= WIDTH and 0 < height <= HEIGHT):
        raise ValueError(f"implausible figure size {width}x{height}")

    stride = (width * 2 + 7) // 8
    need = 6 + stride * height
    if len(raw) < need:
        raise ValueError("graphics file too short for its declared size")

    rows: list[list[int]] = []
    for y in range(height):
        line = raw[6 + y * stride:6 + (y + 1) * stride]
        rows.append([(line[x // 4] >> (6 - 2 * (x % 4))) & 3
                     for x in range(width)])
    rows.reverse()  # stored bottom-to-top
    return rows


class GraphicsScreen:
    """A 320x200 frame of palette indices, with 8x8 text on top."""

    __slots__ = ("pixels",)

    def __init__(self) -> None:
        self.pixels = [[0] * WIDTH for _ in range(HEIGHT)]

    def point(self, x: int, y: int, color: int) -> None:
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            self.pixels[y][x] = color

    def clear(self, color: int = BLACK) -> None:
        for row in self.pixels:
            for x in range(WIDTH):
                row[x] = color

    def blit(self, art: list[list[int]], x0: int = 0, y0: int = 0,
             transparent: int | None = None) -> None:
        for dy, row in enumerate(art):
            y = y0 + dy
            if not 0 <= y < HEIGHT:
                continue
            dest = self.pixels[y]
            for dx, v in enumerate(row):
                x = x0 + dx
                if 0 <= x < WIDTH and v != transparent:
                    dest[x] = v

    def text(self, col: int, row: int, s: str, color: int = CYAN,
             background: int | None = None) -> None:
        """Draw text on the 40x25 character grid, 1-based like the text mode."""
        for i, ch in enumerate(s):
            self._glyph(col + i, row, _encode(ch), color, background)

    def _glyph(self, col: int, row: int, code: int, color: int,
               background: int | None) -> None:
        if not (1 <= col <= COLS and 1 <= row <= ROWS):
            return
        x0, y0 = (col - 1) * 8, (row - 1) * 8
        glyph = FONT[code]
        for gy in range(8):
            bits = glyph[gy]
            dest = self.pixels[y0 + gy]
            for gx in range(8):
                if bits & (0x80 >> gx):
                    dest[x0 + gx] = color
                elif background is not None:
                    dest[x0 + gx] = background

    def centered_text(self, row: int, s: str, color: int = CYAN,
                      left: int = 1, right: int = COLS) -> None:
        col = left + ((right - left + 1) - len(s)) // 2
        self.text(col, row, s, color)

    # -- output ------------------------------------------------------------

    def render(self, scale: int = 1) -> "Image":
        from PIL import Image

        buf = bytearray(WIDTH * HEIGHT * 3)
        o = 0
        for row in self.pixels:
            for v in row:
                r, g, b = PALETTE[v]
                buf[o] = r
                buf[o + 1] = g
                buf[o + 2] = b
                o += 3
        img = Image.frombytes("RGB", (WIDTH, HEIGHT), bytes(buf))
        if scale != 1:
            img = img.resize((WIDTH * scale, HEIGHT * scale), Image.NEAREST)
        return img

    def save_png(self, path: str, scale: int = 1) -> None:
        self.render(scale).save(path)


def find_asset(*candidates: str | Path) -> Path | None:
    """Locate MONOGRAF.GRA among the usual places."""
    seen: list[Path] = []
    for c in candidates:
        seen.append(Path(c))
    seen += [Path(DEFAULT_ASSET),
             Path.cwd() / DEFAULT_ASSET,
             Path.cwd() / "game" / DEFAULT_ASSET,
             Path(__file__).resolve().parents[2] / "game" / DEFAULT_ASSET,
             Path(__file__).resolve().parents[2] / "extracted" / "monopoly"
             / DEFAULT_ASSET]
    for p in seen:
        if p.exists():
            return p
    return None


# --------------------------------------------------------------------------
# The board screen
#
# Square geometry was read off the figure itself: its magenta divider lines
# fall at pixels 16, 26, 36 ... 106, so the nine middle squares on each edge
# are ten pixels wide and the corners are wider.  Token positions were then
# measured against captures -- players sit two and six pixels in from their
# square's leading edge, four pixels apart, which matches the spacing in the
# 32-word offset table at file 0x1C1F of MONOCODE.CHN.
# --------------------------------------------------------------------------

DIVIDERS = (0, 16, 26, 36, 46, 56, 66, 76, 86, 96, 106, 123)

TOKEN_SIZE = 3

# Where a jailed piece sits inside the jail cell.  Measured from a lossless
# capture of a real jailing rather than from the AVI, whose JPEG smear is no
# use for a one-pixel question: the piece occupies x 9..11, y 112..114 of the
# 123x123 figure, whose bottom-left cell starts at (0, 106).  The player it
# belonged to was the first, so lane 0 and seat 1 -- hence the inset of 2
# below, which the seat's four pixels carry to the measured 112.  Only the
# one-piece case is measured; the seat and lane terms are kept because every
# other branch stacks pieces that way.
JAIL_INSET_X = 9
JAIL_INSET_Y = 2
TOKEN_STEP = 4

# Each player gets a distinct 3x3 piece.  All four were read off a capture of
# a four-player game; they are not variations on one shape.
#
# Which piece belongs to whom was measured rather than assumed, by stepping
# through 415 captured board screens and watching which shape moves while a
# given player's name is in the title: ann moves the solid block, ben the
# hollow square, cid the diamond, dot the plus.  The pairs used to be the
# other way round here, which is invisible to a screen-by-screen diff -- the
# audit reads pieces with these same tables, so it matched a swapped pair
# happily -- but it puts the wrong piece on the board for a named player, and
# it put the wrong one in the jail cell.  The swap is within each pair, which
# is the same 1-based parity that decides `seat` below.
TOKEN_SHAPES: tuple[tuple[str, ...], ...] = (
    ("###",
     "###",
     "###"),   # first player -- solid block
    ("###",
     "#.#",
     "###"),   # second player -- hollow square
    (".#.",
     "#.#",
     ".#."),   # third player -- diamond
    (".#.",
     "###",
     ".#."),   # fourth player -- plus
)
TOKEN_INSET = 2
TOKEN_EDGE = 1     # pixels in from the board's outer border
TOKEN_REVERSE = 6  # leading seat where the order runs backwards
TOKEN_CORNER = 12  # leading seat in the two top corners

# Text is laid out on the 40-column grid to the right of the board figure.
TEXT_LEFT = 16
TEXT_RIGHT = COLS
TITLE_ROW = 1
LABEL_ROW = 3        # where CHANCE / COMMUNITY CHEST appear, in place of the dice
MESSAGE_ROW = 8
CASH_NAME_ROW = 24
CASH_MONEY_ROW = 25
# The cash blocks are ten columns each and the whole row is centred, so where
# they start depends on how many are playing: two players begin at column 13,
# four at column 3.  Both measured from captures.
CASH_STEP = 10

# The name is centred over its money column in a seven-column field, rounding
# down, so a name longer than seven characters overhangs to the left rather
# than pushing right.  Solved from three- and four-player captures using names
# of different lengths: "benjamin" (8 letters) starts one column *before* its
# own money column, which rules out both left- and right-alignment.
CASH_FIELD = 7
CASH_AMOUNT_WIDTH = 4   # figures right-align within four columns


def cash_origin(players: int) -> int:
    return (COLS - CASH_STEP * players) // 2 + 3


def cell_bounds(col: int, row: int) -> tuple[int, int, int, int]:
    """Pixel bounds of ring cell (col, row) on the 11x11 board."""
    return (DIVIDERS[col], DIVIDERS[row],
            DIVIDERS[col + 1] - 1, DIVIDERS[row + 1] - 1)


def _centre_up(s: str, left: int = TEXT_LEFT, right: int = TEXT_RIGHT) -> int:
    return left + ((right - left + 1) - len(s) + 1) // 2


def _centre_down(s: str, left: int = TEXT_LEFT, right: int = TEXT_RIGHT) -> int:
    """The card label rounds the other way from the title and message."""
    return left + ((right - left + 1) - len(s)) // 2


class BoardScreen(GraphicsScreen):
    """The board plus the text the original prints beside it."""

    def __init__(self, board: list[list[int]]) -> None:
        super().__init__()
        self.board = board

    def draw(self, title: str, message: list[str],
             players: list[tuple[str, int, int]],
             dice: tuple[int, int] | None = None,
             hide: "set[int] | tuple[int, ...]" = (),
             tumble: "int | tuple[int, int] | None" = None,
             label: str = "") -> None:
        """`players` is a list of (name, cash, board position).

        `hide` omits those players' tokens, which is how the blink after a
        landing is produced -- the original redraws the board with the piece
        left out rather than inverting it.
        """
        self.clear()
        self.blit(self.board, 0, 0)
        # A card square puts its name where the dice sit, in magenta, and the
        # dice are not drawn at all while it shows.
        if label:
            self.text(_centre_down(label), LABEL_ROW, label, MAGENTA)
        elif tumble is not None:
            if isinstance(tumble, tuple):
                draw_tumbling_dice(self, tumble[0], tumble[1])
            else:
                draw_tumbling_dice(self, tumble)
        elif dice:
            draw_dice(self, *dice)

        for i, seat in enumerate(players):
            pos = seat[2]
            jailed = bool(seat[3]) if len(seat) > 3 else False
            if i not in hide:
                self.token(pos, i, jailed)

        if title:
            self.text(_centre_up(title), TITLE_ROW, title, WHITE)
        for n, line in enumerate(message):
            if not line:
                continue
            # A placed run -- (col, row, text[, colour]) -- goes exactly where
            # it is put.  The jail prompt needs this: unlike a landing
            # message it is left-aligned at column 19, and its hot keys are a
            # different colour from the words around them.
            if isinstance(line, tuple):
                col, row, text = line[0], line[1], line[2]
                self.text(col, row, text, line[3] if len(line) > 3 else CYAN)
            else:
                self.text(_centre_up(line), MESSAGE_ROW + n, line, CYAN)

        origin = cash_origin(len(players))
        for i, seat in enumerate(players):
            name, cash = seat[0], seat[1]
            base = origin + i * CASH_STEP
            self.text(base + (CASH_FIELD - len(name)) // 2,
                      CASH_NAME_ROW, name, WHITE)
            # The figure is right-aligned, always ending at base+5; only the
            # dollar sign is fixed.  Four-digit amounts hide this -- it shows
            # up the moment someone drops to three.
            self.text(base, CASH_MONEY_ROW, "$", WHITE)
            figure = str(cash)
            self.text(base + 2 + (CASH_AMOUNT_WIDTH - len(figure)),
                      CASH_MONEY_ROW, figure, WHITE)

    def token(self, pos: int, player: int, jailed: bool = False) -> None:
        """Draw one player's piece on its square.

        Pieces pack two-by-two inside a square: `seat` places them along the
        direction of travel, `lane` steps inward.  The seat order reverses on
        the top and right edges, so the pieces keep a consistent order going
        round the board rather than mirroring at the corners -- measured
        across 415 captured board screens, and the reason an earlier version
        that extrapolated the bottom edge was wrong on half the board.
        """
        from .screens import _ring_cell

        col, row = _ring_cell(pos)
        x0, y0, x1, y1 = cell_bounds(col, row)
        # Pascal counts its players from 1, and the seat comes off that index
        # directly -- `seat := p mod 2` -- while the lane comes off the
        # zero-based one, `lane := (p - 1) div 2`.  So the first player takes
        # seat 1 and the second seat 0, which is the opposite way round from
        # the `player % 2` this used.
        #
        # Measured from a two-player game captured frame by frame: the first
        # player walks the left edge at y0+6 (112, 102, 92, 72, 52, 42, 22 --
        # every one a cell boundary plus six) and the top edge at x0+2, while
        # the second walks the left edge at y0+2 (98, 88, 78) and sits on the
        # bottom edge at x0+2.  Both pieces, over dozens of frames, are one
        # step from where this port drew them.
        seat = (player + 1) % 2
        lane = player // 2
        fwd = TOKEN_INSET + TOKEN_STEP * seat        # 2, 6
        rev = TOKEN_REVERSE - TOKEN_STEP * seat      # 6, 2

        if jailed:
            # Inside the bars.  Measured by diffing a board with a player in
            # jail against the same board without one: the mark moves to
            # pixels x 8..12, y 112..115 of the 123x123 figure, which is the
            # inside of the jail cell rather than the visiting edge.  The
            # placement routine's coordinates come from the square alone, so
            # this is drawn on top of them, and an earlier reading of that
            # routine wrongly concluded there was no jail case at all.
            x = x0 + JAIL_INSET_X + TOKEN_STEP * lane
            y = y0 + JAIL_INSET_Y + TOKEN_STEP * seat
        elif row == 10 and col == 0:                 # bottom-left corner
            x = x0 + TOKEN_EDGE + TOKEN_STEP * lane
            y = y0 + fwd
        elif row == 10:                              # bottom edge and GO
            x = x0 + fwd
            y = y1 - TOKEN_SIZE - TOKEN_STEP * lane
        elif row == 0 and col == 0:                  # top-left corner
            x = x0 + TOKEN_CORNER - TOKEN_STEP * seat
            y = y0 + TOKEN_EDGE + TOKEN_STEP * lane
        elif row == 0 and col == 10:                 # top-right corner
            x = x1 - TOKEN_SIZE - TOKEN_STEP * lane
            y = y0 + TOKEN_CORNER - TOKEN_STEP * seat
        elif row == 0:                               # top edge
            x = x0 + rev
            y = y0 + TOKEN_EDGE + TOKEN_STEP * lane
        elif col == 0:                               # left edge
            x = x0 + TOKEN_EDGE + TOKEN_STEP * lane
            y = y0 + fwd
        else:                                        # right edge
            x = x1 - TOKEN_SIZE - TOKEN_STEP * lane
            y = y0 + rev

        # The piece is opaque: its blank cells are painted black rather than
        # letting the board show through.
        shape = TOKEN_SHAPES[player % len(TOKEN_SHAPES)]
        for dy, srow in enumerate(shape):
            for dx, cell in enumerate(srow):
                self.point(x + dx, y + dy,
                           MAGENTA if cell == "#" else BLACK)



# --------------------------------------------------------------------------
# Dice
#
# The original draws two 3D wireframe cubes overlaid on the board, animating
# them while the roll is in progress.  Geometry below is measured from
# captures: the front face is a 16x16 square outline, the back face is offset
# five pixels sideways, and three corner edges join the two.  The rear top and
# far side edges are not drawn -- they would be hidden by the front face.
#
# The two dice mirror each other: the left one recedes down-left, the right
# one down-right.
#
#     front face          (x0, y0) .. (x0+15, y0+15)
#     top corner edge     (x0, y0)      -> (x0-5, y0+10)
#     bottom corner edges (x0, y0+15)   -> (x0-5, y0+23)
#                         (x0+15, y0+15)-> (x0+10, y0+23)
#     back side edge      x0-5, rows y0+10 .. y0+23
#     back bottom edge    y0+23, x0-5 .. x0+10
# --------------------------------------------------------------------------

DIE_FACE = 16
DIE_DEPTH = 5
DIE_TOP_DROP = 10
DIE_BOTTOM_DROP = 8
DIE_HEIGHT = DIE_FACE + DIE_BOTTOM_DROP  # 24 rows overall

# Front-face top-left corners, and the row both dice sit on.
DIE_LEFT_X = 203
DIE_RIGHT_X = 235
DIE_Y = 20

# Pip centres, relative to the front face's top-left corner.
PIP_COLS = (5, 8, 11)
PIP_ROWS = (4, 7, 10)

# (column index, row index) pairs per face.  Five and six are measured from
# captures; the rest follow the conventional arrangement, since no capture
# happened to show them.
PIP_LAYOUT: dict[int, tuple[tuple[int, int], ...]] = {
    1: ((1, 1),),
    2: ((0, 0), (2, 2)),
    3: ((0, 0), (1, 1), (2, 2)),
    4: ((0, 0), (2, 0), (0, 2), (2, 2)),
    5: ((0, 0), (2, 0), (1, 1), (0, 2), (2, 2)),
    6: ((0, 0), (2, 0), (0, 1), (2, 1), (0, 2), (2, 2)),
}


def _line(screen: "GraphicsScreen", x0: int, y0: int, x1: int, y1: int,
          color: int) -> None:
    """A line stepped along y, rounding halves upward.

    Matches the pixels in the captures; a general Bresenham walk rounds the
    other way on exact halves and lands one pixel off.
    """
    if y1 == y0:
        for x in range(min(x0, x1), max(x0, x1) + 1):
            screen.point(x, y0, color)
        return
    dy = y1 - y0
    for step in range(abs(dy) + 1):
        y = y0 + (step if dy > 0 else -step)
        # floor, not int(): the offsets run negative and int() would
        # truncate toward zero and skew the line.
        x = math.floor(x0 + (x1 - x0) * step / abs(dy) + 0.5)
        screen.point(x, y, color)


def _wireframe(width: int = DIE_FACE, height: int = DIE_FACE,
               depth: int = DIE_DEPTH) -> dict[tuple[int, int], int]:
    """The die's pixels, keyed by offset from the front face's top-left.

    Built in the left-hand orientation; the right-hand die is an exact
    horizontal reflection, checked against captures.

    Width, height and depth are separate because the tumble turns the cube
    rather than scaling it: the narrow poses keep their full height and pull
    the face in, which is what makes them read as edge-on.  Measured from a
    20 fps recording -- the wide pose is a 16x16 face over depth 5 (bounding
    box 21x24) and the narrow one a 13x16 face over depth 2 (15x25).
    """
    cells: dict[tuple[int, int], int] = {}

    class _Plot:
        @staticmethod
        def point(x, y, color):
            cells[(x, y)] = color

    w = width - 1
    h = height - 1
    d = -depth
    far, near = 0, w

    _line(_Plot, 0, 0, w, 0, MAGENTA)
    _line(_Plot, 0, h, w, h, MAGENTA)
    for y in range(0, h + 1):
        cells[(0, y)] = MAGENTA
        cells[(w, y)] = MAGENTA

    _line(_Plot, far, 0, far + d, DIE_TOP_DROP, MAGENTA)
    _line(_Plot, far, h, far + d, h + DIE_BOTTOM_DROP, MAGENTA)
    _line(_Plot, near, h, near + d, h + DIE_BOTTOM_DROP, MAGENTA)

    for y in range(DIE_TOP_DROP, h + DIE_BOTTOM_DROP + 1):
        cells[(far + d, y)] = MAGENTA
    _line(_Plot, far + d, h + DIE_BOTTOM_DROP, near + d, h + DIE_BOTTOM_DROP,
          MAGENTA)
    return cells


def draw_die(screen: "GraphicsScreen", x0: int, y0: int, value: int,
             mirrored: bool = False, width: int = DIE_FACE,
             height: int = DIE_FACE, depth: int = DIE_DEPTH,
             show_pips: bool = True) -> None:
    """One wireframe die, with (x0, y0) the front face's top-left corner.

    `show_pips` is false while the die is still turning: the original draws no
    pips at all until it settles.
    """
    w = width - 1
    for (dx, dy), color in _wireframe(width, height, depth).items():
        screen.point(x0 + (w - dx if mirrored else dx), y0 + dy, color)

    if show_pips:
        for col, row in PIP_LAYOUT.get(value, ()):
            screen.point(x0 + PIP_COLS[col], y0 + PIP_ROWS[row], WHITE)


def draw_dice(screen: "GraphicsScreen", a: int, b: int) -> None:
    """Both dice, in the position the original puts them."""
    draw_die(screen, DIE_LEFT_X, DIE_Y, a, mirrored=False)
    draw_die(screen, DIE_RIGHT_X, DIE_Y, b, mirrored=True)


# --------------------------------------------------------------------------
# Movement
#
# A token does not jump to its destination.  Captured at four frames a second
# during a roll, the moving piece appears one square further along in each
# frame -- ten pixels per square on the bottom edge, matching the divider
# spacing -- and once it arrives it blinks: present, present, absent,
# repeating, until the turn moves on.
#
# The timings below are as close as 250 ms sampling can pin them, so they are
# the right shape rather than exact frame counts.
# --------------------------------------------------------------------------

# A cube redraws every 83 ms -- measured from a 59.92 fps capture of the real
# program, where the two-die box changes every 41.5 ms because the cubes take
# turns.  That matches the speaker exactly: each cube's three clicks come
# round on the same 41.5 ms beat, so a cube's own beat is twice that.  The
# earlier 63 ms came from a 20 fps recording, whose 50 ms resolution could
# not separate the two cubes.
TUMBLE_HOLD_MS = 83

# The cash counter moves $5 at a time, about 19 ms a step -- measured from
# the cash variable and the speaker together while the original played.
CASH_STEP_AMOUNT = 5
CASH_STEP_MS = 19

# Measured off the speaker with MONO_LOGIO: the 900->800 chirps a travelling
# piece makes come 373.7 ms apart on average (min 371.9, max 375.1) over ten
# consecutive squares.  The Delay(400) in the source is not what the machine
# does with it.
STEP_MS = 374   # one square per step while travelling
# A corner chimes for 707 ms and only then takes its ordinary step delay, so
# the piece rests on GO, Jail, Free Parking or Go To Jail for nearly three
# times as long as on any other square.  That pause is audible and visible,
# and the port used to run the chime under the next step instead.
CORNER_MS = 707

# The piece flashes while the square it has landed on is announced, and a
# card that moves it flashes it again before it sets off: ten cycles of three
# blits with a beep on each.  Same loop as the landing flash below, so the
# same figures -- 30 blits of 37.5 ms.  The 72 ms this used to say was never
# measured; every chime in every capture is 37.5 ms a note (see FLASH_TOGGLE_MS).
ADVANCE_BLITS = 30
ADVANCE_BLIT_MS = 37.5

# The piece flashes once the dice stop, not while they tumble.  Measured from
# a 59.92 fps capture: through the whole roll the only thing moving on the
# board is the dice, and the piece toggles about thirty times at ~37 ms only
# after the roll ends, under the chime.
# Delay(1200) between "YOU MUST RAISE SOME MONEY." and the verdict (CHN load
# 0x5950); the trace shows 1.36 s between the last beep and the falling tone.
RAISE_PAUSE_MS = 1200

# "You have rolled 3 / times and must pay." stays on the board for a beat
# before it is wiped and the $50 is taken: Sound(440), Delay(300), NoSound,
# Delay(1000) at CHN load 0xE271.  The speaker log of a game loaded straight
# into jail puts the note at 57.04 s and holds it 280 ms, so the coded 300 is
# right and the whole beat is 1.3 s.
JAIL_FINE_MS = 1300

# A roll out of jail leaves its dice on the board for a full second before
# anything else happens.  CHN load 0xE1BB, immediately after the tumble loop
# stops and the faces are drawn: Delay(1000), and only then is the throw
# tested for doubles.  Without it a failed roll flicked past so fast that the
# turn appeared to end the moment the key went down.
JAIL_ROLL_PAUSE_MS = 1000

# Houses go up and come down one at a time, each with the title deed of the
# square receiving it drawn on the right and its own burst of sound.  Both
# loops are at CHN load 0x9FBA (buying) and 0x9932 (returning); the periods
# are measured off the speaker of a run that bought six units and sold them
# again -- six bursts 514 ms apart going up, six 464 ms apart coming down.
BUILD_UNIT_MS = 514
RETURN_UNIT_MS = 464

# The jail prompt is drawn on the board, not in a text panel.  Measured off a
# board capture of a game loaded straight into jail, and the gotoxy calls in
# the routine agree: the question at column 19 row 5, the options at rows 7
# and 8 (and 9 when a Get Out of Jail Free card is held), all left-aligned at
# column 19 rather than centred the way a landing message is.
#
# Every option string runs exactly eight characters before its hot letter --
# "Want to ", "     or ", " or use " -- so P, R and C all land on column 27.
# In the capture the words are colour 1 (cyan) and the hot letters colour 2
# (magenta), against the title and cash row in colour 3 (white).
JAIL_PROMPT_COL = 19
JAIL_PROMPT_ROW = 5
JAIL_OPTION_ROW = 7
JAIL_HOTKEY_COL = 27


def jail_prompt(cards: bool = False):
    """The in-jail question and its options, as placed board runs."""
    rows = [(JAIL_PROMPT_COL, JAIL_PROMPT_ROW, "You are in JAIL.", CYAN)]
    options = [("Want to ", "P", "ay $50?"), ("     or ", "R", "oll?")]
    if cards:
        options.append((" or use ", "C", "ard?"))
    for n, (lead, key, rest) in enumerate(options):
        row = JAIL_OPTION_ROW + n
        rows.append((JAIL_PROMPT_COL, row, lead, CYAN))
        rows.append((JAIL_HOTKEY_COL, row, key, MAGENTA))
        rows.append((JAIL_HOTKEY_COL + 1, row, rest, CYAN))
    return rows

FLASH_TOGGLES = 30
FLASH_TOGGLE_MS = 37.5
# The flash where the piece lands, from the loop at 0x5143 -- ten passes of
# three blits, one note per blit.  Timed off the speaker, which resolves the
# loop far better than a 59.92 fps capture can: across 101 chime runs in every
# capture on disk the note length is a single population, median 37.49 ms, so
# the flash is 30 blits and ~1125 ms.  See sound.CUES["landing"].
BLINK_ON_MS = 72    # piece shown
BLINK_OFF_MS = 72   # piece hidden
BLINK_CYCLES = 15   # 15 x 2 blits = the 30 the chime covers


def move_path(start: int, steps: int) -> list[int]:
    """The squares a token passes through, excluding where it started."""
    return [(start + n) % 40 for n in range(1, steps + 1)]


# --------------------------------------------------------------------------
# The tumble
#
# While the roll is in progress the dice are redrawn each frame as blank
# cubes -- no pips at all -- in alternating orientations, and only settle into
# the pipped face at the end.  The poses below are measured from a 20 fps
# recording of the original: the front face alternates between sixteen and
# thirteen pixels across, the wide form sits at x=203 or x=200, and the narrow
# one at x=202 with its top edge dropping to y=22 or y=24.
#
# The order the original cycles them in looks irregular and may be random;
# this cycles the measured poses deterministically instead.
# --------------------------------------------------------------------------

# Tumble poses, measured from every pip-less die image in a five-minute
# recording -- seven orientations, each appearing 51-64 times.  A pose is two
# squares: a front face and a back face reached by a horizontal offset `d`
# and two vertical drops `t` and `b`.  The back is not a translated copy: its
# top and bottom recede by different amounts, which is why a plain
# two-rectangle model cannot express the family the settled die belongs to.
#
# `corners` lists which of the four corner edges join front to back, and
# `round_up` picks how a diagonal resolves an exact half -- both measured per
# pose rather than assumed, because no single rule fits all of them.
#
# One further orientation exists (front at -4,+12, size 13, d=+3) which this
# model reproduces to within five pixels; it is left out rather than shipped
# wrong.  It never survives screen de-duplication, so nothing on screen
# depends on it.

TUMBLE_POSES: tuple[dict, ...] = (
    dict(dx=0,  dy=0,  sz=16, d=-5, t=10,  b=8,   corners=("TL","BL","BR"), round_up=True),
    dict(dx=7,  dy=12, sz=13, d=-8, t=-12, b=-12, corners=("TL","TR","BL"), round_up=True),
    dict(dx=-3, dy=0,  sz=16, d=5,  t=10,  b=8,   corners=("TR","BL","BR"), round_up=False),
    dict(dx=1,  dy=10, sz=13, d=4,  t=-12, b=-12, corners=("TL","TR","BR"), round_up=True),
    dict(dx=1,  dy=14, sz=13, d=-2, t=-12, b=-12, corners=("TL","TR","BL"), round_up=False),
    dict(dx=2,  dy=16, sz=13, d=-3, t=-12, b=-12, corners=("TL","TR","BL"), round_up=False),
)


def _tumble_line(x0, y0, x1, y1, round_up, plot):
    if y1 == y0:
        for x in range(min(x0, x1), max(x0, x1) + 1):
            plot(x, y0)
        return
    n = abs(y1 - y0)
    sy = 1 if y1 > y0 else -1
    for s in range(n + 1):
        v = x0 + (x1 - x0) * s / n
        x = math.floor(v + 0.5) if round_up else math.ceil(v - 0.5)
        plot(x, y0 + sy * s)


def draw_tumble_pose(screen: "GraphicsScreen", x0: int, y0: int,
                     pose: dict, mirrored: bool = False) -> None:
    """One die mid-roll: a blank cube, no pips."""
    sz, d, t, b = pose["sz"], pose["d"], pose["t"], pose["b"]
    cells: set[tuple[int, int]] = set()
    plot = lambda x, y: cells.add((x, y))

    for x in range(sz):
        cells.add((x, 0)); cells.add((x, sz - 1))
    for y in range(sz):
        cells.add((0, y)); cells.add((sz - 1, y))

    side = d if d < 0 else d + sz - 1
    lo, hi = sorted((t, sz - 1 + b))
    for y in range(lo, hi + 1):
        cells.add((side, y))
    edge_y = t if t < 0 else sz - 1 + b
    for x in range(d, d + sz):
        cells.add((x, edge_y))

    corner = {"TL": (0, 0), "TR": (sz - 1, 0),
              "BL": (0, sz - 1), "BR": (sz - 1, sz - 1)}
    drop = {"TL": t, "TR": t, "BL": b, "BR": b}
    for k in pose["corners"]:
        cx, cy = corner[k]
        _tumble_line(cx, cy, cx + d, cy + drop[k], pose["round_up"], plot)

    for cx, cy in cells:
        screen.point(x0 + (sz - 1 - cx if mirrored else cx), y0 + cy, MAGENTA)


def draw_tumbling_dice(screen: "GraphicsScreen", phase: int,
                       right_phase: int | None = None) -> None:
    """Both dice mid-roll.

    The two dice turn independently -- a captured frame shows one already
    settled while the other is still going -- so each takes its own phase.
    """
    rp = (phase + 3) if right_phase is None else right_phase
    _blit_tumble_art(screen, phase, 0)
    _blit_tumble_art(screen, rp, 1)


def _blit_tumble_art(screen: "GraphicsScreen", phase: int, side: int) -> None:
    """Stamp one of the original's stored die drawings.

    The program does not compute a cube: it picks a picture with Random(8)
    from a table and blits it, so the port has to stamp the same pictures or
    it draws poses the original never shows.  A dot leaves the board alone --
    the drawings are not rectangular, and the board shows through around the
    corners of the die.
    """
    art = diceart.TUMBLE_ART[phase % len(diceart.TUMBLE_ART)]
    x0 = diceart.ART_ORIGIN[0] + side * diceart.ART_SPACING
    y0 = diceart.ART_ORIGIN[1]
    for dy, row in enumerate(art):
        for dx, ch in enumerate(row):
            if ch != ".":
                screen.point(x0 + dx, y0 + dy, int(ch))
