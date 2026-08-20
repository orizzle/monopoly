"""Check monopoly.tprandom against the real machine code.

tprandom.py is a decompilation, and a decompilation is a claim about what
some bytes do.  Rather than trust the reading, this runs the actual 8086
instructions out of MONOPOLY.COM under an emulator and compares, so the
Python and the 1985 code have to agree value for value.

If MONOPOLY.COM or the unicorn emulator is missing the test skips: it is a
cross-check on the port, not a dependency of it.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from monopoly.tprandom import TurboRandom

GAME = Path("/vmstore/claude/monopoly/game/MONOPOLY.COM")

# Memory addresses inside the loaded .COM image.
RANDOM_N = 0x10DA        # the Random(n) wrapper
SEED_ADDR = 0x01FC       # RandSeed
RETURN_MAGIC = 0x9000    # a parking address to detect the final ret


def _load():
    """Returns a callable random_n(seed, n) -> (result, new_seed)."""
    from unicorn import UC_ARCH_X86, UC_MODE_16, Uc
    from unicorn.x86_const import (UC_X86_REG_AX, UC_X86_REG_CS,
                                   UC_X86_REG_DS, UC_X86_REG_ES,
                                   UC_X86_REG_IP, UC_X86_REG_SP,
                                   UC_X86_REG_SS)

    image = GAME.read_bytes()

    def random_n(seed: int, n: int) -> tuple[int, int]:
        mu = Uc(UC_ARCH_X86, UC_MODE_16)
        mu.mem_map(0, 0x100000)
        # A .COM loads at offset 0x100 with every segment register equal.
        mu.mem_write(0x100, image)
        for reg in (UC_X86_REG_CS, UC_X86_REG_DS,
                    UC_X86_REG_ES, UC_X86_REG_SS):
            mu.reg_write(reg, 0)
        mu.reg_write(UC_X86_REG_SP, 0xFFFC)
        # The return address the wrapper's final `ret` will jump to.
        mu.mem_write(0xFFFC, RETURN_MAGIC.to_bytes(2, "little"))
        mu.mem_write(SEED_ADDR, (seed & 0xFFFFFFFF).to_bytes(4, "little"))
        mu.reg_write(UC_X86_REG_AX, n)
        mu.reg_write(UC_X86_REG_IP, RANDOM_N)
        mu.emu_start(RANDOM_N, RETURN_MAGIC)
        out = mu.reg_read(UC_X86_REG_AX) & 0xFFFF
        new = int.from_bytes(mu.mem_read(SEED_ADDR, 4), "little")
        return out, new

    return random_n


class TurboRandomMatchesTheBinary(unittest.TestCase):
    def setUp(self) -> None:
        if not GAME.exists():
            self.skipTest(f"{GAME} not present")
        try:
            self.random_n = _load()
        except ImportError:
            self.skipTest("unicorn not installed")

    def test_seed_advances_identically(self) -> None:
        """The LCG itself: multiplier 129, increment 0x361962E9."""
        seed = 0x2E024489
        mine = TurboRandom(seed)
        for step in range(200):
            _, hw_seed = self.random_n(mine.seed, 6)
            mine.next_word()
            self.assertEqual(
                mine.seed, hw_seed,
                f"seed diverged at step {step}: "
                f"python 0x{mine.seed:08X} != 8086 0x{hw_seed:08X}")

    def test_random_n_matches_for_many_seeds_and_bounds(self) -> None:
        """Random(n) = ((seed >> 16) >> 1) mod n, for the n the game uses."""
        seeds = (0, 1, 0x2E024489, 0x12345678, 0xFFFFFFFF, 0x80000000,
                 0x7FFFFFFF, 0xDEADBEEF)
        for seed in seeds:
            for n in (2, 3, 4, 6, 8, 16, 40, 2500):
                want, want_seed = self.random_n(seed, n)
                r = TurboRandom(seed)
                got = r.random(n)
                self.assertEqual(
                    got, want,
                    f"Random({n}) from seed 0x{seed:08X}: "
                    f"python {got} != 8086 {want}")
                self.assertEqual(r.seed, want_seed)

    def test_matches_a_real_captured_game(self) -> None:
        """The generator against 453 draws taken from the running program.

        Captured with an instrumented DOSBox watching writes to RandSeed while
        the real game played.  This pins down two things the disassembly alone
        could not: that the port's generator tracks the original over a whole
        game rather than just in isolation, and that the starting seed is 0 --
        the first value written is 0x361962E9, which is 0*129 + 907633385.

        The seed lives at DS:0x01FC, and DS is 0x10DC while the chained code
        runs, not the 0x0192 the code segment sits at.  Watching the address
        computed from the code segment logs nothing at all, which is what made
        this measurement hard to get.
        """
        import json

        path = Path(__file__).parent / "fixtures" / "real_seed_sequence.json"
        if not path.exists():
            self.skipTest("capture fixture not present")
        seeds = json.loads(path.read_text())["seeds"]
        self.assertGreater(len(seeds), 100)

        r = TurboRandom(0)
        for i, want in enumerate(seeds):
            r.next_word()
            self.assertEqual(
                r.seed, want,
                f"draw {i}: port has 0x{r.seed:08X}, the real program had "
                f"0x{want:08X}")

    def test_predicts_the_dice_a_real_game_rolled(self) -> None:
        """Every roll of a real three-minute game, from the seed alone.

        Each fixture entry records the draw index the program was at when it
        stored a pair of dice, so the two draws feeding that roll are the two
        immediately before it.  Getting all of them right from TurboRandom(0)
        is the end-to-end claim: same generator, same seed, same dice.
        """
        import json

        path = Path(__file__).parent / "fixtures" / "real_rolls.json"
        if not path.exists():
            self.skipTest("roll fixture not present")
        rolls = json.loads(path.read_text())["rolls"]
        self.assertGreaterEqual(len(rolls), 10)

        last = max(r["draw_index"] for r in rolls)
        r = TurboRandom(0)
        d6 = [(r.next_word() >> 1) % 6 + 1 for _ in range(last + 2)]
        for entry in rolls:
            i = entry["draw_index"]
            self.assertEqual(
                (d6[i - 2], d6[i - 1]),
                (entry["die1"], entry["die2"]),
                f"roll at draw {i}: port predicts "
                f"{d6[i-2]}+{d6[i-1]}, the real program rolled "
                f"{entry['die1']}+{entry['die2']}")

    def test_die_is_one_to_six(self) -> None:
        r = TurboRandom(0x2E024489)
        rolls = [r.die() for _ in range(600)]
        self.assertTrue(all(1 <= d <= 6 for d in rolls))
        self.assertEqual(len(set(rolls)), 6, "all six faces should appear")


if __name__ == "__main__":
    unittest.main()


class PortSpendsTheGeneratorLikeTheOriginal(unittest.TestCase):
    """The port must draw in the same places, not just from the same stream.

    Sharing a generator and a seed is not enough for the dice to agree: the
    original spends eight draws on every tumble frame before it takes the two
    that become the dice.  A port that draws only the two would read the same
    sequence at the wrong offsets and roll different numbers from the same
    seed.
    """

    def test_a_roll_costs_eight_draws_per_frame_plus_two(self) -> None:
        from monopoly.game import Game

        for frames in (26, 30, 32, 35):
            g = Game.__new__(Game)          # no terminal or artwork needed
            g.rng = TurboRandom(0)
            before = g.rng.seed
            steps = 0
            probe = TurboRandom(0)
            g.tumble_draws(frames)
            g.rng.die()
            g.rng.die()
            # count how many advances reproduce the port's final seed
            while probe.seed != g.rng.seed and steps < 10_000:
                probe.next_word()
                steps += 1
            self.assertEqual(
                steps, frames * 8 + 2,
                f"{frames} tumble frames should cost {frames * 8 + 2} draws")
            self.assertNotEqual(before, g.rng.seed)

    def test_measured_turn_lengths_all_fit_the_model(self) -> None:
        """Every inter-roll gap measured from the real game is 8n + 2."""
        measured = (210, 242, 250, 258, 266, 282)
        for gap in measured:
            self.assertEqual(
                (gap - 2) % 8, 0,
                f"a {gap}-draw turn is not a whole number of tumble frames")
