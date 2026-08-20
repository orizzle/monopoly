"""Entry point: python3 -m monopoly"""

from __future__ import annotations

import argparse
import sys

from .display import Terminal, supports_truecolor
from .game import Game, Quit


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="monopoly",
        description="Monopoly 5.1 (1985, Don Phillip Gibson) ported to Python.")
    ap.add_argument("--seed", type=int, default=None,
                    help="fix the dice and card shuffle, for reproducible games")
    ap.add_argument("--sound", choices=["auto", "tone", "bell", "off"],
                    default="auto",
                    help="how to make the dice-roll beeps (default: auto)")
    ap.add_argument("--ansi16", action="store_true",
                    help="use the terminal's 16 colours instead of exact CGA RGB")
    args = ap.parse_args(argv)

    truecolor = not args.ansi16 and supports_truecolor()
    with Terminal(truecolor=truecolor) as term:
        try:
            Game(term, seed=args.seed, audio=args.sound).run()
        except (KeyboardInterrupt, Quit, EOFError):
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
