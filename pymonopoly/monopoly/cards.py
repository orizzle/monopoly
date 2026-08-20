"""Chance and Community Chest decks.

The 1985 program held its two decks as inline string literals inside the card
procedures rather than as a table, so each card had to be recovered from the
strings embedded in MONOCODE.CHN around file offsets 0x7DA2-0x94D3.  The
effects below are modelled as data; the wording is this port's own.

Three amounts could not be read off the binary because the string and the
number were emitted separately and only the caption survived intact -- the
inheritance, the service fee and the hospital fee.  Those are marked
`RECOVERED_PARTIAL` and carry the conventional values.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import data

RECOVERED_PARTIAL = "amount not recoverable from the binary; conventional value used"


# --------------------------------------------------------------------------
# Card effects
#
# Each card names an action plus its parameters.  The turn loop in game.py
# interprets them; keeping them declarative means the save file can store a
# deck position without serialising callables.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Card:
    text: str
    action: str
    amount: int = 0
    target: int = 0
    note: str = ""


# action names understood by game.apply_card
COLLECT = "collect"  # amount from the bank
PAY = "pay"  # amount to the bank
COLLECT_EACH = "collect_each"  # amount from every other player
PAY_EACH = "pay_each"  # amount to every other player
ADVANCE = "advance"  # to target, passing GO pays salary
ADVANCE_NO_GO = "advance_no_go"  # to target, no salary
BACK = "back"  # move target squares backwards
GOTO_JAIL = "goto_jail"
JAIL_CARD = "jail_card"  # keep until needed
NEAREST_RAILROAD = "nearest_railroad"  # pay double rent if owned
NEAREST_UTILITY = "nearest_utility"  # pay ten times the dice if owned
REPAIRS = "repairs"  # amount per house, target per hotel


CHANCE: tuple[Card, ...] = (
    Card("Advance to GO. Collect $200.", ADVANCE, target=data.GO),
    Card("Advance to Illinois Avenue. If you pass GO, collect $200.",
         ADVANCE, target=24),
    Card("Advance to St. Charles Place. If you pass GO, collect $200.",
         ADVANCE, target=11),
    Card("Take a ride on the Reading. If you pass GO, collect $200.",
         ADVANCE, target=5),
    Card("Take a walk on the Boardwalk. Advance token to Boardwalk.",
         ADVANCE, target=39),
    Card("Advance token to the nearest utility. If unowned you may buy it "
         "from the bank. If owned, pay the owner ten times the dice roll.",
         NEAREST_UTILITY),
    Card("Advance token to the nearest railroad and pay the owner twice the "
         "rent otherwise due. If unowned you may buy it from the bank.",
         NEAREST_RAILROAD),
    Card("Advance token to the nearest railroad and pay the owner twice the "
         "rent otherwise due. If unowned you may buy it from the bank.",
         NEAREST_RAILROAD),
    Card("Go back three spaces.", BACK, target=3),
    Card("Go directly to jail. Do not pass GO, do not collect $200.",
         GOTO_JAIL),
    Card("Get out of jail, free. This card may be kept until needed.",
         JAIL_CARD),
    Card("The bank pays you a dividend of $50.", COLLECT, amount=50),
    Card("Your building and loan matures. Collect $150.", COLLECT, amount=150),
    Card("Poor tax of $15.", PAY, amount=15),
    Card("You have been elected Chairman of the Board. Pay each player $50.",
         PAY_EACH, amount=50),
    Card("Make general repairs on all your property: $25 per house, "
         "$100 per hotel.", REPAIRS, amount=25, target=100),
)

COMMUNITY_CHEST: tuple[Card, ...] = (
    Card("Advance to GO. Collect $200.", ADVANCE, target=data.GO),
    Card("Go directly to jail. Do not pass GO, do not collect $200.",
         GOTO_JAIL),
    Card("Get out of jail, free. This card may be kept until needed.",
         JAIL_CARD),
    Card("Bank error in your favor. Collect $200.", COLLECT, amount=200),
    Card("Income tax refund. Collect $20.", COLLECT, amount=20),
    Card("You have won second prize in a beauty contest. Collect $10.",
         COLLECT, amount=10),
    Card("From the sale of stock you get $45.", COLLECT, amount=45),
    Card("Your insurance matures. Collect $100.", COLLECT, amount=100),
    Card("Your Christmas fund matures. Collect $100.", COLLECT, amount=100),
    Card("You inherit $100.", COLLECT, amount=100, note=RECOVERED_PARTIAL),
    Card("Receive $25 for services.", COLLECT, amount=25,
         note=RECOVERED_PARTIAL),
    Card("Pay hospital fees of $100.", PAY, amount=100,
         note=RECOVERED_PARTIAL),
    Card("Doctor's fee. Pay $50.", PAY, amount=50),
    Card("School tax of $150.", PAY, amount=150),
    Card("Grand opera opening. Collect $50 from every player for opening "
         "night seats.", COLLECT_EACH, amount=50),
    Card("You are assessed for street repairs: $40 per house, "
         "$115 per hotel.", REPAIRS, amount=40, target=115),
)


def nearest(pos: int, targets: tuple[int, ...]) -> int:
    """First square in `targets` at or ahead of `pos`, wrapping at GO."""
    for step in range(1, 41):
        candidate = (pos + step) % 40
        if candidate in targets:
            return candidate
    raise ValueError("no target square on the board")
