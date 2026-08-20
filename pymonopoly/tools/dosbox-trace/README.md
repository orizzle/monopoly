# Instrumented DOSBox

Tracing and deterministic input for the 1985 program, added to DOSBox 0.74-3.
The guest binary is never modified — everything here lives in the emulator, so
what runs is the real MONOPOLY.COM.

## Why

The program blocks in `INT 16h AH=00` until a key arrives, so it cannot be
driven reproducibly from outside: a keystroke lands whenever the window
manager delivers it, and the game branches on *when*. Feeding keys from inside
the emulator removes wall-clock time from the input path.

This also settled a question three rounds of static analysis had got wrong.
The trace shows the game calling the runtime's `KeyPressed` and `ReadKey`
constantly:

```
561243 INT16 AH=01 from 0192:0860
556965 INT16 AH=00 from 0192:087C
```

0x0860 and 0x087C are the return addresses of the two `int 0x16` instructions
at 0x85E and 0x87A. Those huge counts are DOSBox re-running the instruction
while `AH=00` blocks — which is exactly why patching those routines in the
guest to return immediately made the game drown in thousands of keys a second.

## Build

```sh
curl -LO https://downloads.sourceforge.net/project/dosbox/dosbox/0.74-3/dosbox-0.74-3.tar.gz
tar xzf dosbox-0.74-3.tar.gz && cd dosbox-0.74-3
cp /path/to/monolog.h include/
patch -p1 < /path/to/dosbox-0.74-3-trace.patch
./configure && make -j
```

Needs `libsdl1.2-dev`. Everything is off unless the environment asks for it, so
an unpatched-feeling DOSBox is just the binary with no variables set.

## Environment

| variable | meaning |
| --- | --- |
| `MONO_LOG` | file to append trace lines to; unset disables all logging |
| `MONO_KEYS` | canned key stream, hex ASCII bytes, cycled forever |
| `MONO_RATE` | polls of `INT 16h AH=01` before the next key is offered (default 64) |
| `MONO_STOP` | stop offering keys once this many have been consumed |
| `MONO_LOGINT` | log every `INT 16h`/`INT 21h` console call with its caller |
| `MONO_WATCH` | guest physical address to log writes to |
| `MONO_WATCHLEN` | length of the watched range (default 4) |

`MONO_LOGINT` is separate on purpose: it produces about half a million lines a
minute, and the `fflush` on each one slows the emulator enough that the game
never reaches its first dice roll.

The memory watch hooks `mem_writew_inline` in `include/paging.h`, not the
`mem_writew()` helper in `memory.cpp` — the CPU core stores through the inline
via `SaveMw`, so a hook on the public function never fires.

## Example

Play with canned input and freeze at a fixed point in program time:

```sh
MONO_LOG=/tmp/t.log MONO_RATE=64 MONO_STOP=400 \
MONO_KEYS=414c4943450d424f420d0d200d200d200d \
  ./src/dosbox -conf dosbox.conf
```

## The data segment

The chained code runs with **`CS=0192` but `DS=10DC`** — a separate data
segment. Every address computed off the code segment logs nothing, which is
what made the seed and the dice so hard to find. With the right base:

| variable | guest address | physical |
| --- | --- | --- |
| `RandSeed` | DS:0x01FC | 0x10FBC |
| dice | DS:0x0264, DS:0x0266 | 0x11024, 0x11026 |

`MONO_LOGINT=1` prints `ds=` at every INT 16h, which is how to recover this if
the load address ever moves.

## What it established

Watching both ranges in one ordered log, so each roll's draw index is a count
rather than a guess:

- 453 consecutive `RandSeed` values match `TurboRandom(0)` exactly. The seed
  starts at **0** — the first value written is 0x361962E9, which is
  `0*129 + 907633385`.
- 19 of 19 dice rolls in a three-minute game are predicted from that seed.
- Attributing each draw to its call site (the caller sits at `SS:SP+4` when the
  seed is stored, two frames above `Random`'s core) gives the whole
  consumption model:

  | caller | arg | what |
  | --- | --- | --- |
  | 4FA7 | 2500/5000/7500 | the beep, `for i := 1 to 3 do Random(i*2500)` |
  | 5627 / 5653 | 8 | each die's art, 8 drawings of 636 bytes |
  | 56B9 / 56C5 | 6 | the dice themselves |
  | 4D0B | 16…2 | the deck shuffle, descending |
  | AD0E | 100 | an eighth site, absent from the CHN's near calls |

A tumble frame costs eight draws (art plus beep, twice), and the dice are the
two draws *after* the tumble. Measured turns were 210, 242, 250, 258, 266 and
282 draws — every one of them `8n + 2`.

That is the explanation for the original's apparent nondeterminism: the tumble
runs until a key is pressed, so a slower hand spends more of the sequence
before the dice are taken. Same seed, different pause, different roll.
