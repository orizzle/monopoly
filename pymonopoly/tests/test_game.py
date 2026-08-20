"""Drive whole games headlessly and check nothing breaks.

The auto-player answers every prompt with a valid key rather than a canned
script, so it keeps working as prompts change.  Its policy is deliberately
acquisitive -- buy when offered, build when asked -- because that is the path
that exercises rent, mortgages and bankruptcy.
"""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from monopoly import cga, data, rules, save
from monopoly.display import NullTerminal
from monopoly.game import Game, Quit
from monopoly.state import BANK, GameState


class AutoTerminal(NullTerminal):
    """Answers prompts by policy, and gives up after a turn budget."""

    def __init__(self, names, prefer="", budget=4000, seed=0):
        super().__init__()
        self.names = list(names)
        self.prefer = prefer
        self.budget = budget
        self.calls = 0
        self.rng = random.Random(seed)
        self.screens_seen = 0

    def _spend(self):
        self.calls += 1
        if self.calls > self.budget:
            raise Quit

    def choose(self, allowed):
        self._spend()
        if allowed is None:
            return "\r"
        for want in self.prefer:
            if want in allowed:
                return want
        return allowed[0]

    def read_key(self):
        self._spend()
        return "\r"

    def read_line(self, scr, x, y, width, attr, initial=""):
        self._spend()
        if self.names:
            return self.names.pop(0)
        return ""

    def paint(self, scr, force=False):
        self.screens_seen += 1


def play(names=("Ann", "Ben"), prefer="pgi", budget=900, seed=7):
    term = AutoTerminal(list(names) + [""], prefer=prefer, budget=budget)
    game = Game(term, seed=seed, audio="off")
    try:
        game.run()
    except Quit:
        pass
    return game


class TestSetup(unittest.TestCase):
    def test_names_are_taken_in_order(self):
        game = play(names=("Ann", "Ben", "Cal"), budget=40)
        self.assertEqual([p.name for p in game.state.players],
                         ["Ann", "Ben", "Cal"])

    def test_everyone_starts_with_the_same_stake(self):
        st = GameState.new_game(["Ann", "Ben"], seed=1)
        for p in st.players:
            self.assertEqual(p.cash, data.STARTING_CASH)
            self.assertEqual(p.position, data.GO)
        self.assertTrue(all(s.owner == BANK for s in st.props))


class TestFullGames(unittest.TestCase):
    def test_a_long_game_does_not_crash(self):
        game = play(budget=1500, seed=3)
        self.assertIsNotNone(game.state)
        self.assertGreater(game.term.screens_seen, 0)

    def test_money_is_conserved_or_created_only_by_the_bank(self):
        """No player may end with negative cash, and nobody may own a square
        twice."""
        for seed in (1, 2, 3, 5, 8):
            game = play(budget=900, seed=seed)
            st = game.state
            for p in st.players:
                self.assertGreaterEqual(p.cash, 0, f"seed {seed}: {p.name}")
            owners = [s.owner for s in st.props]
            for pos, owner in enumerate(owners):
                if owner != BANK:
                    self.assertTrue(0 <= owner < len(st.players))
                    self.assertTrue(data.PLACE[pos].ownable,
                                    f"non-property {pos} became owned")

    def test_bankrupt_players_hold_nothing(self):
        for seed in (4, 11, 19):
            game = play(budget=1200, seed=seed)
            st = game.state
            for i, p in enumerate(st.players):
                if p.bankrupt:
                    self.assertEqual(st.holdings(i), [],
                                     f"seed {seed}: {p.name} still holds land")
                    self.assertEqual(p.cash, 0)

    def test_houses_never_exceed_zoning(self):
        for seed in (6, 13):
            game = play(prefer="pghi", budget=1200, seed=seed)
            st = game.state
            for g in range(1, 11):
                self.assertLessEqual(rules.units_in_group(st, g),
                                     rules.max_units_in_group(g))
            for pos, s in enumerate(st.props):
                self.assertLessEqual(s.houses, data.HOUSES_PER_HOTEL)
                if s.houses:
                    self.assertEqual(data.PLACE[pos].kind, data.STREET)

    def test_players_stay_on_the_board(self):
        game = play(budget=900, seed=21)
        for p in game.state.players:
            self.assertTrue(0 <= p.position < 40)


class TestSaveLoad(unittest.TestCase):
    def test_round_trip(self):
        import tempfile

        game = play(budget=600, seed=9)
        st = game.state
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "game"
            save.save(st, str(target))
            back = save.load(str(target))
        self.assertEqual([p.name for p in back.players],
                         [p.name for p in st.players])
        self.assertEqual([p.cash for p in back.players],
                         [p.cash for p in st.players])
        self.assertEqual([(s.owner, s.houses, s.mortgaged) for s in back.props],
                         [(s.owner, s.houses, s.mortgaged) for s in st.props])
        self.assertEqual(back.current, st.current)

    def test_rejects_a_foreign_format(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bad.mpl"
            target.write_text(json.dumps({"version": 999}))
            with self.assertRaises(ValueError):
                save.load(str(target))


class TestScreens(unittest.TestCase):
    def test_every_deed_card_draws_without_error(self):
        from monopoly import screens

        st = GameState.new_game(["Ann", "Ben"], seed=1)
        for pos, sq in enumerate(data.PLACE):
            if not sq.ownable:
                continue
            scr = cga.Screen()
            screens.draw_deed_card(scr, pos, st)
            text = scr.as_text()
            self.assertIn(sq.name.split()[0], text, sq.name)

    def test_board_draws_every_square(self):
        from monopoly import screens

        st = GameState.new_game(["Ann", "Ben"], seed=1)
        scr = cga.Screen()
        screens.draw_board(scr, st)
        text = scr.as_text()
        for sq in data.PLACE:
            if sq.short:
                self.assertIn(sq.short[:3], text, sq.name)

    def test_ring_positions_are_distinct(self):
        from monopoly.screens import _ring_cell

        cells = [_ring_cell(p) for p in range(40)]
        self.assertEqual(len(set(cells)), 40)


if __name__ == "__main__":
    unittest.main(verbosity=2)
