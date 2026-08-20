"""Run the original under emulation and log how it talks to the outside.

Static analysis has been contradicted three times over on one question: how
the game reads the keyboard.  The runtime's ReadKey turns out to be only the
Ctrl-C/Ctrl-S check inside the *output* path, the CHN makes no near call to
it or to the DOS thunk, and there is no INT 16h or BIOS-buffer access in the
chained code at all.  Rather than guess a fourth time, this runs the program
under Unicorn with a minimal DOS/BIOS underneath it and logs every software
interrupt, so the input path identifies itself.

Enough of DOS is implemented to get the loader to chain MONOCODE.CHN and
reach the first prompt; everything else is stubbed loudly rather than
silently, so a missing service shows up as a log line instead of a hang.

    python3 tools/trace_dos.py --stop-on-input
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

GAME = Path("/vmstore/claude/monopoly/game")
SEG = 0x1000                      # the program's segment
BASE = SEG * 16                   # its linear address
ENTRY = BASE + 0x100              # .COM entry point


class Dos:
    """Just enough DOS and BIOS to keep a 1985 Pascal program running."""

    def __init__(self, mu, keys: bytes, verbose: bool):
        self.mu = mu
        self.keys = keys
        self.key_at = 0
        self.verbose = verbose
        self.handles: dict[int, object] = {}
        self.next_handle = 5
        self.log: list[str] = []
        self.int_counts: dict[tuple[int, int], int] = {}
        self.input_calls: list[str] = []
        self.exited = False
        self.out = ""
        self.dta = BASE + 0x80
        self.ip_hits = {}
        self.mode = 3
        self.ports = {}

    # -- registers ------------------------------------------------------
    def r(self, name):
        from unicorn import x86_const as c
        return self.mu.reg_read(getattr(c, "UC_X86_REG_" + name.upper()))

    def w(self, name, v):
        from unicorn import x86_const as c
        self.mu.reg_write(getattr(c, "UC_X86_REG_" + name.upper()), v & 0xFFFF)

    def set_cf(self, on: bool) -> None:
        from unicorn import x86_const as c
        f = self.mu.reg_read(c.UC_X86_REG_EFLAGS)
        f = (f | 1) if on else (f & ~1)
        self.mu.reg_write(c.UC_X86_REG_EFLAGS, f)

    def note(self, msg: str) -> None:
        self.log.append(msg)
        if self.verbose:
            print("   " + msg)

    def next_key(self) -> int:
        if not self.keys:
            return 0x0D
        ch = self.keys[self.key_at % len(self.keys)]
        self.key_at += 1
        return ch

    # -- dispatch -------------------------------------------------------
    def on_intr(self, mu, intno, _user):
        ah = (self.r("ax") >> 8) & 0xFF
        self.int_counts[(intno, ah)] = self.int_counts.get((intno, ah), 0) + 1
        if intno == 0x21:
            self.int21(ah)
        elif intno == 0x10:
            self.int10(ah)
        elif intno == 0x16:
            self.int16(ah)
        elif intno == 0x1A:
            self.w("cx", 0)
            self.w("dx", 0)
        elif intno == 0x20:
            self.exited = True
            mu.emu_stop()
        else:
            self.note(f"unhandled INT {intno:02X} AH={ah:02X}")

    # -- BIOS video -----------------------------------------------------
    def int10(self, ah: int) -> None:
        if ah == 0x00:
            # Remember the mode: the program sets CGA graphics for the board
            # and reads it back, so a stub that always claims 80x25 text
            # makes it think the mode change failed.
            self.mode = self.r("ax") & 0xFF
            self.note(f"set video mode {self.mode:02X}")
        elif ah == 0x0F:
            cols = 40 if self.mode in (0, 1, 4, 5) else 80
            self.w("ax", (self.mode & 0xFF) | (cols << 8))
            self.w("bx", 0)
        elif ah == 0x03:
            self.w("cx", 0x0607)
            self.w("dx", 0)

    # -- BIOS keyboard --------------------------------------------------
    def int16(self, ah: int) -> None:
        self.input_calls.append(f"INT 16h AH={ah:02X}")
        if ah in (0x00, 0x10):
            ch = self.next_key()
            self.w("ax", (0x1C << 8) | ch)
        elif ah in (0x01, 0x11):
            self.w("ax", (0x1C << 8) | (self.keys[0] if self.keys else 0x0D))
            self.set_cf(False)   # ZF handling below
        elif ah == 0x02:
            self.w("ax", 0)

    # -- DOS ------------------------------------------------------------
    def int21(self, ah: int) -> None:
        mu = self.mu
        if ah in (0x01, 0x06, 0x07, 0x08, 0x0A, 0x0B, 0x0C):
            self.input_calls.append(f"INT 21h AH={ah:02X}")

        if ah == 0x4C or ah == 0x00:
            self.exited = True
            mu.emu_stop()
        elif ah == 0x30:
            self.w("ax", 0x0003)
        elif ah == 0x02:
            self.out += chr(self.r("dx") & 0xFF)
            self.set_cf(False)
        elif ah == 0x09:
            addr = self.r("ds") * 16 + self.r("dx")
            s = b""
            while len(s) < 256:
                b = self.mu.mem_read(addr + len(s), 1)
                if b[0] == ord("$"):
                    break
                s += bytes(b)
            text = s.decode("latin-1")
            self.out += text
            self.note(f"AH=09 prints: {text!r}")
            self.set_cf(False)
        elif ah in (0x01, 0x07, 0x08):
            self.w("ax", (self.r("ax") & 0xFF00) | self.next_key())
        elif ah == 0x06:
            dl = self.r("dx") & 0xFF
            if dl == 0xFF:
                self.w("ax", (self.r("ax") & 0xFF00) | self.next_key())
            else:
                self.set_cf(False)
        elif ah == 0x0B:
            self.w("ax", (self.r("ax") & 0xFF00) | 0xFF)   # a key is ready
        elif ah == 0x0A:
            self.buffered_input()
        elif ah == 0x2C:
            self.w("cx", 0x0C1E)
            self.w("dx", 0x1E20)
        elif ah == 0x1A:
            self.dta = self.r("ds") * 16 + self.r("dx")
            self.set_cf(False)
        elif ah == 0x25:
            # Set interrupt vector AL to DS:DX, in a real IVT at linear 0.
            v = self.r("ax") & 0xFF
            self.mu.mem_write(v * 4, (self.r("dx") & 0xFFFF).to_bytes(2, "little")
                              + (self.r("ds") & 0xFFFF).to_bytes(2, "little"))
            self.set_cf(False)
        elif ah == 0x35:
            # Get interrupt vector AL into ES:BX.  Leaving these unset is not
            # harmless: the Delay calibration restores the old timer vector
            # with `mov [es:si],ax`, so a garbage ES scribbles over memory and
            # the program dies with a runtime error far from the real cause.
            v = self.r("ax") & 0xFF
            raw = self.mu.mem_read(v * 4, 4)
            self.w("bx", int.from_bytes(raw[0:2], "little"))
            self.w("es", int.from_bytes(raw[2:4], "little"))
            self.set_cf(False)
        elif ah == 0x3D:
            self.open_file()
        elif ah == 0x3E:
            self.handles.pop(self.r("bx"), None)
            self.set_cf(False)
        elif ah == 0x3F:
            self.read_file()
        elif ah == 0x40:
            self.w("ax", self.r("cx"))
            self.set_cf(False)
        elif ah == 0x42:
            self.seek_file()
        elif ah == 0x44:
            self.w("dx", 0x80)
            self.set_cf(False)
        elif ah == 0x4A:
            self.set_cf(False)
        else:
            self.note(f"unhandled INT 21h AH={ah:02X}")
            self.set_cf(True)

    def buffered_input(self) -> None:
        """AH=0Ah: fill the caller's buffer with a canned line."""
        addr = self.r("ds") * 16 + self.r("dx")
        cap = self.mu.mem_read(addr, 1)[0]
        line = b""
        while len(line) < cap - 1:
            ch = self.next_key()
            if ch == 0x0D:
                break
            line += bytes([ch])
        self.mu.mem_write(addr + 1, bytes([len(line)]))
        self.mu.mem_write(addr + 2, line + b"\r")
        self.note(f"AH=0Ah buffered input -> {line!r}")

    def cstr(self, addr: int) -> str:
        out = b""
        while len(out) < 128:
            b = self.mu.mem_read(addr + len(out), 1)
            if b[0] == 0:
                break
            out += bytes(b)
        return out.decode("latin-1")

    def open_file(self) -> None:
        name = self.cstr(self.r("ds") * 16 + self.r("dx"))
        base = name.split("\\")[-1].split(":")[-1]
        path = GAME / base
        if not path.exists():
            for p in GAME.iterdir():
                if p.name.upper() == base.upper():
                    path = p
                    break
        if not path.exists():
            self.note(f"open FAILED {name}")
            self.w("ax", 2)
            self.set_cf(True)
            return
        h = self.next_handle
        self.next_handle += 1
        self.handles[h] = [path.read_bytes(), 0]
        self.note(f"open {base} -> handle {h} ({len(self.handles[h][0])} bytes)")
        self.w("ax", h)
        self.set_cf(False)

    def read_file(self) -> None:
        h = self.r("bx")
        n = self.r("cx")
        dest = self.r("ds") * 16 + self.r("dx")
        f = self.handles.get(h)
        if f is None:
            self.w("ax", 0)
            self.set_cf(True)
            return
        data, pos = f
        chunk = data[pos:pos + n]
        f[1] = pos + len(chunk)
        if chunk:
            self.mu.mem_write(dest, chunk)
        self.note(f"read handle {h}: {len(chunk)} bytes -> {dest:05X}")
        self.w("ax", len(chunk))
        self.set_cf(False)

    def seek_file(self) -> None:
        h = self.r("bx")
        f = self.handles.get(h)
        off = (self.r("cx") << 16) | self.r("dx")
        if f is None:
            self.set_cf(True)
            return
        whence = self.r("ax") & 0xFF
        f[1] = off if whence == 0 else (
            f[1] + off if whence == 1 else len(f[0]) + off)
        self.w("dx", (f[1] >> 16) & 0xFFFF)
        self.w("ax", f[1] & 0xFFFF)
        self.set_cf(False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", default="ALICE\rBOB\r\r    ")
    ap.add_argument("--max-insns", type=int, default=80_000_000)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    try:
        from unicorn import (UC_ARCH_X86, UC_HOOK_INTR, UC_MODE_16, Uc,
                             UcError)
        from unicorn import x86_const as c
    except ImportError:
        print("unicorn is required: pip install unicorn")
        return 2

    mu = Uc(UC_ARCH_X86, UC_MODE_16)
    mu.mem_map(0, 0x110000)

    image = (GAME / "MONOPOLY.COM").read_bytes()
    mu.mem_write(ENTRY, image)

    # A minimal PSP: INT 20h at offset 0, the top-of-memory segment at
    # offset 2 -- the runtime reads that to size its heap and refuses to
    # start ("Not enough memory") if it is zero -- and a blank command tail.
    mu.mem_write(BASE, b"\xcd\x20")
    mu.mem_write(BASE + 0x02, (0x9000).to_bytes(2, "little"))
    mu.mem_write(BASE + 0x80, b"\x00\r")

    for reg in ("cs", "ds", "es", "ss"):
        mu.reg_write(getattr(c, "UC_X86_REG_" + reg.upper()), SEG)
    mu.reg_write(c.UC_X86_REG_SP, 0xFFFE)
    # A .COM starts with the PSP return address on the stack.
    mu.mem_write(BASE + 0xFFFE, b"\x00\x00")

    dos = Dos(mu, args.keys.encode("latin-1"), args.verbose)
    mu.hook_add(UC_HOOK_INTR, dos.on_intr)

    from collections import deque
    from unicorn import UC_HOOK_CODE
    state = {"n": 0}
    trail = deque(maxlen=48)
    dos.trail = trail

    # Turbo Pascal calibrates Delay at startup: it hooks the timer, spins
    # `loop 0x222` counting passes, and stops when the tick handler sets
    # [cs:0x194] to 0xFF, storing the count at [0x12].  Nothing fires a timer
    # here, so the tick is delivered after a fixed number of passes instead.
    # Being a count rather than a clock reading is the point -- it makes the
    # calibration, and therefore every later Delay, reproducible.
    CALIB_SPIN = BASE + 0x222
    CALIB_FLAG = BASE + 0x194
    TICKS_AFTER = 20_000

    def sample(u, address, size, _u):
        state["n"] += 1
        if address == CALIB_SPIN:
            state["spin"] = state.get("spin", 0) + 1
            if state["spin"] == TICKS_AFTER:
                u.mem_write(CALIB_FLAG, b"\xff")
        trail.append(address - BASE)
        if state["n"] % 4096 == 0:
            off = address - BASE
            dos.ip_hits[off] = dos.ip_hits.get(off, 0) + 1

    mu.hook_add(UC_HOOK_CODE, sample)

    print(f"running MONOPOLY.COM ({len(image)} bytes) under emulation ...")
    try:
        mu.emu_start(ENTRY, 0, count=args.max_insns)
    except UcError as exc:
        ip = mu.reg_read(c.UC_X86_REG_IP)
        cs = mu.reg_read(c.UC_X86_REG_CS)
        print(f"stopped: {exc} at {cs:04X}:{ip:04X}")

    ip = mu.reg_read(c.UC_X86_REG_IP); cs = mu.reg_read(c.UC_X86_REG_CS)
    print(f"halted at {cs:04X}:{ip:04X}  (program-relative 0x{ip:04X})")
    print(f"hot IPs: {sorted(dos.ip_hits.items(), key=lambda kv:-kv[1])[:8]}")
    print(f"port reads: {dos.ports}")

    print("\n--- interrupt traffic (interrupt, AH, count) ---")
    for (i, ah), n in sorted(dos.int_counts.items(),
                             key=lambda kv: -kv[1])[:25]:
        print(f"   INT {i:02X}h AH={ah:02X}  x{n}")

    print("\n--- console input calls, in order (first 20) ---")
    if dos.input_calls:
        for cidx, call in enumerate(dos.input_calls[:20]):
            print(f"   {cidx}: {call}")
        print(f"   ... {len(dos.input_calls)} total")
    else:
        print("   none -- the program never asked for input")

    print(f"\nkeys consumed: {dos.key_at}")
    err = mu.mem_read(BASE + 0x180, 1)[0]
    codes = {0x01:"file does not exist", 0x02:"file not open for input",
             0x03:"file not open for output", 0x04:"file not open",
             0x05:"cannot read from this file", 0x06:"cannot write to this file",
             0x10:"error in numeric format", 0x20:"operation not allowed on a logical device",
             0x21:"not allowed in direct mode", 0x90:"record length mismatch",
             0x91:"seek beyond end of file", 0x99:"unexpected end of file",
             0xF0:"disk write error", 0xFF:"file disappeared"}
    print(f"\nTurbo Pascal runtime error code: 0x{err:02X} "
          f"({codes.get(err,'unknown')})" if err else "\nno runtime error")

    print("\n--- last 48 instruction addresses before it stopped ---")
    print("   " + " ".join(f"{a:04X}" for a in dos.trail))

    print("\n--- what it drew to video memory (B800) ---")
    vram = mu.mem_read(0xB8000, 80*25*2)
    for row in range(25):
        line = "".join(chr(vram[(row*80+col)*2]) if 32 <= vram[(row*80+col)*2] < 127
                       else " " for col in range(80)).rstrip()
        if line.strip():
            print(f"{row+1:2d}| {line}")

    if dos.out.strip():
        print(f"DOS text output: {dos.out[:300]!r}")
    for line in dos.log[:25]:
        print("   " + line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
