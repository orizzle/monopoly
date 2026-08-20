"""Mutable game state.

The 1985 program kept three parallel arrays, and the names here are its own,
recovered from the Pascal source left in MONOGRAF.GRA:

    Ply   : array[1..4]  -- the players          (34 bytes each, DS:0x3880)
    Owner : array[1..40] -- per-square ownership (.OwnNum, .Mort, .HH)

`Owner` is indexed by board square rather than by property, so the 12
non-property squares carry inert entries.  That looks wasteful, but it is what
lets every rule path index `Owner[pos]` directly off a token position without
first mapping the square to a property number, and it is reproduced here for
the same reason.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import data
from .tprandom import TurboRandom

BANK = -1  # Owner.OwnNum when a square is unowned

# RandSeed's initial value.  Randomize is never called, so an unmodified copy
# of the original always starts from here.
#
# Measured, not read out of the file: an instrumented DOSBox watching writes
# to RandSeed (DS:0x01FC, and DS is 0x10DC while the chained code runs -- not
# the 0x0192 the code segment sits at) logged 453 draws in a live game, and
# every one of them matches TurboRandom(0).  The first write is 0x361962E9,
# which is 0*129 + 907633385, so the seed going in was zero.
STOCK_SEED = 0


def _turbo_shuffle(rng: TurboRandom, size: int) -> list[int]:
    """The original's descending Fisher-Yates, as a 0-based order."""
    deck = list(range(size))
    for i in range(size, 1, -1):          # for i := size downto 2
        j = rng.random(i) + 1             # j := Random(i) + 1
        deck[i - 1], deck[j - 1] = deck[j - 1], deck[i - 1]
    return deck


@dataclass
class PropertyState:
    """Owner[n] -- the mutable half of a board square."""

    owner: int = BANK  # OwnNum: index into GameState.players
    mortgaged: bool = False  # Mort
    houses: int = 0  # HH: 0-4 houses, 5 = hotel

    @property
    def has_hotel(self) -> bool:
        return self.houses == data.HOUSES_PER_HOTEL


@dataclass
class Player:
    """Ply[n]."""

    name: str
    cash: int = data.STARTING_CASH
    position: int = data.GO
    in_jail: bool = False
    jail_turns: int = 0
    jail_cards: int = 0
    bankrupt: bool = False

    # The bank's short-term overdraft: "I WILL LOAN UNTIL YOUR TURN", cleared
    # before the player may move again.
    loan: int = 0

    @property
    def display(self) -> str:
        return self.name


@dataclass
class GameState:
    players: list[Player]
    props: list[PropertyState] = field(
        default_factory=lambda: [PropertyState() for _ in range(40)])

    current: int = 0
    dice: tuple[int, int] = (0, 0)
    doubles_run: int = 0
    # Display only: the board titles a repeat roll "<name> again"
    # instead of "<name>'s turn".  Kept apart from doubles_run because
    # the captures show the change landing at the start of the repeat
    # roll, not the moment the doubles are thrown.
    again: bool = False

    # Card decks are shuffled once and drawn round-robin, so a card cannot
    # reappear until the deck has been exhausted.
    chance_order: list[int] = field(default_factory=list)
    chest_order: list[int] = field(default_factory=list)
    chance_next: int = 0
    chest_next: int = 0

    sound: bool = True
    rng_seed: int = 0

    # The 1985 generator itself, shared with the Game so that draws happen in
    # one order across shuffles, dice and card draws.
    rng: TurboRandom = field(default_factory=lambda: TurboRandom(STOCK_SEED))

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------

    @classmethod
    def new_game(cls, names: list[str], seed: int | None = None) -> "GameState":
        """Start a game on the 1985 generator.

        The seed defaults to STOCK_SEED, the value baked into MONOPOLY.COM,
        because the original never calls Randomize -- so that seed is the one
        a real copy actually starts from.
        """
        if seed is None:
            seed = random.Random().randrange(1 << 32)
        state = cls(players=[Player(n) for n in names])
        state.rng_seed = seed
        state.rng = TurboRandom(seed)
        state.reshuffle(state.rng)
        # The board always has dice on it, even before anyone has rolled.
        state.dice = (state.rng.die(), state.rng.die())
        return state

    def reshuffle(self, rng: "TurboRandom") -> None:
        """Shuffle both decks the way the original does.

        Decompiled from MONOCODE.CHN at 0x1F03 and 0x1F8C, which are the same
        loop twice over: the deck is filled 1..16, then

            for i := 16 downto 2 do
              begin j := Random(i) + 1; swap(deck[i], deck[j]) end

        a descending Fisher-Yates costing fifteen draws per deck.  Both decks
        holding exactly sixteen cards is independent confirmation of the
        reading.  Which of the two loops shuffles Chance and which Community
        Chest is not determined by the disassembly, so Chance is taken first;
        it changes which card each draw yields, not the dice.
        """
        from . import cards

        self.chance_order = _turbo_shuffle(rng, len(cards.CHANCE))
        self.chest_order = _turbo_shuffle(rng, len(cards.COMMUNITY_CHEST))
        self.chance_next = self.chest_next = 0

    # ------------------------------------------------------------------
    # players
    # ------------------------------------------------------------------

    @property
    def player(self) -> Player:
        return self.players[self.current]

    @property
    def active(self) -> list[int]:
        return [i for i, p in enumerate(self.players) if not p.bankrupt]

    def next_player(self) -> None:
        if len(self.active) <= 1:
            return
        i = self.current
        for _ in range(len(self.players)):
            i = (i + 1) % len(self.players)
            if not self.players[i].bankrupt:
                self.current = i
                return

    def owner_of(self, pos: int) -> int:
        return self.props[pos].owner

    def holdings(self, player: int) -> list[int]:
        """Board positions owned by a player, in board order."""
        return [p for p in range(40) if self.props[p].owner == player]

    # ------------------------------------------------------------------
    # cards
    # ------------------------------------------------------------------

    def draw_chance(self) -> int:
        i = self.chance_order[self.chance_next]
        self.chance_next = (self.chance_next + 1) % len(self.chance_order)
        return i

    def draw_chest(self) -> int:
        i = self.chest_order[self.chest_next]
        self.chest_next = (self.chest_next + 1) % len(self.chest_order)
        return i
