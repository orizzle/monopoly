# Monopoly 5.1 — a measured port

*Monopoly 5.1* was written by Don Phillip Gibson in Turbo Pascal 3.0 and
released on 19 December 1985. This repository holds a reimplementation of it
in Python and in HTML/JavaScript, rebuilt from the original binaries rather
than from memory or from a manual.

The rule that governs the whole project is that nothing is implemented from
taste. Every layout, colour, delay and sound in the port traces back to
something measured: a table decoded out of `MONOCODE.CHN`, a screen diffed
against DOSBox's output pixel for pixel, or a tone read off the 8253 through
an instrumented emulator. Where a thing could not be measured, the comment
next to it says so.

* **[`pymonopoly/`](pymonopoly/)** — the port, its test suite and the
  measuring tools. Start with [its README](pymonopoly/README.md).
* **`shots/`** — captures of the original running, used as test fixtures.
  The five-minute audit in `tests/test_fidelity.py` replays 415 of them:
  each is parsed back into game state, redrawn by the port, and diffed.
* **`dbx/`** — DOSBox configurations used for the captures.

## The 1985 program is not included here

`MONOPOLY.COM`, `MONOCODE.CHN`, `MONOCODE.000` and `MONOGRAF.GRA` are Gibson's
commercial release. They are not this project's to redistribute, so this public
repository does not carry them, and `game/` is in `.gitignore`.

To run the measuring tools, or the fidelity tests that need the real board
figure, put your own copy of those files in `game/`. The port finds them from
there. Without them the game itself still plays — the board figure is the only
asset it needs, and the tests that require it skip rather than fail.

Trademarks in the board and card text belong to their owners; this is a study
of a piece of 1985 software, not a Monopoly product.
