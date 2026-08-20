"""Turbo Pascal 3.0's Random, decompiled from the Borland runtime.

The port cannot share a seed with the original while it draws from Python's
Mersenne Twister, so this is the 1985 generator itself, recovered from
MONOPOLY.COM.  Two routines matter, both in the runtime linked into the .COM:

Randomize, at file offset 0x0E14 (memory 0x0F14):

    mov ah,0x2c        ; DOS get-system-time
    call 0x957         ; the runtime's INT 21h thunk
    mov [0x1fe],cx     ; CH=hour, CL=minute       -> seed, high word
    mov [0x1fc],dx     ; DH=second, DL=hundredths -> seed, low word
    ret

So RandSeed is a 32-bit variable at DS:0x01FC and it is seeded from the wall
clock to a hundredth of a second.  That is measured, not assumed: two runs of
the original driven with byte-identical keystrokes diverge on the very first
die.

Random, at 0x10E6, is a plain LCG written the long way round because the 8086
has no 32-bit multiply.  It shifts the seed left 8 into a 40-bit al:bx:cx
(the `xor cl,cl` that completes the shift also clears CF for what follows),
rotates the whole thing right one bit to get seed*2**7, then adds the
original seed back off the stack -- so the multiplier is 2**7 + 1 = 129 --
adds 0x361962E9, stores it back, and returns the *high* word in ax.

The Random(n) wrapper at 0x10DA takes that word, `shr ax,1` to clear the sign
bit, and divides by n keeping the remainder.
"""

from __future__ import annotations

MASK = 0xFFFFFFFF
MULTIPLIER = 129          # 2**7 + 1, from the rcr/add pair
INCREMENT = 0x361962E9    # 907633385


class TurboRandom:
    """The 1985 generator, seed and all."""

    def __init__(self, seed: int = 0) -> None:
        self.seed = seed & MASK

    @classmethod
    def from_clock(cls, hour: int, minute: int, second: int,
                   hundredths: int) -> "TurboRandom":
        """Reproduce Randomize for a given wall-clock time.

        CX (hour, minute) becomes the high word and DX (second, hundredths)
        the low word, exactly as the two stores at 0x0F19 and 0x0F1D leave
        them.
        """
        return cls(((hour & 0xFF) << 24) | ((minute & 0xFF) << 16)
                   | ((second & 0xFF) << 8) | (hundredths & 0xFF))

    def next_word(self) -> int:
        """The core at 0x10E6: advance the seed, return the high word."""
        self.seed = (self.seed * MULTIPLIER + INCREMENT) & MASK
        return self.seed >> 16

    def random(self, n: int) -> int:
        """Random(n) -- the wrapper at 0x10DA.  Yields 0 .. n-1."""
        return (self.next_word() >> 1) % n

    # The game rolls a die as Random(6)+1.
    def die(self) -> int:
        return self.random(6) + 1
