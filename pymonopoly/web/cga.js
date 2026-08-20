// CGA 80x25 text mode.
//
// The font is the IBM CGA 8x8 ROM font, pulled out of the emulator's video
// ROM rather than redrawn, and the palette is the hardware's sixteen.
//
// One detail matters and is easy to get wrong: with blink disabled the
// background nibble is four bits, not three, so all sixteen colours are
// available as backgrounds.  The original relies on that.

export const COLS = 80;
export const ROWS = 25;

// A DOS 6.22 machine had VGA, and VGA text mode 3 is 720x400: nine-dot cells
// sixteen scanlines tall.  CGA's 80x25 is 8x8 doubled to 640x400, which is
// the chunkier look.  The board is unaffected either way -- that is 320x200
// graphics, where the game draws its own 8x8 glyphs whatever the adapter.
export const CELL_W = 9;
export const CELL_H = 16;
export const WIDTH = COLS * CELL_W;    // 720
export const HEIGHT = ROWS * CELL_H;   // 400

export class TextScreen {
  constructor(data) {
    // The VGA font when it is available, the CGA one as a fallback.
    this.vga = !!data.fontVga;
    this.font = base64Bytes(this.vga ? data.fontVga : data.font);
    this.cellH = this.vga ? 16 : 8;
    this.palette = data.textPalette;
    this.cells = new Uint16Array(COLS * ROWS);   // char | attr << 8
    this.attr = 0x07;
    this.cursor = null;                          // [col, row], 1-based
    this.clear();
  }

  clear(attr = this.attr) {
    const blank = 0x20 | (attr << 8);
    this.cells.fill(blank);
  }

  setAttr(fg, bg) { this.attr = (fg & 0x0f) | ((bg & 0x0f) << 4); }

  // 1-based, like the original's GotoXY.
  put(col, row, ch, attr = this.attr) {
    if (col < 1 || col > COLS || row < 1 || row > ROWS) return;
    this.cells[(row - 1) * COLS + (col - 1)] =
      (ch & 0xff) | ((attr & 0xff) << 8);
  }

  write(col, row, text, attr = this.attr) {
    for (let i = 0; i < text.length; i++) {
      this.put(col + i, row, text.charCodeAt(i) & 0xff, attr);
    }
  }

  centre(row, text, attr = this.attr, left = 1, right = COLS) {
    const col = left + Math.floor(((right - left + 1) - text.length) / 2);
    this.write(col, row, text, attr);
  }

  box(x0, y0, x1, y1, attr) {
    for (let y = y0; y <= y1; y++) {
      for (let x = x0; x <= x1; x++) this.put(x, y, 0x20, attr);
    }
  }

  // Renders into a 720x400 ImageData.  Each cell is nine dots wide: the
  // ninth repeats the eighth for the box-drawing range 0xC0-0xDF so the line
  // characters join up, and is background for everything else.  That rule is
  // the VGA hardware's, not a choice made here.
  render(img) {
    const px = img.data;
    const W = COLS * CELL_W;
    const H = this.cellH;
    for (let row = 0; row < ROWS; row++) {
      for (let col = 0; col < COLS; col++) {
        const cell = this.cells[row * COLS + col];
        const ch = cell & 0xff;
        const attr = cell >> 8;
        const fg = this.palette[attr & 0x0f];
        const bg = this.palette[(attr >> 4) & 0x0f];
        const glyph = ch * H;
        const joins = ch >= 0xc0 && ch <= 0xdf;
        for (let gy = 0; gy < H; gy++) {
          const bits = this.font[glyph + gy];
          const y = row * H + gy;
          for (let gx = 0; gx < CELL_W; gx++) {
            let on;
            if (gx < 8) on = bits & (0x80 >> gx);
            else on = joins ? (bits & 1) : 0;
            const c = on ? fg : bg;
            const x = col * CELL_W + gx;
            const o = (y * W + x) * 4;
            px[o] = c[0]; px[o + 1] = c[1]; px[o + 2] = c[2]; px[o + 3] = 255;
          }
        }
      }
    }
    if (this.cursor) this.paintCursor(img);
  }

  // The cursor is drawn by the CRTC, not by a character: a two-scanline bar
  // across the bottom of the cell.
  paintCursor(img) {
    const [col, row] = this.cursor;
    if (col < 1 || col > COLS || row < 1 || row > ROWS) return;
    const cell = this.cells[(row - 1) * COLS + (col - 1)];
    const fg = this.palette[(cell >> 8) & 0x0f];
    const W = COLS * CELL_W;
    const H = this.cellH;
    const px = img.data;
    for (const gy of [H - 2, H - 1]) {
      const y = (row - 1) * H + gy;
      for (let gx = 0; gx < CELL_W; gx++) {
        const x = (col - 1) * CELL_W + gx;
        const o = (y * W + x) * 4;
        px[o] = fg[0]; px[o + 1] = fg[1]; px[o + 2] = fg[2]; px[o + 3] = 255;
      }
    }
  }
}

export function base64Bytes(s) {
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
