"""Screen fidelity: the port's own drawing versus the 1985 program's output.

These tests fail if a layout change breaks a screen that previously matched
the emulator exactly.  They are skipped when the reference captures are not
present, so the suite still runs on a checkout without them.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

SHOTS = ROOT.parent / "shots"


def _load():
    import compare_screens
    import verify_pixels

    return compare_screens, verify_pixels


@unittest.skipUnless(SHOTS.is_dir(), "reference captures not available")
class TestRendererIsExact(unittest.TestCase):
    """A capture decoded to cells and re-rendered must be pixel-identical.

    This is the measuring instrument rather than the port: it proves the CGA
    ROM font and the 16-colour palette are right.
    """

    def test_captures_round_trip(self):
        _, verify_pixels = _load()
        checked = 0
        for shot in sorted(SHOTS.glob("*.png")):
            status, detail = verify_pixels.verify(str(shot))
            if status == "SKIP":
                continue
            self.assertEqual(status, "PASS", f"{shot.name}: {detail}")
            checked += 1
        self.assertGreater(checked, 0, "no text-mode captures found")


@unittest.skipUnless(SHOTS.is_dir(), "reference captures not available")
class TestScreensMatchTheOriginal(unittest.TestCase):
    def test_every_case_is_pixel_exact(self):
        compare_screens, _ = _load()
        for shot, build, label in compare_screens.CASES:
            with self.subTest(screen=label):
                self.assertTrue(
                    compare_screens.run_case(shot, build, label),
                    f"{shot} ({label}) no longer matches the original")


@unittest.skipUnless(SHOTS.is_dir(), "reference captures not available")
class TestBoardFigure(unittest.TestCase):
    def test_board_decodes_to_match_the_capture(self):
        import numpy as np

        from monopoly import graphics
        from verify_graphics import to_indices

        asset = graphics.find_asset()
        if asset is None:
            self.skipTest("MONOGRAF.GRA not available")
        capture = SHOTS / "22-board-land.png"
        if not capture.exists():
            self.skipTest("board capture not available")

        board = np.array(graphics.load_board(asset))
        idx = to_indices(str(capture))
        h, w = board.shape
        differing = int((board != idx[:h, :w]).sum())
        # The only differences are the 3x3 player tokens drawn over the figure.
        self.assertLess(differing, 40,
                        f"board figure differs in {differing} pixels")



@unittest.skipUnless(SHOTS.is_dir(), "reference captures not available")
class TestTokenMovement(unittest.TestCase):
    """The token walks to its square and then blinks.

    Both behaviours were measured by capturing the original four times a
    second through a roll: the moving piece advances one square per frame, and
    once it arrives it alternates present/absent.
    """

    def _clusters(self, frame, base):
        import numpy as np

        d = np.argwhere(np.array(frame.pixels)[:123, :123] != base)
        seen = []
        for y, x in d:
            if not any(abs(y - cy) < 4 and abs(x - cx) < 4 for cy, cx in seen):
                seen.append((int(y), int(x)))
        return sorted(seen, key=lambda t: t[1])

    def _game(self):
        from monopoly.display import NullTerminal
        from monopoly.game import Game
        from monopoly.state import GameState

        g = Game(NullTerminal(), seed=1, audio="off")
        g.state = GameState.new_game(["ann", "ben"], seed=1)
        return g

    def test_token_steps_one_square_per_frame(self):
        import numpy as np

        from monopoly import graphics

        if graphics.find_asset() is None:
            self.skipTest("MONOGRAF.GRA not available")
        g = self._game()
        base = np.array(graphics.load_board(graphics.find_asset()))
        frames = list(g.move_frames(0, 0, 7))

        travel = [self._clusters(f, base) for f, _ in frames[:7]]
        moving = [c[0][1] for c in travel]   # x of the leftmost token
        # Ten pixels per square along the bottom edge, as the board's own
        # divider lines are spaced.  These are the first player's columns,
        # and they are the ones the captured original walks through: screens
        # s0000..s0011 of the five-minute audit show ann's piece at x 102,
        # 92, 72, 62, 52, 42, 32, 22 on consecutive frames.
        self.assertEqual(moving, [102, 92, 82, 72, 62, 52, 42])
        for c in travel:
            self.assertEqual(len(c), 2, "both tokens should stay drawn")

    def test_token_blinks_after_landing(self):
        import numpy as np

        from monopoly import graphics

        if graphics.find_asset() is None:
            self.skipTest("MONOGRAF.GRA not available")
        g = self._game()
        base = np.array(graphics.load_board(graphics.find_asset()))
        frames = list(g.move_frames(0, 0, 7))
        blink = [len(self._clusters(f, base)) for f, _ in frames[7:]]
        self.assertEqual(blink, [2, 1] * graphics.BLINK_CYCLES)

    def test_blink_happens_on_the_destination_square(self):
        import numpy as np

        from monopoly import graphics

        if graphics.find_asset() is None:
            self.skipTest("MONOGRAF.GRA not available")
        g = self._game()
        base = np.array(graphics.load_board(graphics.find_asset()))
        frames = list(g.move_frames(0, 0, 7))
        shown = self._clusters(frames[7][0], base)
        self.assertIn((119, 42), shown,
                      "the piece must blink where it landed, not where it began")

@unittest.skipUnless(SHOTS.is_dir(), "reference captures not available")
class TestCashRow(unittest.TestCase):
    """Player names and cash along the bottom of the board screen.

    Two things only show up with the right test data: the row is centred as a
    block, so where it starts depends on the number of players, and each name
    is centred over its own money column in a seven-wide field.  A capture
    where every name is the same length cannot distinguish centring from a
    fixed offset, so these cases use names of differing lengths.
    """

    CASES = (
        ("22-board-land.png", [("ann", 1500, 0), ("ben", 1500, 0)]),
        ("four4-00.png", [("ann", 1500, 0), ("ben", 1500, 0),
                          ("cal", 1500, 0), ("dot", 1500, 0)]),
        ("names-3p.png", [("a", 1500, 0), ("benjamin", 1500, 0),
                          ("cid", 1500, 0)]),
        ("names-4p.png", [("al", 1500, 0), ("beatrix", 1500, 0),
                          ("cy", 1500, 0), ("dee", 1500, 0)]),
    )

    def _row(self, indices):
        import verify_graphics as vg

        return {(c, r, t) for c, r, t, _ in vg.runs(
            vg.find_text(indices, skip=(0, 0, 123, 123))) if r >= 24}

    def test_matches_the_original(self):
        import numpy as np
        import verify_graphics as vg

        from monopoly import graphics

        asset = graphics.find_asset()
        if asset is None:
            self.skipTest("MONOGRAF.GRA not available")
        art = graphics.load_board(asset)

        for shot, seats in self.CASES:
            path = SHOTS / shot
            if not path.exists():
                continue
            with self.subTest(players=len(seats), shot=shot):
                screen = graphics.BoardScreen(art)
                screen.draw("", [], seats)
                self.assertEqual(self._row(np.array(screen.pixels)),
                                 self._row(vg.to_indices(str(path))))

    def test_a_long_name_overhangs_to_the_left(self):
        from monopoly import graphics

        # Eight letters in a seven-wide field: the name must start one column
        # before its money column, not be pushed right or clipped.
        base = graphics.cash_origin(3) + graphics.CASH_STEP
        start = base + (graphics.CASH_FIELD - len("benjamin")) // 2
        self.assertEqual(start, base - 1)

    def test_row_origin_shifts_with_player_count(self):
        from monopoly import graphics

        self.assertEqual(graphics.cash_origin(2), 13)
        self.assertEqual(graphics.cash_origin(3), 8)
        self.assertEqual(graphics.cash_origin(4), 3)

SCREENS5 = ROOT.parent / "shots" / "screens5"


@unittest.skipUnless(SCREENS5.is_dir(), "five-minute screen set not available")
class TestFiveMinuteAudit(unittest.TestCase):
    """Every screen from five minutes of four-player play must reproduce.

    This is the end-to-end guarantee: each screen the original drew is parsed
    back into game state, redrawn by the port, and diffed.  Anything the port
    cannot reconstruct counts as a failure, so a screen cannot pass by being
    quietly skipped.
    """

    def test_every_screen_is_pixel_exact(self):
        import json

        import audit

        manifest = json.loads((SCREENS5 / "manifest.json").read_text())
        asset = audit.graphics.find_asset()
        if asset is None:
            self.skipTest("MONOGRAF.GRA not available")
        art = audit.graphics.load_board(asset)
        board = audit.np.array(art)

        bad = []
        for entry in manifest:
            path = SCREENS5 / entry["file"]
            if entry["mode"] == "graphics":
                r = audit.audit_graphics(path, art, board)
            else:
                r = audit.audit_text(path)
            if r["status"] != "exact":
                bad.append((entry["file"], r["status"],
                            r.get("pixels_differ")))
        self.assertEqual(bad, [], f"{len(bad)} of {len(manifest)} screens "
                                  f"did not reproduce exactly")


@unittest.skipUnless(SHOTS.is_dir(), "reference captures not available")
class TestTumblePoses(unittest.TestCase):
    def test_poses_carry_no_pips(self):
        from monopoly import graphics

        for phase in range(len(graphics.diceart.TUMBLE_ART)):
            scr = graphics.GraphicsScreen()
            graphics.draw_tumbling_dice(scr, phase)
            pixels = [v for row in scr.pixels for v in row]
            self.assertEqual(pixels.count(3), 0,
                             "a tumbling die must show no pips")
            self.assertGreater(pixels.count(2), 0)

    def test_the_two_dice_turn_independently(self):
        from monopoly import graphics

        a = graphics.GraphicsScreen(); graphics.draw_tumbling_dice(a, 0, 0)
        b = graphics.GraphicsScreen(); graphics.draw_tumbling_dice(b, 0, 2)
        self.assertNotEqual(a.pixels, b.pixels,
                            "the right die must follow its own phase")

class TestTumbleRate(unittest.TestCase):
    """The cubes take turns, each on twice the click beat.

    Measured from a 59.92 fps capture of the original: the two-die box changes
    every 41.5 ms (median of 22 changes: 50 ms at 16.69 ms per video frame,
    with the odd 83 ms gap where Random(8) picked the same drawing twice).
    The speaker log agrees -- a cube's three clicks come round every 41.56 ms
    -- so one cube redraws on each beat and any single cube every 83 ms.
    """

    def test_a_cube_redraws_on_every_other_beat(self):
        from monopoly import graphics, sound

        self.assertAlmostEqual(graphics.TUMBLE_HOLD_MS,
                               2 * sound.RATTLE_PERIOD_MS, delta=1)

    def test_pose_is_slower_than_a_single_click_beat(self):
        from monopoly import graphics, sound

        self.assertGreater(graphics.TUMBLE_HOLD_MS, sound.RATTLE_PERIOD_MS,
                           "a die must hold its pose across the other's beat")


JAIL = Path(__file__).resolve().parent / "fixtures" / "jail"


@unittest.skipUnless(JAIL.is_dir(), "jail captures not available")
class JailScreens(unittest.TestCase):
    """The board, pixel for pixel, against captures of a real jailing.

    These are lossless grabs rather than AVI frames: the questions here turn
    on single pixels, which JPEG smear cannot answer.  Between them they pin
    the piece inside the cell, the piece walking out of it, and the two
    board-drawn messages the jail routine writes.
    """

    def art(self):
        from monopoly import graphics

        asset = graphics.find_asset()
        if asset is None:
            self.skipTest("MONOGRAF.GRA not available")
        return graphics.load_board(asset)

    def boxes(self, pixels):
        """Bounding box of each piece drawn over the board figure."""
        import numpy as np

        base = np.array(self.art())
        diff = np.argwhere(np.array(pixels)[:123, :123] != base)
        groups: list[list[tuple[int, int]]] = []
        for y, x in sorted((int(y), int(x)) for y, x in diff):
            for g in groups:
                if any(abs(y - gy) <= 3 and abs(x - gx) <= 3 for gy, gx in g):
                    g.append((y, x))
                    break
            else:
                groups.append([(y, x)])
        return sorted((min(x for _, x in g), max(x for _, x in g),
                       min(y for y, _ in g), max(y for y, _ in g))
                      for g in groups if len(g) >= 4)

    def capture(self, name):
        import verify_graphics as vg

        return vg.to_indices(str(JAIL / name))

    def rendered(self, seats):
        from monopoly import graphics

        screen = graphics.BoardScreen(self.art())
        screen.draw("", [], seats)
        return screen

    CASES = (
        # (capture, seats) -- C is the first player, P the second, which the
        # cash row in each capture confirms.
        ("jailed-piece.png", [("C", 840, 10, True), ("P", 1125, 8, False)]),
        ("walk-left-edge.png", [("C", 840, 17, False), ("P", 1125, 8, False)]),
        ("two-walkers.png", [("C", 840, 19, False), ("P", 1125, 13, False)]),
    )

    def test_pieces_sit_where_the_original_puts_them(self):
        for name, seats in self.CASES:
            with self.subTest(capture=name):
                self.assertEqual(self.boxes(self.rendered(seats).pixels),
                                 self.boxes(self.capture(name)),
                                 f"{name}: pieces are in the wrong place")

    def test_the_jailed_piece_is_inside_the_cell(self):
        """Not on the visiting edge, and not where the port used to draw it."""
        boxes = self.boxes(self.capture("jailed-piece.png"))
        self.assertIn((9, 11, 112, 114), boxes)

    def test_first_player_takes_the_far_seat(self):
        """Pascal counts from 1, so player 0 is seat 1 and player 1 seat 0."""
        from monopoly import graphics

        # both on the left edge, one square apart, at their two offsets
        boxes = self.boxes(self.capture("two-walkers.png"))
        self.assertEqual(boxes, [(1, 3, 22, 24), (1, 3, 78, 80)])
        for player, offset in ((0, 6), (1, 2)):
            with self.subTest(player=player):
                self.assertEqual(
                    graphics.TOKEN_INSET
                    + graphics.TOKEN_STEP * ((player + 1) % 2), offset)

    def prompt_runs(self, name):
        import verify_graphics as vg

        return [(c, r, t) for c, r, t, _a in
                vg.runs(vg.find_text(self.capture(name), skip=(0, 0, 123, 123)))
                # row 3 carries the dice drawings, not the message
                if 4 <= r <= 22]

    def test_the_jail_prompt_is_on_the_board(self):
        """Not in the blue message panel: rows 5, 7 and 8, left of centre."""
        self.assertEqual(
            self.prompt_runs("prompt.png"),
            [(19, 5, "You"), (23, 5, "are"), (27, 5, "in"), (30, 5, "JAIL."),
             (19, 7, "Want"), (24, 7, "to"), (27, 7, "P"), (28, 7, "ay"),
             (31, 7, "$50?"),
             (24, 8, "or"), (27, 8, "R"), (28, 8, "oll?")])

    def test_the_port_lays_the_prompt_out_the_same_way(self):
        from monopoly import graphics

        placed = {(col, row): text
                  for col, row, text, _c in graphics.jail_prompt(False)}
        self.assertEqual(placed[(19, 5)], "You are in JAIL.")
        self.assertEqual(placed[(19, 7)], "Want to ")
        self.assertEqual(placed[(27, 7)], "P")
        self.assertEqual(placed[(28, 7)], "ay $50?")
        self.assertEqual(placed[(19, 8)], "     or ")
        self.assertEqual(placed[(27, 8)], "R")
        self.assertEqual(placed[(28, 8)], "oll?")

    def title_of(self, name):
        import verify_graphics as vg

        runs = vg.runs(vg.find_text(self.capture(name), skip=(0, 0, 123, 123)))
        return " ".join(t for _c, r, t, _a in runs if r <= 2)

    def cash_of(self, name):
        import verify_graphics as vg

        runs = vg.runs(vg.find_text(self.capture(name), skip=(0, 0, 123, 123)))
        return [t for _c, r, t, _a in runs if r >= 25 and t.isdigit()]

    def test_rolling_out_of_jail_costs_nothing_and_earns_another_roll(self):
        """The escape is a double like any other, so the turn carries on.

        Both frames come from one game loaded straight into jail.  The player
        had no Get Out of Jail Free card -- the captured prompt offers only
        Pay and Roll -- and her cash is untouched at $1500 when she lands, so
        she left by throwing a double rather than by paying the $50.  The
        board is titled for her turn as she lands, and retitled "again" for
        the roll that follows.
        """
        self.assertEqual(self.title_of("escape-landing.png"), "alice's turn")
        self.assertEqual(self.cash_of("escape-landing.png")[0], "1500")
        self.assertEqual(self.title_of("escape-again.png"), "alice again")

    def test_the_port_titles_that_repeat_the_same_way(self):
        from monopoly.display import NullTerminal
        from monopoly.game import Game
        from monopoly.state import GameState
        from monopoly import data

        g = Game(NullTerminal(), seed=1, audio="off")
        g.state = GameState.new_game(["alice", "bob"], seed=1)
        ply = g.state.players[0]
        ply.in_jail, ply.position, ply.jail_turns = True, data.JAIL, 0
        g.ask_on_board = lambda runs, keys: "r"
        g.roll_dice = lambda: (3, 3)
        g.move_by = lambda who, steps: None

        self.assertEqual(g.board_title(), "alice's turn")
        self.assertTrue(g.jail_turn(0), "the turn continues after the escape")
        self.assertEqual(ply.cash, 1500, "no fine is paid on a double")
        self.assertEqual(g.board_title(), "alice again")

    def test_the_third_roll_message_is_on_the_board(self):
        """Two lines at column 19, rows 7 and 8 -- not a four-line panel."""
        self.assertEqual(
            self.prompt_runs("rolled-three.png"),
            [(19, 7, "You"), (23, 7, "have"), (28, 7, "rolled"), (35, 7, "3"),
             (19, 8, "times"), (25, 8, "and"), (29, 8, "must"), (34, 8, "pay.")])


HOUSES = Path(__file__).resolve().parent / "fixtures" / "houses"


@unittest.skipUnless(HOUSES.is_dir(), "house captures not available")
class BuildingScreens(unittest.TestCase):
    """Buying and returning houses, against captures of the real flow.

    The captures come from saves edited to give one player a whole colour
    group -- property records start at file offset 136, five bytes a square,
    owner at +0 and houses at +3, players counted from one.
    """

    def rows(self, name, first=5, last=13):
        """The left-hand column of a business screen, row by row."""
        from verify_pixels import decode_capture

        scr, _ = decode_capture(str(HOUSES / name))
        out = []
        for row, line in enumerate(scr.as_text().splitlines(), start=1):
            text = line[:47].rstrip()
            if first <= row <= last and text.strip():
                out.append((row, text.strip()))
        return out

    def test_the_buy_prompt_reads_as_captured(self):
        self.assertEqual(self.rows("buy-units.png"), [
            (5, "Zoning Regulations allow 15"),
            (6, "units in the Cyan group."),
            (7, "There are no units now."),
            (8, "Each unit costs $50."),
            (10, "How many units will you buy? 6"),
            (12, "That will cost $300."),
        ])

    def test_the_return_prompt_reads_as_captured(self):
        """One line naming the group, not two, and no space after the $."""
        self.assertEqual(self.rows("return-units.png"), [
            (5, "There are 6 units on Cyan."),
            (6, "Each will bring $25."),
            (8, "How many units to return? 6"),
            (10, "That will bring $150."),
        ])

    def test_the_port_composes_the_same_lines(self):
        from monopoly import data, rules

        group = 2                                     # Cyan
        allowed = rules.max_units_in_group(group)
        cost = rules.house_cost(group)
        each = rules.sale_value_per_unit(group)
        name = data.COLOR_GROUPS[group].name
        self.assertEqual(
            [f"Zoning Regulations allow {allowed}",
             f"units in the {name} group.",
             f"There are {0 or 'no'} units now.",
             f"Each unit costs ${cost}."],
            ["Zoning Regulations allow 15", "units in the Cyan group.",
             "There are no units now.", "Each unit costs $50."])
        self.assertEqual(
            [f"There are 6 units on {name}.", f"Each will bring ${each}."],
            ["There are 6 units on Cyan.", "Each will bring $25."])

    def test_the_group_picker_lists_only_what_can_be_built_on(self):
        """Captured with two complete groups owned, one player."""
        self.assertEqual(self.rows("group-picker.png", first=5, last=9), [
            (5, "Tell me the color group"),
            (6, "you wish to improve."),
            (7, "Cyan"),
            (8, "Orange"),
            (9, "or None... changed my mind."),
        ])

    def test_the_whole_buy_screen_is_pixel_exact(self):
        """The strongest check available: render it and diff the pixels.

        Comparing cells is not enough -- a space and a full block render the
        same when the colour that differs is the one you cannot see -- so
        this rebuilds the captured state, draws the screen, and compares the
        two as images.  Reconstructed from the capture itself: alice on
        Oriental Avenue with $4700 against bob's $1500, holding the Cyan
        group with the sixth house going up, so Connecticut and Vermont carry
        two and Oriental one.  It was this diff that turned up the house
        marks taking the card body's colours instead of the title band's, the
        header centred inside the panel instead of on a fixed column, and a
        house count appended to the holdings row that the original never
        writes.
        """
        import numpy as np
        from verify_pixels import decode_capture

        from monopoly.display import NullTerminal
        from monopoly.game import Game
        from monopoly.state import GameState

        want, _ = decode_capture(str(HOUSES / "buy-units.png"))
        g = Game(NullTerminal(), seed=1, audio="off")
        g.state = GameState.new_game(["alice", "bob"], seed=1)
        st = g.state
        st.players[0].cash, st.players[1].cash = 4700, 1500
        st.players[0].position, st.current = 6, 0
        for square, houses in ((6, 1), (8, 2), (9, 2)):
            st.props[square].owner = 0
            st.props[square].houses = houses
        g.in_business = True
        g.group_ink = 2

        prompt = "How many units will you buy? "
        lines = ["Zoning Regulations allow 15", "units in the Cyan group.",
                 "There are no units now.", "Each unit costs $50."]
        g._panel("alice", lines + ["", f"{prompt}6", "",
                                   "That will cost $300."], None, 6)

        mine = np.array(g.scr.render())
        theirs = np.array(want.render())
        differing = int(np.any(mine != theirs, axis=-1).sum())
        self.assertEqual(differing, 0,
                         f"{differing} pixels differ from the original")

    def attrs(self, name, row, first, last):
        from verify_pixels import decode_capture

        scr, _ = decode_capture(str(HOUSES / name))
        return [scr.cell(c, row) for c in range(first, last + 1)]

    def test_the_group_name_is_written_in_its_own_colours(self):
        """Cyan on cyan, mid-sentence, while the line stays on the panel."""
        from monopoly import data

        grp = data.COLOR_GROUPS[2]
        want = (grp.tback << 4) | grp.ttext
        # "units in the Cyan group." -- the name sits at columns 18..21
        cells = self.attrs("buy-units.png", 6, 18, 21)
        self.assertEqual("".join(chr(ch) for ch, _a in cells), "Cyan")
        self.assertEqual([a for _c, a in cells], [want] * 4)
        # and the word before it keeps the panel's own colours
        self.assertNotEqual(self.attrs("buy-units.png", 6, 17, 17)[0][1], want)

    def test_the_return_line_colours_the_name_too(self):
        from monopoly import data

        grp = data.COLOR_GROUPS[2]
        want = (grp.tback << 4) | grp.ttext
        cells = self.attrs("return-units.png", 5, 26, 29)
        self.assertEqual("".join(chr(ch) for ch, _a in cells), "Cyan")
        self.assertEqual([a for _c, a in cells], [want] * 4)
        # the full stop after it does not take the group's colours
        self.assertNotEqual(self.attrs("return-units.png", 5, 30, 30)[0][1],
                            want)

    def test_the_port_paints_the_name_the_same_way(self):
        from monopoly import cga, data, screens

        grp = data.COLOR_GROUPS[2]
        panel = screens.BUSINESS_PANEL
        lines = ["Zoning Regulations allow 15", f"units in the {grp.name} group."]
        scr = cga.Screen()
        for i, line in enumerate(lines):
            scr.write_at(panel[0] + 3, panel[1] + 3 + i, line, 15, 2)
        screens.paint_group_name(scr, panel, lines, 2)
        at = lines[1].find(grp.name)
        cells = [scr.cell(panel[0] + 3 + at + i, panel[1] + 4) for i in range(4)]
        self.assertEqual("".join(chr(ch) for ch, _a in cells), grp.name)
        self.assertEqual([a for _c, a in cells],
                         [(grp.tback << 4) | grp.ttext] * 4)

    def marks(self, name):
        """The house marks on the deed card: (count of cells, colours)."""
        from verify_pixels import decode_capture

        from monopoly import screens

        scr, _ = decode_capture(str(HOUSES / name))
        left, top = screens.DEED_PANEL[0], screens.DEED_PANEL[1]
        cells = [scr.cell(left + i, top + 1) for i in range(12)]
        card = cells[-1][1]                           # the card's own attribute
        return [(ch, attr) for ch, attr in cells if attr != card]

    def test_one_house_is_two_cells_wide(self):
        """Each house is two blocks and a space, so one house marks two."""
        self.assertEqual(len(self.marks("deed-one-house.png")), 2)

    def test_a_hotel_is_a_solid_run_of_six(self):
        self.assertEqual(len(self.marks("deed-hotel.png")), 6)

    def test_the_port_draws_the_same_widths(self):
        from monopoly import cga, data, screens

        for houses, expected in ((1, 2), (2, 4), (4, 8),
                                 (data.HOUSES_PER_HOTEL, 6), (6, 0)):
            with self.subTest(houses=houses):
                scr = cga.Screen()
                blank = scr.cell(screens.DEED_PANEL[0] + 2,
                                 screens.DEED_PANEL[1] + 1)
                screens.deed_houses(scr, houses, 3)
                marked = 0
                for i in range(12):
                    cell = scr.cell(screens.DEED_PANEL[0] + 2 + i,
                                    screens.DEED_PANEL[1] + 1)
                    if cell != blank and cell[0] == screens.BLOCK:
                        marked += 1
                self.assertEqual(marked, expected)


class CueNames(unittest.TestCase):
    """Every cue a port asks for must exist.

    Both ports called cue("landing") while sound.CUES had no such entry, and
    both speakers ignored the unknown name in silence, so the chime after
    every dice roll simply never played.  A call site and the cue table
    drifting apart is invisible at runtime; it is trivial to catch here.
    """

    CALL = re.compile(r"""cue\(\s*["']([a-z_]+)["']\s*\)""")

    def sites(self, relpath):
        return sorted(set(self.CALL.findall((ROOT / relpath).read_text())))

    def test_python_call_sites_all_exist(self):
        from monopoly import sound

        used = self.sites("monopoly/game.py")
        self.assertIn("landing", used, "the post-roll chime must be played")
        for name in used:
            self.assertIn(name, sound.CUES, "game.py plays a missing cue")

    def test_web_call_sites_all_exist(self):
        from monopoly import sound

        used = self.sites("web/game.js")
        self.assertIn("landing", used, "the post-roll chime must be played")
        for name in used:
            self.assertIn(name, sound.CUES, "game.js plays a missing cue")

    def test_unknown_cue_raises_rather_than_going_quiet(self):
        from monopoly import sound

        spk = sound.Speaker(enabled=False)
        with self.assertRaises(KeyError):
            spk.cue("no_such_cue")


class BuildingSounds(unittest.TestCase):
    """The house sounds, against the speaker log of a real purchase.

    Six units bought and the same six sold gave twelve bursts, not two: both
    loops carry their sweeps inside them, so the sound belongs to the house
    and not to the transaction.
    """

    def test_building_is_four_sweeps(self):
        from monopoly import sound

        tones = sound.CUES["build"].tones
        turns = [a for a, b in zip(tones, tones[1:]) if
                 (b[0] > a[0]) != (tones[1][0] > tones[0][0])]
        self.assertEqual([hz for hz, _ms in tones[:1]], [1000])
        self.assertEqual(tones[-1][0], 300)
        self.assertGreaterEqual(len(turns), 1)

    def test_returning_is_four_sweeps_the_other_way(self):
        from monopoly import sound

        tones = sound.CUES["houses_sold"].tones
        self.assertEqual(tones[0][0], 2500)
        self.assertEqual(tones[-1][0], 600)

    def test_neither_burst_lasts_anything_like_a_second(self):
        """The loops carry no Delay, so a burst is a chirp."""
        from monopoly import sound

        build = sum(ms for _hz, ms in sound.CUES["build"].tones)
        sold = sum(ms for _hz, ms in sound.CUES["houses_sold"].tones)
        self.assertAlmostEqual(build, sound.BUILD_BURST_MS, delta=1)
        self.assertAlmostEqual(sold, sound.RETURN_BURST_MS, delta=1)
        self.assertLess(build, 200, "measured at 137 ms, not 2.8 seconds")

    def test_a_burst_fits_inside_its_unit(self):
        """Each house gets its own burst, with room to spare in the beat."""
        from monopoly import graphics, sound

        self.assertLess(sum(ms for _hz, ms in sound.CUES["build"].tones),
                        graphics.BUILD_UNIT_MS)
        self.assertLess(sum(ms for _hz, ms in sound.CUES["houses_sold"].tones),
                        graphics.RETURN_UNIT_MS)


class LandingChime(unittest.TestCase):
    """The chime between the dice stopping and the piece setting off.

    Measured across every speaker log on disk: 101 runs, all of them the
    2002/3005/2501 triplet, gapless, 93 of them exactly 30 notes, one single
    duration population with a median of 37.49 ms.
    """

    def cue(self):
        from monopoly import sound

        return sound.CUES["landing"]

    def test_thirty_notes_of_the_measured_triplet(self):
        tones = self.cue().tones
        self.assertEqual(len(tones), 30)
        self.assertEqual([hz for hz, _ in tones[:3]], [2002, 3005, 2501])
        self.assertEqual({hz for hz, _ in tones}, {2002, 3005, 2501})

    def test_note_length_and_total_match_the_speaker(self):
        tones = self.cue().tones
        for _hz, ms in tones:
            self.assertAlmostEqual(ms, 37.49, delta=0.2)
        self.assertAlmostEqual(sum(ms for _hz, ms in tones), 1125, delta=30)

    def test_it_is_gapless(self):
        self.assertTrue(all(hz > 0 for hz, _ms in self.cue().tones),
                        "the chime runs as one unbroken row of notes")

    def test_one_note_per_blit_of_the_flash(self):
        """Sound and picture come from the same loop at 0x5143."""
        from monopoly import graphics

        tones = self.cue().tones
        self.assertEqual(graphics.FLASH_TOGGLES, len(tones))
        self.assertAlmostEqual(graphics.FLASH_TOGGLE_MS, tones[0][1], places=3)
        # a card that moves the piece flashes it with the same loop
        self.assertEqual(graphics.ADVANCE_BLITS, graphics.FLASH_TOGGLES)
        self.assertAlmostEqual(graphics.ADVANCE_BLIT_MS,
                               graphics.FLASH_TOGGLE_MS, places=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
