"""Record a session of the port to an MP4, with its sound.

Rather than filming a terminal, this drives the game with a scripted player and
renders each screen the way the hardware would have: text screens through the
CGA ROM font at 640x400, and the board through the 320x200 graphics mode scaled
2x to match.  Sound cues are collected with timestamps as they fire and mixed
into one track afterwards, so the beeps land on the frames that triggered them.

    python3 tools/record.py --seconds 60 --out gameplay.mp4

Needs ffmpeg for the final mux; everything before that is done here.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from monopoly import sound
from monopoly.display import NullTerminal
from monopoly.game import Game, Quit

# How long each kind of screen stays up.  The animated ones take their timing
# from the game itself; these are the reading pauses in between.
DWELL_MS = 1100
PROMPT_MS = 1500
FPS = 20

# The canvas matches what DOSBox puts on screen: text mode fills 640x400, and
# the 320x200 graphics board sits at native size in the top-left corner with
# the rest black.  Keeping the same geometry makes the recording directly
# comparable with a capture of the original.
CANVAS = (640, 400)


class ScriptedPlayer(NullTerminal):
    """Answers prompts by preference order, and types the opening names."""

    def __init__(self, names, prefer="pgb", budget=6000):
        super().__init__()
        self.names = list(names) + [""]
        self.prefer = prefer
        self.budget = budget
        self.calls = 0

    def _spend(self):
        self.calls += 1
        if self.calls > self.budget:
            raise Quit

    def choose(self, allowed):
        self._spend()
        if not allowed:
            return "\r"
        for want in self.prefer:
            if want in allowed:
                return want
        return allowed[0]

    def read_key(self):
        self._spend()
        return "\r"

    def read_line(self, scr, x, y, width, attr, initial=""):
        self._spend()
        return self.names.pop(0) if self.names else ""

    def paint(self, scr, force=False):
        pass


class Recorder(Game):
    """A Game that draws to a film strip instead of a terminal."""

    def __init__(self, term, seed=None, limit_ms=60_000):
        super().__init__(term, seed=seed, audio="off")
        self.frames: list[tuple[object, int]] = []
        self.cues: list[tuple[int, tuple]] = []
        self.clock_ms = 0
        self.limit_ms = limit_ms

    @property
    def animating(self) -> bool:
        return True

    # -- capture ----------------------------------------------------------

    def _emit(self, image, ms: int) -> None:
        self.frames.append((image, ms))
        self.clock_ms += ms
        if self.clock_ms >= self.limit_ms:
            raise Quit

    def _text_frame(self):
        return self.scr.render(scanline_double=True)

    def _board_image(self, frame):
        """The board at native 320x200, top-left on a black 640x400 canvas.

        That is where the emulator leaves it when the video mode changes, so
        the two recordings line up.
        """
        from PIL import Image

        canvas = Image.new("RGB", CANVAS, (0, 0, 0))
        canvas.paste(frame.render(scale=1), (0, 0))
        return canvas

    def emit_tones(self, sequence) -> None:
        """The tumble's clicks, captured at the moment they would sound."""
        if sequence:
            self.cues.append((self.clock_ms, tuple(sequence)))

    def cue(self, name: str) -> None:
        # There is no "roll" cue any more: the tumble's sound is generated a
        # cube at a time from the game's own draws, and the recorder picks it
        # up through rattle() rather than from the cue table.
        entry = sound.CUES.get(name)
        if entry is not None:
            self.cues.append((self.clock_ms, entry.tones))

    # -- the game's own drawing calls -------------------------------------

    def _show(self) -> None:
        self._emit(self._text_frame(), DWELL_MS)

    def show_board(self, message=None) -> None:
        frame = self.board_frame(message)
        if frame is None:
            super().show_board(message)
            self._emit(self._text_frame(), DWELL_MS)
            return
        self._emit(self._board_image(frame), PROMPT_MS)

    def _emit_board(self, frame, ms: int) -> None:
        self._emit(self._board_image(frame), ms)

    def animate_move(self, who: int, start: int, steps: int) -> None:
        if steps <= 0:
            return
        for frame, ms in self.move_frames(who, start, steps):
            self._emit(self._board_image(frame), ms)
        self.state.players[who].position = (start + steps) % 40


