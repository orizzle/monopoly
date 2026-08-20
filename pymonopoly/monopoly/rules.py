"""Pure rule functions -- no state mutation, no screen output.

Everything money-related lives here so it can be tested against the values the
original prints on its title deed cards.  Two of the rules are the author's
own rather than Parker Brothers', and are marked where they occur: mortgages
accrue recurring interest, and the bank extends a short-term loan rather than
forcing an immediate sale.
"""

from __future__ import annotations

from . import data
from .state import BANK, GameState

# --------------------------------------------------------------------------
# Ownership queries
# --------------------------------------------------------------------------


def owns_group(state: GameState, player: int, group: int) -> bool:
    """True when one player holds every square in a colour group."""
    members = data.COLOR_GROUPS[group].members
    return all(state.props[p].owner == player for p in members)


def group_unimproved(state: GameState, group: int) -> bool:
    return all(state.props[p].houses == 0
               for p in data.COLOR_GROUPS[group].members)


def group_unmortgaged(state: GameState, group: int) -> bool:
    return all(not state.props[p].mortgaged
               for p in data.COLOR_GROUPS[group].members)


def count_owned(state: GameState, player: int, squares: tuple[int, ...]) -> int:
    return sum(1 for p in squares if state.props[p].owner == player)


def railroads_owned(state: GameState, player: int) -> int:
    return count_owned(state, player, data.RAILROAD_SQUARES)


def utilities_owned(state: GameState, player: int) -> int:
    return count_owned(state, player, data.UTILITY_SQUARES)


# --------------------------------------------------------------------------
# Rent
# --------------------------------------------------------------------------


def railroad_rent(count: int) -> int:
    """25, 50, 100, 200 for one to four railroads.

    The Value[] record for a railroad ships with a zeroed Rent[] array; the
    original computes the figure instead, and its title deed card prints the
    same doubling ladder.
    """
    return 25 * (2 ** (count - 1)) if count else 0


def utility_rent(count: int, dice_total: int) -> int:
    """Four times the dice for one utility, ten times for both."""
    return dice_total * (10 if count >= 2 else 4)


def rent_due(state: GameState, pos: int, dice_total: int) -> int:
    """What the square at `pos` charges the player standing on it."""
    sq = data.PLACE[pos]
    st = state.props[pos]

    if not sq.ownable or st.owner == BANK or st.mortgaged:
        return 0  # "but it is mortgaged.  No charge."

    if sq.kind == data.RAILROAD:
        return railroad_rent(railroads_owned(state, st.owner))

    if sq.kind == data.UTILITY:
        return utility_rent(utilities_owned(state, st.owner), dice_total)

    if st.houses:
        return sq.rent[st.houses]

    # Undeveloped street: doubled if the owner holds the whole group.
    base = sq.rent[0]
    if owns_group(state, st.owner, sq.group) and group_unimproved(state, sq.group):
        return base * 2
    return base


# --------------------------------------------------------------------------
# Mortgages
#
# The author's own mechanic.  Standard Monopoly charges 10% once, when the
# property is redeemed.  This game charges interest repeatedly and lets the
# player stop it by repaying the principal -- which is the mortgage value.
#
# Version 3.x had a bug here that overcharged on redemption; the readme says
# 4.1 fixed it, and a fragment of the buggy expression survives in the slack
# space of MONOGRAF.GRA.  The corrected form is used below.
# --------------------------------------------------------------------------


def mortgage_value(pos: int) -> int:
    """Trunc(Value[n].Cost / 2)."""
    return data.PLACE[pos].cost // 2


def mortgage_interest(pos: int) -> int:
    """Ten per cent of the mortgage value."""
    return mortgage_value(pos) // 10


def unmortgage_cost(pos: int) -> int:
    """Principal plus ten per cent -- the post-4.1 figure."""
    return mortgage_value(pos) + mortgage_interest(pos)


def total_interest_due(state: GameState, player: int) -> int:
    return sum(mortgage_interest(p) for p in state.holdings(player)
               if state.props[p].mortgaged)


# --------------------------------------------------------------------------
# Building
# --------------------------------------------------------------------------


