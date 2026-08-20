"""PC speaker sound.

The 1985 program beeps while the dice roll.  Its animation loop, at file
offset 0x2400 of MONOCODE.CHN, is a `for i := 1 to 20` that redraws the token
and calls the Turbo Pascal 3 CRT routines:

    mov  al,[0x3B79]      ; if the sound flag is set
    or   ax,ax
    jnz  +3
    mov  ax,0xBB8         ;   Sound(3000)
    call Sound
    mov  ax,0x28
    call Delay            ; Delay(40)

Three tones appear in the loop -- 2000, 3000 and 2500 Hz -- each held for
40 ms, with NoSound at the end.  The byte at DS:0x3B79 is the on/off flag that
F1 toggles, which is why every Sound call is guarded by it.

A PC speaker is not available here, so the tones are synthesised as square
waves (the speaker's actual timbre, not a sine) and handed to whatever audio
backend exists.  If none does, the terminal bell stands in, and if that is
unwanted the whole thing degrades to silence.  Playback is asynchronous: the
original's beeps overlap its animation rather than blocking it.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

# The dice.  Measured off the hardware rather than read out of the code: with
# MONO_LOGIO=1 the emulator logs every write to the 8253 and the speaker gate,
# and a run in which no key was pressed for twenty seconds shows what actually
# happens.
#
#   * 463 bursts of three tones each, one burst every 41.56 ms (median 41.50)
#   * each tone sounds for about 1.2 ms, with the gate closed between them
#   * the frequencies are random across 19..7504 Hz -- Random(i*2500) for
#     i = 1, 2, 3, which is the routine at CHN 0x4F74
#   * and it does not stop after a fixed number of frames: the dice tumble
#     from the moment the turn starts until the player presses a key
#
# The old constants here described a fixed thirty-frame warble on 2000/3000/
# 2500 Hz.  No such tones appear anywhere in the log; that reading of the
# code was wrong, and it is what made the roll sound wrong in both ports.
RATTLE_SLOTS = 3            # Sound(Random(i*2500)) for i := 1 to 3
RATTLE_RANGE = 2500         # the multiplier inside Random()
RATTLE_HOLD_MS = 1.2        # measured; the source's Delay(1)
RATTLE_PERIOD_MS = 41.5     # measured burst-to-burst period
FRAME_MS = RATTLE_PERIOD_MS

# Kept only so a recording can ask for a bounded tumble, and so headless runs
# spend the generator by a fixed count instead of by wall-clock time.
ROLL_CYCLES = 10
ROLL_FRAMES = ROLL_CYCLES * RATTLE_SLOTS

# The tumble is open-ended, so its audio has to be handed to the backend in
# pieces.  One process per 41 ms burst would spawn twenty-four players a
# second and most would be dropped; a third of a second at a time sounds
# continuous and keeps at most two in flight.
RATTLE_CHUNK_MS = 332

# A sweep that would run for ages at its original step rate is compressed to
# this, so the game does not stall on a sound effect.
SWEEP_CAP_MS = 700
# How long one whole burst of the building sounds lasts.  Neither loop has a
# Delay in it, so the length is just how fast the FOR loop runs: measured off
# the speaker across six houses bought and six sold, a median of 137 ms going
# up (6204 iterations over four legs) and 42 ms coming down (2904 over four).
BUILD_BURST_MS = 137
RETURN_BURST_MS = 42
SWEEP_STEPS = 24

SAMPLE_RATE = 22050
AMPLITUDE = 0.22  # a square wave at full scale is unpleasant


def rattle_burst(freqs) -> list[tuple[int, int]]:
    """One cube's clicks, then silence to fill the measured period.

    The three frequencies come from the game's own generator -- they are
    Random(i*2500) -- so sounding them and spending the sequence are the same
    act, which is why the dice a player gets depend on when they stop the
    roll.
    """
    seq: list[tuple[int, int]] = []
    for hz in freqs:
        seq.append((int(hz), max(1, round(RATTLE_HOLD_MS))))
        seq.append((0, 1))
    rest = RATTLE_PERIOD_MS - len(freqs) * (RATTLE_HOLD_MS + 1)
    if rest > 0:
        seq.append((0, round(rest)))
    return seq


def square_wave(sequence: list[tuple[int, int]],
                rate: int = SAMPLE_RATE) -> bytes:
    """16-bit mono PCM for a list of (hz, ms) tones.

    A square wave rather than a sine: the PC speaker was a one-bit device and
    could only produce one.
    """
    out = bytearray()
    level = int(32767 * AMPLITUDE)
    for hz, ms in sequence:
        count = max(1, int(rate * ms / 1000))
        if hz <= 0:
            out += b"\x00\x00" * count
            continue
        period = rate / hz
        for n in range(count):
            value = level if (n % period) < (period / 2) else -level
            out += struct.pack("<h", value)
    return bytes(out)


def write_wav(pcm: bytes, path: str | Path, rate: int = SAMPLE_RATE) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


# --------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------


class Backend:
    name = "null"
    available = True

    def play(self, sequence: list[tuple[int, int]]) -> None:
        pass

    def close(self) -> None:
        pass


class NullBackend(Backend):
    """Silence, but still a working speaker object."""


class BellBackend(Backend):
    """The terminal bell: one \\a per burst, not per tone."""

    name = "bell"

    def __init__(self) -> None:
        self._out = None

    def play(self, sequence: list[tuple[int, int]]) -> None:
        import sys

        try:
            sys.stdout.write("\a")
            sys.stdout.flush()
        except Exception:
            pass


class FfplayBackend(Backend):
    """Synthesise the tones and hand the WAV to ffplay."""

    name = "ffplay"

    # Sound effects are incidental.  If the previous ones are still playing,
    # drop the new one instead of queueing: an unbounded spawn rate will bury
    # the machine in player processes, and on a host with no real audio device
    # they block rather than exiting on their own.
    MAX_CONCURRENT = 2
    TEMP_SLOTS = 4

    def __init__(self) -> None:
        self.exe = shutil.which("ffplay")
        self.available = self.exe is not None
        self._tmp = Path(tempfile.mkdtemp(prefix="monopoly-snd-"))
        self._procs: list[subprocess.Popen] = []
        self._slot = 0

    def play(self, sequence: list[tuple[int, int]]) -> None:
        if not self.available:
            return
        self._reap()
        if len(self._procs) >= self.MAX_CONCURRENT:
            return
        path = self._tmp / f"tone{self._slot % self.TEMP_SLOTS}.wav"
        self._slot += 1
        try:
            write_wav(square_wave(sequence), path)
            self._procs.append(subprocess.Popen(
                [self.exe, "-nodisp", "-autoexit", "-loglevel", "quiet",
                 str(path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL))
        except Exception:
            # An unusable audio device should never take the game down.
            self.available = False

    def _reap(self) -> None:
        alive = []
        for p in self._procs:
            if p.poll() is None:
                alive.append(p)
        self._procs = alive

    def close(self) -> None:
        for p in self._procs:
            try:
                p.kill()
            except Exception:
                pass
        self._procs.clear()
        shutil.rmtree(self._tmp, ignore_errors=True)


def pick_backend(preference: str = "auto") -> Backend:
    """Choose an output route.  `preference` is auto, tone, bell or off.

    "auto" resolves to silence when stdout is not a terminal.  Nothing is
    listening to a piped or automated run, and spawning a player per effect
    there is pure cost -- a test suite driving thousands of turns will happily
    start thousands of processes otherwise.
    """
    if preference == "off":
        return NullBackend()
    if preference == "bell":
        return BellBackend()
    if preference == "auto" and not interactive():
        return NullBackend()
    if preference in ("auto", "tone"):
        ff = FfplayBackend()
        if ff.available and _audio_device_present():
            return ff
        ff.close()
        return NullBackend() if preference == "tone" else BellBackend()
    return NullBackend()


def interactive() -> bool:
    """Whether a person is plausibly listening."""
    import sys

    try:
        return bool(sys.stdout.isatty())
    except Exception:
        return False


def _audio_device_present() -> bool:
    return os.path.exists("/dev/snd") or os.path.exists("/dev/dsp")


# --------------------------------------------------------------------------
# Speaker
# --------------------------------------------------------------------------


class Speaker:
    """The game's sound, with the original's on/off flag.

    `enabled` mirrors the byte at DS:0x3B79 that F1 toggles; when it is off no
    tone is produced, exactly as the original skips its Sound calls.
    """

    def __init__(self, preference: str = "auto", enabled: bool = True) -> None:
        self.backend = pick_backend(preference)
        self.enabled = enabled

    @property
    def route(self) -> str:
        return self.backend.name

    def tone(self, hz: int, ms: int) -> None:
        if self.enabled:
            self.backend.play([(hz, ms)])

    def play(self, sequence: list[tuple[int, int]]) -> None:
        if self.enabled and sequence:
            self.backend.play(sequence)

    def roll(self) -> None:
        """The dice-roll beeps."""
        self.cue("roll")

    def cue(self, name: str) -> None:
        """Play a named effect from the recovered cue list.

        An unknown name is a bug, not a silence: both ports called
        cue("landing") for months while no such cue existed, and the old
        CUES.get(...) swallowed it, so the chime after every roll was simply
        missing.  Fail loudly instead; test_cue_names_exist keeps the call
        sites honest so this cannot reach a player.
        """
        try:
            entry = CUES[name]
        except KeyError:
            raise KeyError(f"no such cue: {name!r}") from None
        self.play(list(entry.tones))

    def toggle(self) -> bool:
        self.enabled = not self.enabled
        return self.enabled

    def close(self) -> None:
        self.backend.close()


# --------------------------------------------------------------------------
# The full cue list
#
# Every Sound() call site in MONOCODE.CHN and MONOCODE.000 was located by
# scanning for calls to the Turbo Pascal CRT Sound routine, and each one's
# argument read from the `mov ax,imm16` in front of it.  Seventeen sites load
# the frequency from a FOR-loop variable instead of an immediate -- those are
# glides, and their endpoints come from the loop's bounds.  Each cue records
# the file offset it was taken from.
#
# Event names are inferred from the inline string literals nearest each call
# site, which in Turbo Pascal 3 sit inside the procedure that prints them.
# Where that inference is thin the cue says so.
# --------------------------------------------------------------------------


def sweep(start: int, end: int, step_ms: int = 1,
          cap_ms: int = SWEEP_CAP_MS) -> list[tuple[int, int]]:
    """A glide, as the original's FOR loop over the frequency produces.

    Sampled down to SWEEP_STEPS segments when running it at the original rate
    would take longer than cap_ms.
    """
    span = abs(end - start) + 1
    natural = span * step_ms
    if natural <= cap_ms:
        direction = 1 if end >= start else -1
        return [(hz, step_ms)
                for hz in range(start, end + direction, direction)]
    per = max(1, cap_ms // SWEEP_STEPS)
    return [(round(start + (end - start) * i / (SWEEP_STEPS - 1)), per)
            for i in range(SWEEP_STEPS)]


def burst(legs: list[tuple[int, int]], total_ms: float,
          steps_per_leg: int = 12) -> list[tuple[int, float]]:
    """Several of the original's FOR-loop sweeps, run back to back.

    `sweep` assumes a millisecond a step, which is right for the loops that
    carry a Delay.  These do not: the buy- and return-houses loops are bare
    `for i := a to b do Sound(i)`, so a leg lasts exactly as long as the loop
    takes to run -- about a fiftieth of a millisecond an iteration on the
    machine this was measured on.  Four legs of it come to a chirp of about a
    seventh of a second, not the two and three quarter seconds a step-per-
    millisecond reading gives.

    The measured total is shared between the legs in proportion to how many
    iterations each one runs, which is what decides their relative lengths.
    """
    spans = [abs(b - a) + 1 for a, b in legs]
    whole = sum(spans)
    out: list[tuple[int, float]] = []
    for (a, b), span in zip(legs, spans):
        n = max(2, min(steps_per_leg, span))
        per = total_ms * span / whole / n
        for i in range(n):
            out.append((round(a + (b - a) * i / (n - 1)), per))
    return out


def shaped(start: int, end: int, ramp_ms: int,
           lead_ms: int = 0, tail_ms: int = 0,
           steps: int = 48) -> list[tuple[int, int]]:
    """A hold, a glide, and another hold, sampled for the WAV backends.

    Going to jail is not a bare ramp: it sits on its first note, falls, and
    sits on its last.  Sampling only the ramp lost both holds and, with the
    old duration, three quarters of the sound.
    """
    out: list[tuple[int, int]] = []
    if lead_ms:
        out.append((start, round(lead_ms)))
    per = max(1, round(ramp_ms / steps))
    for i in range(steps):
        hz = round(start + (end - start) * i / (steps - 1))
        out.append((hz, per))
    if tail_ms:
        out.append((end, round(tail_ms)))
    return out


def jail_scale() -> list[tuple[int, int]]:
    """The descending scale played when a piece goes to jail.

    Measured twice off the speaker -- once from a Chance card, once from
    three doubles -- and both agree: nine notes from 1000 Hz down to 200 in
    hundreds.  Each sounds for 234 ms and then slides to the next over about
    51 ms, the divisor stepping through every value in between at roughly
    1.2 ms apiece; the last note is held 471 ms.  Rendering it as one smooth
    1000->200 glide loses the tune, and holding each note for the whole beat
    loses the slide.
    """
    notes = list(range(1000, 200, -100))
    out: list[tuple[int, int]] = []
    for i, hz in enumerate(notes):
        out.append((hz, 234))
        nxt = notes[i + 1] if i + 1 < len(notes) else 200
        for k in range(1, 4):                    # the slide, in three steps
            out.append((round(hz + (nxt - hz) * k / 3), 17))
    out.append((200, 471))
    return out


class Cue:
    """A named sound effect."""

    __slots__ = ("name", "tones", "source", "note", "glide", "hold")

    def __init__(self, name, tones, source, note="", glide=None, hold=(0, 0)):
        self.name = name
        self.tones = tuple(tones)
        self.source = source
        self.note = note
        # (lead_ms, tail_ms): some cues sit on their first and last note
        # before and after the ramp.  Going to jail holds 1000 Hz for 234 ms,
        # falls to 200 over 2.1 s, then sits on 200 for another 471 ms; a
        # bare ramp is not the same sound.
        self.hold = tuple(hold)
        # (start_hz, end_hz, total_ms) when the cue is one of the original's
        # frequency loops.  `tones` samples such a loop into steps so it can be
        # written to a WAV; a front end able to ramp a frequency should use
        # this instead, because the original is a continuous glide and the
        # sampled form audibly staircases.
        self.glide = glide

    def __repr__(self):
        return f"<Cue {self.name} {len(self.tones)} tones from {self.source}>"


def _cues() -> dict[str, Cue]:
    c = {}

    def add(name, tones, source, note="", glide=None, hold=(0, 0)):
        c[name] = Cue(name, tones, source, note, glide, hold)

    def glide_ms(start, end):
        """How long `for i := start downto end do Sound(i)` takes.

        The loop at CHN 0x25E5 carries a constant 100 through the runtime's
        arithmetic helpers on every pass, which reads as a per-step delay of
        roughly 100/i ms; summing that over the range gives 100*ln(start/end).
        The helpers themselves were not decoded, so this is an inference from
        the constant and the loop bounds, not a measurement -- but it lands on
        a fast swoop, which a 700 ms staircase certainly is not.
        """
        import math
        lo, hi = min(start, end), max(start, end)
        return max(60, round(100 * math.log(hi / lo)))

    add("start", sweep(900, 800, 400) + sweep(1600, 1900, 2),
        "CHN 0x2053, 0x209C", "program start, while the board is drawn")
    # No "roll" cue: the tumble is not a fixed pattern.  It is generated a
    # frame at a time by rattle_burst() from the game's own generator, and it
    # runs until the player presses a key.  See the note at the top of this
    # file for the measurement.
    # The chime between the dice stopping and the piece setting off, and
    # again before a card walks the piece to a new square.  Ten cycles of
    # 2002/3005/2501 Hz, one note per blit of the flash loop at 0x5143.
    #
    # Measured, not inferred: 101 runs of it across every speaker log on disk
    # are all this triplet, all gapless, 93 of them exactly 30 notes long,
    # with a single duration population at a median of 37.49 ms -- so 1125 ms
    # in all, ending within a millisecond of the first step chirp.  The
    # landing routine at 0x6620 is indeed silent, which is what an earlier
    # note here concluded; the sound comes from the flash loop instead.  That
    # note left this cue undefined while both ports called cue("landing"),
    # and a missing name used to play nothing at all -- so there was no chime
    # after a roll in either port.  Speaker.cue now raises on an unknown name.
    add("landing", [(2002, 37.5), (3005, 37.5), (2501, 37.5)] * 10,
        "CHN 0x5143", "the flash after the dice stop, and before a card move")
    # The third failed roll in jail, under "You have rolled 3 / times and
    # must pay."  Disassembled at CHN load 0xE271: the sound flag is tested,
    # then Sound(440), Delay(300), NoSound, Delay(1000) -- one flat note and
    # a second of quiet before the two lines are wiped off the board.
    add("jail_third", [(440, 300)], "CHN 0xE271",
        "the third failed roll out of jail")
    # NOT a landing sound: 0x3A32 sits in the key handler behind
    # `cmp ax,0x3c` (F2).
    add("save", [(340, 150), (0, 150), (340, 150)], "CHN 0x3A32",
        "F2 save-game confirmation, two beeps")
    add("pay", [(900, 5), (1500, 5)], "CHN 0x3200/0x32C4",
        "cash leaving a player")
    add("receive", [(900, 5), (1500, 5)], "CHN 0x3414/0x358B",
        "cash arriving; the same pair as `pay` in a second routine")
    add("spend", [(320, 200)], "CHN 0x71C9", "paying for houses")
    # Four sweeps, not one, and once per unit returned rather than once per
    # sale.  Read off the loop bounds inside the return-houses loop at CHN
    # load 0x99C1-0x9B04 -- down 2500->1000, up 1000->1300, down 1300->400,
    # up 400->600, then Delay(50) -- and confirmed against the speaker: a
    # sale of six units played six identical bursts of exactly those four
    # legs, 465 ms apart.  This port had the first leg alone, played once.
    add("houses_sold",
        burst([(2500, 1000), (1000, 1300), (1300, 400), (400, 600)],
              RETURN_BURST_MS),
        "CHN 0x99C1/0x9A75/0x9AA7/0x9AD9",
        "one unit going back to the bank")
    # Four sweeps, from the loop bounds inside the buy-houses routine at CHN
    # load 0xA07B-0xA135: up 1000->2500, down 2500->500, up 1000->2000, down
    # 2000->300, then Delay(50) and NoSound.  The three sweeps this port had
    # were taken from a routine outside that code and were the wrong shape.
    #
    # All four sit inside the per-unit loop, so this plays once for every
    # house bought rather than once for the purchase: buying six units gave
    # six identical bursts on the speaker, 514 ms apart.
    add("build",
        burst([(1000, 2500), (2500, 500), (1000, 2000), (2000, 300)],
              BUILD_BURST_MS),
        "CHN 0xA07B/0xA0AD/0xA0DF/0xA111", "buying houses and hotels")
    add("trade", sweep(1000, 2500) + sweep(2500, 500), "CHN 0x7323/0x7355",
        "a deal between players")
    add("auction", [(320, 200)], "CHN 0x7A4D", "a lot sold at auction")
    add("interest", [(780, 200)], "CHN 0x5597", "mortgage interest charged")
    add("error", [(150, 200)], "CHN 0x2ABF",
        "not your turn / cannot afford / must raise money")
    add("reject", [(200, 600)], "CHN 0x49A1", "input refused")
    add("accept", [(560, 600)], "CHN 0x4A38", "input accepted")
    add("jail", jail_scale(),
        "measured: nine notes 1000..200 Hz, 234 ms each with a ~51 ms slide "
        "between them, the last held 471 ms",
        "sent to jail")
    # The three-doubles routine at 0x54AF is a warble (370 down to 270 and
    # back, repeated) then Delay(100), then 370->800 and 800->1000.  0x2874 is
    # that last ascending sweep; the glide covers the rising part, which is
    # what carries the sound.
    add("doubles", sweep(370, 1000), "CHN 0x2842/0x2874",
        "three doubles in a row: a rising sweep",
        glide=(370, 1000, 260))
    # The raise-money screen's own sound, from inside that routine (CHN load
    # 0x59A4-0x59EE): 130 Hz held 1.6 s, then a slow fall to 1 Hz at 15 ms a
    # step.  It plays when the player is told to find the money, which is
    # also the moment they may be declared out -- the port had the cue but
    # never played it.
    # Two different sounds, and the port had them confused.  The line "YOU
    # DON'T HAVE ENOUGH CASH." is followed by `for i := 1 to 5 do begin
    # Sound(150); Delay(200); NoSound; Delay(200) end` (CHN load 0x5817-
    # 0x5844): five flat beeps.  The long fall belongs to the branch below
    # it, the one that prints "YOU HAVE NO ASSETS." and "YOU ARE OUT OF THE
    # GAME!" -- so it plays only when the player is actually finished.
    add("no_cash", [(150, 200), (0, 200)] * 5, "CHN load 0x5817-0x5844",
        "cannot meet a payment, but still has something to sell")
    # Measured from a trace of a player who really was finished: 130 Hz held
    # 1521 ms, a fall to 19 Hz over 1528 ms, then 19 Hz for 826 ms.  The
    # source loop runs `downto 1`, but the 8253's divisor runs out of room
    # below about 19 Hz, which is where it stops.
    add("bankrupt", shaped(130, 19, 1528, 1521, 826),
        "measured: 130 Hz 1521 ms, 130->19 Hz over 1528 ms, 19 Hz 826 ms",
        "out of the game")
    add("turn_end", [(100, 500)], "CHN 0x7C87", "turn handed on")
    add("winner", [(380, 300), (380, 300)], "000 overlay",
        "endgame; the overlay's two 380 Hz calls")

    # --- movement --------------------------------------------------------
    # Measured, not guessed: the speaker's timer writes were logged out of an
    # instrumented emulator while a token travelled.  Every square produces
    # one fast descending chirp from about 900 Hz down to 800, restarting at
    # 900 for the next square -- 101 steps a square, and the tone count scaled
    # exactly with the distance rolled.
    #
    # An earlier version of this file claimed the original was silent while a
    # piece moved.  That was wrong, and wrongly reasoned: it read this port's
    # own move loop, which had no sound in it, and concluded something about
    # the original.
    add("step", sweep(900, 800), "measured: PIT writes during a move",
        "one zip per square: `for i := 900 downto 800 do Sound(i)` at "
        "CHN 0x4DA4 with no delay in the loop, so about 2 ms -- a "
        "tick, not a glide.  NoSound and Delay(400) follow it.", glide=(900, 800, 3))
    # The rising tone crossing a corner, measured the same way as the step
    # chirp: the PIT writes were logged against the token's own position, and
    # the sweep appeared identically after square 10 and after square 20.
    #
    # 301 tones running 1602 -> 1903 Hz.  The 2-3 Hz stepping is the timer's
    # divisor quantisation -- at 1600 Hz one divisor step is about 2 Hz -- so
    # the program is counting `for i := 1600 to 1900 do Sound(i)`, which is
    # exactly the 301 values observed.  Duration is scaled from the step
    # chirp by tone count (301/101 * 70 ms), the loops running at the same
    # rate; that part is derived, the endpoints are measured.
    # The cash counter ticks as it counts: measured at one 901 Hz blip per
    # $5 step, the steps about 19 ms apart.
    # The counter's two voices.  Both loops are the same shape -- print the
    # running total, Sound(f), Delay(5), NoSound, Delay(15) -- but money
    # coming in ticks at 1500 Hz and money going out at 900 Hz.  Two call
    # sites each: CHN 0x603D and 0x6304 for the rise, 0x5F79 and 0x618D for
    # the fall.  The port used the falling tone for both.
    add("money", [(900, 5)], "CHN 0x5F79, 0x618D",
        "one tick per $5 as a total counts down")
    add("money_up", [(1500, 5)], "CHN 0x603D, 0x6304",
        "one tick per $5 as a total counts up")
    add("corner", sweep(1600, 1900),
        "measured: 1602->1903 Hz over 706.8 ms at a corner crossing",
        "rising tone crossing a corner square",
        glide=(1600, 1900, 707))
    return c


CUES: dict[str, Cue] = _cues()
