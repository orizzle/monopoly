// Turbo Pascal 3.0's Random, decompiled from MONOPOLY.COM and verified
// against the real 8086 code under emulation.
//
//   Random at 0x10E6 shifts the seed left 8 into a 40-bit al:bx:cx, rotates
//   the whole thing right one bit to get seed*2^7, adds the original seed
//   back off the stack -- so the multiplier is 2^7+1 = 129 -- adds
//   0x361962E9, stores it back and returns the HIGH word.
//
//   The Random(n) wrapper at 0x10DA takes that word, shifts it right one to
//   clear the sign bit, and divides by n keeping the remainder.
//
// Randomize is never called by the game, so a stock copy always starts from
// seed 0.  That is measured, not assumed: an instrumented DOSBox watching
// RandSeed logged 453 draws of a live game and every one matched this.
//
// JavaScript bitwise operators are 32-bit *signed*, so the multiply is done
// in floating point and folded back with modulo rather than with `*` and
// `|0`, which would overflow into negatives.

const MASK = 0x100000000;
const MULTIPLIER = 129;
const INCREMENT = 907633385; // 0x361962E9

export class TurboRandom {
  constructor(seed = 0) {
    this.seed = ((seed % MASK) + MASK) % MASK;
  }

  // The core at 0x10E6: advance the seed, return the high word.
  nextWord() {
    this.seed = (this.seed * MULTIPLIER + INCREMENT) % MASK;
    return Math.floor(this.seed / 65536);
  }

  // Random(n) -- the wrapper at 0x10DA.  Yields 0 .. n-1.
  random(n) {
    return (this.nextWord() >>> 1) % n;
  }

  // The game rolls a die as Random(6)+1.
  die() {
    return this.random(6) + 1;
  }
}
