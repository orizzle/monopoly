# Monopoly 5.1, in Python

A port of *Monopoly 5.1* — Don Phillip Gibson, 19 December 1985, written in
Turbo Pascal 3.0 for MS-DOS — reconstructed from the original binaries.

Nothing here was transcribed from a manual. The board, price and colour-group
tables were decoded out of `MONOCODE.CHN`; the screen layouts were measured
from captures of the original running under DOSBox; and the game rules were
recovered from the program's own strings and from a few kilobytes of the
author's Pascal source that survive in the slack space of `MONOGRAF.GRA`.

```
python3 -m monopoly              # play
python3 -m monopoly --seed 7     # reproducible dice and card shuffle
python3 -m monopoly --ansi16     # for terminals without 24-bit colour
```

Two to four players, hotseat. There is no computer opponent — there wasn't one
in 1985 either, whatever the abandonware listings say.

## How faithful is it

The original runs in 80×25 colour text mode for everything except the board,
which it draws in CGA 320×200 four-colour graphics. Text screens are grids of
character-and-attribute cells, so they can be reproduced *exactly*, and that is
what `tools/compare_screens.py` measures: it draws a screen from
`monopoly/screens.py`, renders it through the CGA ROM font, and diffs the
result against DOSBox's own output.

```
$ python3 tools/compare_screens.py
PASS  01-player1.png       title screen, one name entered
PASS  02-player2.png       title screen, two names entered
PASS  11-bob-land.png      landed on unowned property
PASS  12-purchased.png     property purchased
PASS  play-16.png          railroad title deed card
PASS  play-09.png          utility title deed card
PASS  play-08.png          street rent owed
PASS  play-11.png          utility rent owed
PASS  biz-01.png           business menu

all exact
```

Each of those is 0 differing pixels out of 256,000.

**Exact:** the title and player-entry screen, the message panel, all three
prompt styles, all three title deed card layouts (street, railroad, utility),
the business menu, the cash boxes, and the holdings map. The board *figure* decodes from
`MONOGRAF.GRA` and matches the emulator to within the nine pixels of the
player tokens drawn over it.

**Not yet exact:** the dice sprite on the board screen — the original draws two
isometric cubes procedurally, and this port draws simpler dice. Token
placement is measured for the bottom edge and extrapolated to the other three.
Screens not yet captured (jail, auctions, house building, bankruptcy, the
endgame) are laid out to the same rules but have not been diffed -- reaching
them under the emulator needs specific game situations that are awkward to
drive by script.

**Deliberately different:** in a terminal the board is drawn in text mode,
because a terminal cannot switch to CGA graphics. `Game.board_frame()` produces
the real 320×200 rendering for anyone who wants it.

## Artwork

The board figure is *not* included here. It lives in `MONOGRAF.GRA`, which
ships with the original game; `monopoly/graphics.py` loads it from a copy you
already have, looking in the working directory and a `game/` subdirectory.
Without it the port falls back to the text-mode board and everything still
works.

The card decks are reimplemented from their effects rather than copied.

## Layout

| | |
|---|---|
| `monopoly/data.py` | Board, price and colour-group tables decoded from `MONOCODE.CHN` |
| `monopoly/cards.py` | Chance and Community Chest, modelled as effects |
| `monopoly/rules.py` | Rent, mortgages, building, tax — pure functions |
| `monopoly/state.py` | `Ply[]` and `Owner[]`, using the original's field names |
| `monopoly/cga.py` | 80×25 text mode: palette, ROM font, cell grid, renderer |
| `monopoly/graphics.py` | CGA 320×200 mode and the board figure |
| `monopoly/screens.py` | Every screen layout, with its measured constants |
| `monopoly/display.py` | Terminal front end and keyboard input |
| `monopoly/game.py` | Turn loop and player interaction |
| `monopoly/save.py` | Save and resume |

Tools, none of which are needed to play:

| | |
|---|---|
| `tools/capture.py` | Drives the original under DOSBox and captures its screens |
| `tools/extract_layout.py` | Describes a capture as panels and coloured text runs |
| `tools/verify_pixels.py` | Calibrates the renderer against captures |
| `tools/compare_screens.py` | Diffs the port's screens against the original |
| `tools/verify_graphics.py` | The same, for the 320×200 board screen |

## The CGA font

`monopoly/cga.py` embeds the IBM CGA 8×8 ROM font. It was not typed in: a
24-byte COM program filled video memory at `B800:0000` with characters 0–255,
the resulting screen was captured, and each cell was de-doubled back to its
native 8×8 bitmap. `tools/verify_pixels.py` closes the loop — decoding a
capture to cells and re-rendering it reproduces the original bit-for-bit,
which is only possible if the font and palette are both correct.

## Rules worth knowing

Two mechanics are the author's own, not Parker Brothers':

- **Mortgages accrue interest.** Standard Monopoly charges 10% once, on
  redemption. Here interest is charged every time your turn comes round, and
  you are offered the chance to stop it by repaying the principal.
- **The bank lends.** Short of cash, you are advanced the difference and must
  clear it before you move again.

Income tax asks whether you want the flat rate or the calculated 10%, then
tells you whether you chose well. Auctions are run by the players — the
program asks who won and for how much, exactly as the original does.

Version 3.x overcharged when unmortgaging; the author fixed it in 4.1, and a
fragment of the buggy expression is still legible in `MONOGRAF.GRA`. The
corrected formula is used here, and `tests/test_rules.py` guards against the
old one coming back.

## Tests

```
python3 -m unittest discover -s tests
```

49 tests. The rule tests check the decoded tables against the figures the
original prints on its own title deed cards. `tests/test_game.py` drives whole
games headlessly with an auto-player and asserts invariants — nobody ends with
negative cash, bankrupt players hold nothing, houses never exceed zoning.
`tests/test_fidelity.py` runs the pixel comparisons above, and skips itself if
the reference captures are absent.

## Credit

*Monopoly* is a registered trademark of Parker Brothers. The 1985 MS-DOS
adaptation is by Don Phillip Gibson, who released it as shareware and said in
its readme that he had written it to teach himself Turbo Pascal.
