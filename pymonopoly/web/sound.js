// The PC speaker, as a one-bit device.
//
// The original drives the 8253 to make square waves, so the timbre is a
// square wave and nothing else -- no envelope, no decay.
//
// The cues are not invented: they come from data.js, which carries the tone
// sequences recovered from the Sound call sites in MONOCODE.CHN.  An earlier
// version of this file made up plausible-sounding beeps, and they were wrong
// in both pitch and length.
//
// Browsers refuse to start audio until the user has interacted with the page,
// so the context is created lazily and resumed on the first keypress.

import { DATA } from "./data.js";

export class Speaker {
  constructor() {
    this.ctx = null;
    this.enabled = true;
    this.rollTimer = null;
  }

  resume() {
    if (!this.ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (AC) this.ctx = new AC();
    }
    if (this.ctx && this.ctx.state === "suspended") this.ctx.resume();
  }

  toggle() { this.enabled = !this.enabled; return this.enabled; }

  // sequence: [[hz, ms], ...].  Scheduled onto one oscillator so a long cue
  // is a continuous run of tones rather than a stack of overlapping notes.
  play(sequence, when = 0) {
    if (!this.enabled || !this.ctx || !sequence || !sequence.length) return 0;
    const ctx = this.ctx;
    const gain = ctx.createGain();
    gain.gain.value = 0.0001;
    gain.connect(ctx.destination);
    const osc = ctx.createOscillator();
    osc.type = "square";
    osc.connect(gain);

    let t = ctx.currentTime + when;
    const start = t;
    const level = 0.05;            // a square wave at full scale is unpleasant
    osc.frequency.setValueAtTime(sequence[0][0] || 440, t);
    for (const [hz, ms] of sequence) {
      const dur = Math.max(ms, 1) / 1000;
      if (hz > 0) {
        osc.frequency.setValueAtTime(hz, t);
        gain.gain.setValueAtTime(level, t);
      } else {
        gain.gain.setValueAtTime(0.0001, t);
      }
      t += dur;
      gain.gain.setValueAtTime(0.0001, t);
    }
    osc.start(start);
    osc.stop(t + 0.02);
    return (t - start) * 1000;     // milliseconds of audio scheduled
  }

  // The tumble's clicks.  Measured off the 8253 with MONO_LOGIO: each cube
  // makes three tones of about 1.2 ms with the gate shut between them, and a
  // cube's burst comes round every 41.5 ms.  A frame is two cubes, so it
  // carries six frequencies and covers 83 ms.  They are clicks, not tones --
  // and the frequencies are random, which is why the roll is a rattle rather
  // than the tidy 2000/3000/2500 warble this port used to play over the top.
  rattle(freqs) {
    if (!this.enabled || !this.ctx || !freqs || !freqs.length) return;
    const ctx = this.ctx;
    const t0 = ctx.currentTime;
    const HOLD = 0.0012, PERIOD = 0.0415, SLOTS = 3;
    for (let i = 0; i < freqs.length; i++) {
      const hz = freqs[i];
      if (!(hz > 30)) continue;
      // burst index decides which 41.5 ms window this click sits in
      const at = t0 + Math.floor(i / SLOTS) * PERIOD + (i % SLOTS) * HOLD * 2;
      const gain = ctx.createGain();
      gain.gain.setValueAtTime(0.0001, at);
      gain.gain.setValueAtTime(0.05, at);
      gain.gain.setValueAtTime(0.0001, at + HOLD);
      gain.connect(ctx.destination);
      const osc = ctx.createOscillator();
      osc.type = "square";
      osc.frequency.setValueAtTime(hz, at);
      osc.connect(gain);
      osc.start(at);
      osc.stop(at + HOLD + 0.001);
    }
  }

  cue(name) {
    // A cue that is one of the original's `for i := a downto b do Sound(i)`
    // loops is a continuous glide, so it is rendered as a frequency ramp.
    // Playing the sampled steps instead staircases audibly -- which is what
    // made the go-to-jail sound wrong.
    const g = DATA.glides && DATA.glides[name];
    if (g) { this.glide(g[0], g[1], g[2], g[3] || 0, g[4] || 0); return; }
    const tones = DATA.cues[name];
    // An unknown name means a call site and the cue table have drifted --
    // which is exactly how the post-roll chime went missing.  Say so.
    if (!tones) { console.warn(`no such cue: ${name}`); return; }
    this.play(tones);
  }

  // `lead` and `tail` are the milliseconds the cue sits on its first and
  // last note.  Going to jail holds 1000 Hz for 234 ms, falls to 200 over
  // 2.1 s and then sits on 200 for 471 ms; without the holds -- and with the
  // 161 ms ramp this port used to use -- it was a blip, not a descent.
  glide(from, to, ms, lead = 0, tail = 0) {
    if (!this.enabled || !this.ctx) return;
    const ctx = this.ctx;
    const gain = ctx.createGain();
    gain.connect(ctx.destination);
    const osc = ctx.createOscillator();
    osc.type = "square";
    osc.connect(gain);
    const t = ctx.currentTime;
    // No floor here: the step zip really is about 2 ms, and
    // clamping it to 20 ms turns a tick into a buzz.
    const dur = Math.max(ms, 1) / 1000;
    const l = lead / 1000, tl = tail / 1000;
    gain.gain.setValueAtTime(0.05, t);
    osc.frequency.setValueAtTime(from, t);
    if (l) osc.frequency.setValueAtTime(from, t + l);
    // exponential matches how pitch is heard; the endpoints are never zero
    // so it is safe here.
    osc.frequency.exponentialRampToValueAtTime(Math.max(to, 1), t + l + dur);
    if (tl) osc.frequency.setValueAtTime(Math.max(to, 1), t + l + dur + tl);
    const end = t + l + dur + tl;
    gain.gain.setValueAtTime(0.05, end);
    gain.gain.linearRampToValueAtTime(0.0001, end + 0.01);
    osc.start(t);
    osc.stop(end + 0.02);
  }

  // There is no continuous roll tone.  An earlier version held one
  // oscillator open and stepped it through 2000/3000/2500 Hz, which is what
  // the disassembly seemed to say; the speaker log shows no such tones at
  // any point in a roll.  stopRoll survives only so callers can tidy up.
  stopRoll() {
    if (this.rollTimer) { clearInterval(this.rollTimer); this.rollTimer = null; }
  }
}
