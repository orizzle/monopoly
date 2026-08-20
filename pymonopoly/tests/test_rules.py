"""Rule and table tests.

The expected values here are not copied from the port -- they are the figures
the original prints on its own title deed cards, so a passing run means the
tables decoded out of MONOCODE.CHN agree with what the 1985 program shows.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from monopoly import data, rules
from monopoly.state import GameState


class TestBoardTable(unittest.TestCase):
    def test_forty_squares(self):
        self.assertEqual(len(data.PLACE), 40)

    def test_twenty_eight_ownable(self):
        ownable = [s for s in data.PLACE if s.ownable]
        self.assertEqual(len(ownable), 28)
        self.assertEqual(sum(1 for s in ownable if s.kind == data.STREET), 22)
        self.assertEqual(sum(1 for s in ownable if s.kind == data.RAILROAD), 4)
        self.assertEqual(sum(1 for s in ownable if s.kind == data.UTILITY), 2)

    def test_known_costs(self):
        expected = {
            1: 60, 3: 60, 5: 200, 6: 100, 8: 100, 9: 120, 11: 140, 12: 150,
            13: 140, 14: 160, 16: 180, 18: 180, 19: 200, 21: 220, 23: 220,
            24: 240, 26: 260, 27: 260, 28: 150, 29: 280, 31: 300, 32: 300,
            34: 320, 37: 350, 39: 400,
        }
        for pos, cost in expected.items():
            self.assertEqual(data.PLACE[pos].cost, cost, data.PLACE[pos].name)

    def test_st_james_matches_the_deed_card(self):
        """Read directly off shots/11-bob-land.png."""
        sq = data.PLACE[16]
        self.assertEqual(sq.name, "St. James Place")
        self.assertEqual(sq.cost, 180)
        self.assertEqual(list(sq.rent), [14, 70, 200, 550, 750, 950])
        self.assertEqual(rules.house_cost(sq.group), 100)
        self.assertEqual(rules.mortgage_value(16), 90)

    def test_boardwalk(self):
        sq = data.PLACE[39]
        self.assertEqual(sq.cost, 400)
        self.assertEqual(list(sq.rent), [50, 200, 600, 1400, 1700, 2000])
        self.assertEqual(rules.house_cost(sq.group), 200)

    def test_short_names_unique(self):
        shorts = [s.short_uc for s in data.PLACE if s.ownable]
        self.assertEqual(len(shorts), len(set(shorts)))

    def test_short_name_lookup(self):
        self.assertEqual(data.find_by_short_name("boarD"), 39)
        self.assertEqual(data.find_by_short_name("b&o"), 25)
        self.assertIsNone(data.find_by_short_name("zzz"))


class TestColorGroups(unittest.TestCase):
    def test_membership_covers_every_ownable_square(self):
        seen = set()
        for g in data.COLOR_GROUPS[1:]:
            seen |= set(g.members)
        ownable = {i for i, s in enumerate(data.PLACE) if s.ownable}
        self.assertEqual(seen, ownable)

    def test_group_sizes(self):
        sizes = [g.size for g in data.COLOR_GROUPS[1:]]
        self.assertEqual(sizes, [2, 3, 3, 3, 3, 3, 3, 2, 4, 2])

    def test_house_costs(self):
        costs = [g.house_cost for g in data.COLOR_GROUPS[1:]]
        self.assertEqual(costs, [50, 50, 100, 100, 150, 150, 200, 200, 0, 0])

    def test_only_streets_are_buildable(self):
        for g in data.COLOR_GROUPS[1:]:
            for pos in g.members:
                self.assertEqual(g.buildable,
                                 data.PLACE[pos].kind == data.STREET)

    def test_members_match_place_group(self):
        for i, g in enumerate(data.COLOR_GROUPS[1:], start=1):
            for pos in g.members:
                self.assertEqual(data.PLACE[pos].group, i)


class TestRent(unittest.TestCase):
    def setUp(self):
        self.st = GameState.new_game(["A", "B"], seed=1)

    def test_unowned_pays_nothing(self):
        self.assertEqual(rules.rent_due(self.st, 1, 7), 0)

    def test_base_rent(self):
        self.st.props[1].owner = 0
        self.assertEqual(rules.rent_due(self.st, 1, 7), 2)

    def test_whole_group_doubles_undeveloped_rent(self):
        self.st.props[1].owner = 0
        self.st.props[3].owner = 0
        self.assertEqual(rules.rent_due(self.st, 1, 7), 4)

    def test_houses_beat_the_doubling(self):
        self.st.props[1].owner = 0
        self.st.props[3].owner = 0
        self.st.props[1].houses = 1
        self.assertEqual(rules.rent_due(self.st, 1, 7), 10)

    def test_hotel(self):
        self.st.props[39].owner = 0
        self.st.props[39].houses = 5
        self.assertEqual(rules.rent_due(self.st, 39, 7), 2000)

    def test_mortgaged_pays_nothing(self):
        self.st.props[1].owner = 0
        self.st.props[1].mortgaged = True
        self.assertEqual(rules.rent_due(self.st, 1, 7), 0)

    def test_railroad_ladder(self):
        self.assertEqual([rules.railroad_rent(n) for n in (1, 2, 3, 4)],
                         [25, 50, 100, 200])
        for n, sq in enumerate(data.RAILROAD_SQUARES, start=1):
            self.st.props[sq].owner = 0
            self.assertEqual(rules.rent_due(self.st, sq, 7),
                             [25, 50, 100, 200][n - 1])

    def test_utility_multipliers(self):
        self.st.props[12].owner = 0
        self.assertEqual(rules.rent_due(self.st, 12, 9), 36)
        self.st.props[28].owner = 0
        self.assertEqual(rules.rent_due(self.st, 12, 9), 90)


class TestMortgage(unittest.TestCase):
    def test_value_is_half_cost(self):
        for pos, sq in enumerate(data.PLACE):
            if sq.ownable:
                self.assertEqual(rules.mortgage_value(pos), sq.cost // 2)

    def test_redemption_is_principal_plus_ten_percent(self):
        """The post-4.1 figure.  Boardwalk: 200 principal + 20 interest."""
        self.assertEqual(rules.mortgage_value(39), 200)
        self.assertEqual(rules.mortgage_interest(39), 20)
        self.assertEqual(rules.unmortgage_cost(39), 220)

    def test_redemption_is_not_the_3x_bug(self):
        """Version 3.x computed cost + 10% of the mortgage, roughly doubling
        the charge.  Guard against reintroducing it."""
        for pos, sq in enumerate(data.PLACE):
            if sq.ownable:
                buggy = sq.cost + (sq.cost // 2) // 10
                self.assertLess(rules.unmortgage_cost(pos), buggy)


class TestBuilding(unittest.TestCase):
    def setUp(self):
        self.st = GameState.new_game(["A", "B"], seed=1)

    def _own_orange(self):
        for pos in data.COLOR_GROUPS[4].members:
            self.st.props[pos].owner = 0

    def test_needs_whole_group(self):
        self.st.props[16].owner = 0
        self.assertFalse(rules.can_build_on(self.st, 0, 4))
        self._own_orange()
        self.assertTrue(rules.can_build_on(self.st, 0, 4))

    def test_mortgage_blocks_building(self):
        self._own_orange()
        self.st.props[16].mortgaged = True
        self.assertFalse(rules.can_build_on(self.st, 0, 4))

    def test_zoning_limit(self):
        self.assertEqual(rules.max_units_in_group(4), 15)
        self.assertEqual(rules.max_units_in_group(1), 10)

    def test_units_build_evenly(self):
        self._own_orange()
        picks = rules.distribute_units(self.st, 4, 3)
        self.assertEqual(sorted(picks), sorted(data.COLOR_GROUPS[4].members))

    def test_units_unbuild_evenly(self):
        self._own_orange()
        for pos in data.COLOR_GROUPS[4].members:
            self.st.props[pos].houses = 2
        picks = rules.collect_units(self.st, 4, 3)
        self.assertEqual(sorted(picks), sorted(data.COLOR_GROUPS[4].members))

    def test_cannot_exceed_hotel(self):
        self._own_orange()
        for pos in data.COLOR_GROUPS[4].members:
            self.st.props[pos].houses = 5
        self.assertEqual(rules.distribute_units(self.st, 4, 3), [])


class TestWorth(unittest.TestCase):
    def setUp(self):
        self.st = GameState.new_game(["A", "B"], seed=1)

    def test_net_worth_counts_cash_and_property(self):
        self.st.props[39].owner = 0
        self.assertEqual(rules.net_worth(self.st, 0), 1500 + 400)

    def test_mortgaged_property_counts_at_mortgage_value(self):
        self.st.props[39].owner = 0
        self.st.props[39].mortgaged = True
        self.assertEqual(rules.net_worth(self.st, 0), 1500 + 200)

    def test_houses_count_at_half(self):
        self.st.props[39].owner = 0
        self.st.props[39].houses = 2
        self.assertEqual(rules.net_worth(self.st, 0), 1500 + 400 + 2 * 100)

    def test_calculated_tax_is_ten_percent(self):
        self.assertEqual(rules.calculated_income_tax(self.st, 0), 150)

    def test_repair_bill(self):
        self.st.props[39].owner = 0
        self.st.props[39].houses = 5
        self.st.props[37].owner = 0
        self.st.props[37].houses = 3
        self.assertEqual(rules.repair_bill(self.st, 0, 25, 100), 100 + 75)


if __name__ == "__main__":
    unittest.main(verbosity=2)