def can_build_on(state: GameState, player: int, group: int) -> bool:
    """The whole group must be owned, unmortgaged and buildable."""
    g = data.COLOR_GROUPS[group]
    return (g.buildable
            and owns_group(state, player, group)
            and group_unmortgaged(state, group))


def units_in_group(state: GameState, group: int) -> int:
    return sum(state.props[p].houses for p in data.COLOR_GROUPS[group].members)


def max_units_in_group(group: int) -> int:
    """"Zoning Regulations allow N units in the <group> group." """
    return data.HOUSES_PER_HOTEL * len(data.COLOR_GROUPS[group].members)


def house_cost(group: int) -> int:
    return data.COLOR_GROUPS[group].house_cost


def sale_value_per_unit(group: int) -> int:
    """Returned units bring back half what they cost."""
    return house_cost(group) // 2


def distribute_units(state: GameState, group: int, count: int) -> list[int]:
    """Choose which squares receive `count` new units.

    Not the fewest-houses-first rule this used to apply, which is the modern
    board-game one.  The original keeps a cursor per colour group -- a word
    in the group record at CHN load 0x41AB, starting at 1 -- and simply walks
    it round the members:

        place a unit on member[cursor]
        cursor := cursor + 1
        if cursor > NumberIn then cursor := 1

    It never looks at how many houses a square already has.  Two things
    follow.  The order is the record's own, which is descending, so the first
    house on the Cyan group goes to Connecticut Avenue and not to Oriental
    -- captured, with the deed card of each receiving square drawn in turn.
    And the cursor survives between visits, so where a house lands depends on
    what was bought and sold on that group before.

    Returns the list of board positions to increment, one entry per unit.
    """
    order = data.COLOR_GROUPS[group].build_order
    cursor = state.build_cursor.get(group, 1)
    picks: list[int] = []
    for _ in range(count):
        picks.append(order[cursor - 1])
        cursor += 1
        if cursor > len(order):
            cursor = 1
    state.build_cursor[group] = cursor
    return picks


def collect_units(state: GameState, group: int, count: int) -> list[int]:
    """Choose which squares give up `count` units.

    The mirror image, sharing the same cursor (CHN load 0x994A).  Returning
    steps the cursor back *before* using it, where building uses it and then
    steps forward, so a sale undoes a purchase square for square:

        cursor := cursor - 1
        if cursor < 1 then cursor := NumberIn
        take a unit from member[cursor]
    """
    order = data.COLOR_GROUPS[group].build_order
    cursor = state.build_cursor.get(group, 1)
    picks: list[int] = []
    for _ in range(count):
        cursor -= 1
        if cursor < 1:
            cursor = len(order)
        picks.append(order[cursor - 1])
    state.build_cursor[group] = cursor
    return picks


# --------------------------------------------------------------------------
# Worth and taxes
# --------------------------------------------------------------------------


def property_worth(state: GameState, player: int) -> int:
    """Cash value of a player's holdings, for tax and bankruptcy tests."""
    total = 0
    for pos in state.holdings(player):
        sq = data.PLACE[pos]
        st = state.props[pos]
        total += mortgage_value(pos) if st.mortgaged else sq.cost
        total += st.houses * sale_value_per_unit(sq.group)
    return total


def net_worth(state: GameState, player: int) -> int:
    return state.players[player].cash + property_worth(state, player)


def calculated_income_tax(state: GameState, player: int) -> int:
    """The ten per cent alternative to the $200 flat rate."""
    return net_worth(state, player) * data.INCOME_TAX_RATE // 100


def repair_bill(state: GameState, player: int,
                per_house: int, per_hotel: int) -> int:
    """Used by the street-repairs and general-repairs cards."""
    total = 0
    for pos in state.holdings(player):
        st = state.props[pos]
        if st.has_hotel:
            total += per_hotel
        else:
            total += st.houses * per_house
    return total


# --------------------------------------------------------------------------
# Liquidity
# --------------------------------------------------------------------------


def can_raise(state: GameState, player: int, amount: int) -> bool:
    """Whether a player could cover `amount` by selling and mortgaging."""
    return net_worth(state, player) >= amount


def has_assets(state: GameState, player: int) -> bool:
    return bool(state.holdings(player))