def build_audio(cues, total_ms: int, rate: int = sound.SAMPLE_RATE) -> bytes:
    """Mix the cue tones into one track, each at the moment it fired."""
    import numpy as np

    track = np.zeros(int(rate * total_ms / 1000) + rate, dtype=np.int32)
    for start_ms, tones in cues:
        pcm = np.frombuffer(sound.square_wave(list(tones), rate), dtype="<i2")
        at = int(rate * start_ms / 1000)
        end = min(at + len(pcm), len(track))
        if end > at:
            track[at:end] += pcm[:end - at]
    np.clip(track, -32768, 32767, out=track)
    return track.astype("<i2").tobytes()


def write_video(frames, workdir: Path, fps: int = FPS) -> int:
    """Write one PNG per output frame, holding each screen for its duration."""
    n = 0
    for image, ms in frames:
        repeats = max(1, round(ms * fps / 1000))
        for _ in range(repeats):
            image.save(workdir / f"f{n:06d}.png")
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="gameplay.mp4")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--names", nargs="*", default=["ann", "ben", "cid"])
    ap.add_argument("--fps", type=int, default=FPS)
    ap.add_argument("--roll-seconds", type=float, default=0.0,
                    help="stretch the dice tumble to roughly this many "
                         "seconds so it is watchable.  0 keeps the "
                         "original's measured 1.2s.")
    ap.add_argument("--crf", type=int, default=10,
                    help="x264 quality, lower is better.  Do not pass 0: "
                         "H.264 lossless needs the High 4:4:4 Predictive "
                         "profile, which ordinary players cannot decode.")
    args = ap.parse_args()

    term = ScriptedPlayer(args.names)
    rec = Recorder(term, seed=args.seed, limit_ms=int(args.seconds * 1000))
    if args.roll_seconds > 0:
        # Each cycle is three frames of 40 ms.
        rec.roll_cycles = max(1, round(args.roll_seconds * 1000
                                       / (3 * sound.FRAME_MS)))
        print(f"roll stretched to {rec.roll_cycles} cycles "
              f"({rec.roll_cycles * 3 * sound.FRAME_MS / 1000:.1f}s) "
              f"-- the original rolls for "
              f"{sound.ROLL_FRAMES * sound.FRAME_MS / 1000:.1f}s")
    if rec.board_art is None:
        print("MONOGRAF.GRA not found: the board would fall back to text mode.",
              file=sys.stderr)
    try:
        rec.run()
    except Quit:
        pass

    if not rec.frames:
        print("nothing was recorded", file=sys.stderr)
        return 1

    total_ms = sum(ms for _, ms in rec.frames)
    print(f"{len(rec.frames)} screens, {total_ms/1000:.1f}s, "
          f"{len(rec.cues)} sound cues")

    with tempfile.TemporaryDirectory(prefix="monopoly-rec-") as tmp:
        work = Path(tmp)
        count = write_video(rec.frames, work, args.fps)
        wav = work / "track.wav"
        sound.write_wav(build_audio(rec.cues, total_ms), wav)
        print(f"{count} video frames at {args.fps} fps")

        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-framerate", str(args.fps), "-i", str(work / "f%06d.png"),
            "-i", str(wav),
            # A rapidly toggling handful of pixels is exactly what a lossy
            # encoder throws away, so keep the quality high and tell x264 it
            # is looking at flat-colour animation.
            #
            # The output has to be 4:2:0 High profile: 4:4:4 and true
            # lossless both need High 4:4:4 Predictive, which ffmpeg decodes
            # happily but browsers, QuickTime and hardware decoders do not --
            # they render it as garbage.  Doubling the frame with
            # nearest-neighbour first is what makes 4:2:0 safe here: every
            # source pixel becomes a uniform 2x2 block, so the chroma
            # half-resolution sampling reads a flat block and throws nothing
            # away.
            "-vf", "scale=iw*2:ih*2:flags=neighbor",
            "-c:v", "libx264", "-preset", "slow", "-crf", str(args.crf),
            "-tune", "animation", "-g", str(args.fps),
            "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.0",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            "-shortest", str(args.out),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            print(r.stderr[-2000:], file=sys.stderr)
            return r.returncode

    size = Path(args.out).stat().st_size
    print(f"wrote {args.out} ({size/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
