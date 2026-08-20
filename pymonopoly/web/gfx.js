// CGA 320x200 four-colour graphics -- the mode the board is drawn in.
//
// The board figure itself comes from MONOGRAF.GRA, decoded on the Python side
// and shipped in data.js.  Everything drawn over it -- pieces, dice, names,
// cash -- is placed from geometry measured against captures of the running
// program, and the same constants feed both builds.

import { base64Bytes } from "./cga.js";

export const WIDTH = 320;
export const HEIGHT = 200;
export const COLS = WIDTH / 8;
export const BLACK = 0, CYAN = 1, MAGENTA = 2, WHITE = 3;

// Text is centred over columns 16..40, not over the whole width: the left
// third of the screen is board, and the original writes only to the right of
// it.  Centring over 1..40 puts every line about eight columns too far left.
const centreUp = (s, g) =>
  g.textLeft + Math.floor(((g.textRight - g.textLeft + 1) - s.length + 1) / 2);
const centreDown = (s, g) =>
  g.textLeft + Math.floor(((g.textRight - g.textLeft + 1) - s.length) / 2);

export class BoardScreen {
  constructor(data) {
    this.d = data;
    this.g = data.geom;
    this.font = base64Bytes(data.font);
    this.palette = data.gfxPalette;
    this.board = base64Bytes(data.board.px);
    this.bw = data.board.w;
    this.bh = data.board.h;
    this.px = new Uint8Array(WIDTH * HEIGHT);
  }

  clear() { this.px.fill(BLACK); }

  point(x, y, c) {
    if (x >= 0 && x < WIDTH && y >= 0 && y < HEIGHT) this.px[y * WIDTH + x] = c;
  }

  blitBoard() {
    for (let y = 0; y < this.bh; y++) {
      for (let x = 0; x < this.bw; x++) {
        this.px[y * WIDTH + x] = this.board[y * this.bw + x];
      }
    }
  }

  glyph(col, row, code, colour) {
    if (col < 1 || col > COLS || row < 1 || row > HEIGHT / 8) return;
    const x0 = (col - 1) * 8, y0 = (row - 1) * 8;
    for (let gy = 0; gy < 8; gy++) {
      const bits = this.font[code * 8 + gy];
      for (let gx = 0; gx < 8; gx++) {
        if (bits & (0x80 >> gx)) this.point(x0 + gx, y0 + gy, colour);
      }
    }
  }

  text(col, row, s, colour = CYAN) {
    for (let i = 0; i < s.length; i++) {
      this.glyph(col + i, row, s.charCodeAt(i) & 0xff, colour);
    }
  }

  // -- board furniture ----------------------------------------------------

  cellBounds(col, row) {
    const D = this.g.dividers;
    return [D[col], D[row], D[col + 1] - 1, D[row + 1] - 1];
  }

  // Position 0..39 -> cell on the 11x11 ring.
  ringCell(pos) {
    if (pos <= 10) return [10 - pos, 10];            // bottom, right to left
    if (pos <= 20) return [0, 10 - (pos - 10)];      // left, bottom to top
    if (pos <= 30) return [pos - 20, 0];             // top, left to right
    return [10, pos - 30];                           // right, top to bottom
  }

  // Pieces pack two-by-two inside a square: `seat` runs along the direction
  // of travel, `lane` steps inward.  The seat order reverses on the top and
  // right edges so the pieces keep a consistent order all the way round --
  // extrapolating the bottom edge to the rest of the board is wrong, and was
  // measured wrong once before across 415 captured screens.
  token(pos, player, inJail = false) {
    const G = this.g;
    const [col, row] = this.ringCell(pos);
    const [x0, y0, x1, y1] = this.cellBounds(col, row);
    // Pascal counts its players from 1, and the seat comes off that index
    // directly -- `seat := p mod 2` -- while the lane comes off the
    // zero-based one.  So the first player takes seat 1 and the second
    // seat 0, the opposite way round from the `player % 2` this used.
    // Measured frame by frame from a two-player game: the first player
    // walks the left edge at y0+6 and the second at y0+2.
    const seat = (player + 1) % 2, lane = Math.floor(player / 2);
    const fwd = G.tokenInset + G.tokenStep * seat;      // 2, 6
    const rev = G.tokenReverse - G.tokenStep * seat;    // 6, 2
    let x, y;

    if (inJail) {
      // Inside the bars.  Measured from a lossless capture of a real
      // jailing (the AVI's JPEG smear is no use for a one-pixel question):
      // the piece occupies x 9..11, y 112..114 of the 123x123 figure, whose
      // bottom-left cell starts at (0, 106).  It belonged to the first
      // player -- lane 0, seat 1 -- so the y inset is 2 and the seat's four
      // pixels carry it to the measured 112.
      x = x0 + G.jailInsetX + G.tokenStep * lane;
      y = y0 + G.jailInsetY + G.tokenStep * seat;
    } else if (row === 10 && col === 0) {          // bottom-left corner
      x = x0 + G.tokenEdge + G.tokenStep * lane; y = y0 + fwd;
    } else if (row === 10) {                       // bottom edge and GO
      x = x0 + fwd; y = y1 - G.tokenSize - G.tokenStep * lane;
    } else if (row === 0 && col === 0) {           // top-left corner
      x = x0 + G.tokenCorner - G.tokenStep * seat;
      y = y0 + G.tokenEdge + G.tokenStep * lane;
    } else if (row === 0 && col === 10) {          // top-right corner
      x = x1 - G.tokenSize - G.tokenStep * lane;
      y = y0 + G.tokenCorner - G.tokenStep * seat;
    } else if (row === 0) {                        // top edge
      x = x0 + rev; y = y0 + G.tokenEdge + G.tokenStep * lane;
    } else if (col === 0) {                        // left edge
      x = x0 + G.tokenEdge + G.tokenStep * lane; y = y0 + fwd;
    } else {                                       // right edge
      x = x1 - G.tokenSize - G.tokenStep * lane; y = y0 + rev;
    }

    // The piece is opaque -- its blank cells are painted black, not left
    // transparent, so it covers the board rather than showing through.
    const shape = G.tokenShapes[player % G.tokenShapes.length];
    for (let dy = 0; dy < shape.length; dy++) {
      const line = shape[dy];
      for (let dx = 0; dx < line.length; dx++) {
        this.point(x + dx, y + dy, line[dx] === "#" ? MAGENTA : BLACK);
      }
    }
  }

  // A line stepped along y, rounding halves upward.  A general Bresenham
  // walk rounds the other way on exact halves and lands a pixel off the
  // captured art, so this follows the original's own stepping.
  line(cells, x0, y0, x1, y1, colour) {
    if (y1 === y0) {
      for (let x = Math.min(x0, x1); x <= Math.max(x0, x1); x++) {
        cells.set(`${x},${y0}`, colour);
      }
      return;
    }
    const dy = y1 - y0;
    for (let step = 0; step <= Math.abs(dy); step++) {
      const y = y0 + (dy > 0 ? step : -step);
      // floor, not truncation: the offsets run negative and truncating
      // toward zero skews the line.
      const x = Math.floor(x0 + (x1 - x0) * step / Math.abs(dy) + 0.5);
      cells.set(`${x},${y}`, colour);
    }
  }

  // The die is a wireframe cube, not a flat square: a face plus three edges
  // dropping back to a rear face.  Built left-handed; the right-hand die is
  // an exact horizontal reflection.
  wireframe(width, height, depth) {
    const G = this.g;
    const cells = new Map();
    const w = width - 1, h = height - 1, d = -depth;
    const far = 0, near = w;

    this.line(cells, 0, 0, w, 0, MAGENTA);
    this.line(cells, 0, h, w, h, MAGENTA);
    for (let y = 0; y <= h; y++) {
      cells.set(`0,${y}`, MAGENTA);
      cells.set(`${w},${y}`, MAGENTA);
    }
    this.line(cells, far, 0, far + d, G.dieTopDrop, MAGENTA);
    this.line(cells, far, h, far + d, h + G.dieBottomDrop, MAGENTA);
    this.line(cells, near, h, near + d, h + G.dieBottomDrop, MAGENTA);
    for (let y = G.dieTopDrop; y <= h + G.dieBottomDrop; y++) {
      cells.set(`${far + d},${y}`, MAGENTA);
    }
    this.line(cells, far + d, h + G.dieBottomDrop,
              near + d, h + G.dieBottomDrop, MAGENTA);
    return cells;
  }

  die(x0, y0, value, mirrored = false, showPips = true) {
    const G = this.g;
    const w = G.dieFace - 1;
    for (const [key, colour] of this.wireframe(G.dieFace, G.dieFace,
                                               G.dieDepth)) {
      const [dx, dy] = key.split(",").map(Number);
      this.point(x0 + (mirrored ? w - dx : dx), y0 + dy, colour);
    }
    // Pips are single pixels, and none are drawn while the die is turning.
    if (showPips) {
      for (const [c, r] of (G.pipLayout[String(value)] || [])) {
        this.point(x0 + G.pipCols[c], y0 + G.pipRows[r], WHITE);
      }
    }
  }

  dice(a, b) {
    this.die(this.g.dieLeftX, this.g.dieY, a, false);
    this.die(this.g.dieRightX, this.g.dieY, b, true);
  }

  // The tumbling dice are not a computed cube: the original picks each die's
  // picture with Random(8) from a table of stored drawings and blits it.
  // These are those drawings, recovered from the running program.
  tumblingDice(left, right) {
    this.tumbleArt(left, 0);
    this.tumbleArt(right === undefined ? left + 3 : right, 1);
  }

  tumbleArt(phase, side) {
    const art = this.d.diceArt[
      ((phase % this.d.diceArt.length) + this.d.diceArt.length)
      % this.d.diceArt.length];
    const x0 = this.d.diceOrigin[0] + side * this.d.diceSpacing;
    const y0 = this.d.diceOrigin[1];
    for (let dy = 0; dy < art.length; dy++) {
      const row = art[dy];
      for (let dx = 0; dx < row.length; dx++) {
        if (row[dx] !== ".") this.point(x0 + dx, y0 + dy, +row[dx]);
      }
    }
  }

  cashOrigin(players) {
    return Math.floor((COLS - this.g.cashStep * players) / 2) + 3;
  }

  // players: [{name, cash, pos}]
  draw(title, message, players, dice, hide = [], tumble = null, label = "") {
    this.clear();
    this.blitBoard();

    // A card square puts its name where the dice sit, and the dice are not
    // drawn at all while it shows.
    if (label) {
      this.text(centreDown(label, this.g), this.g.labelRow, label, MAGENTA);
    } else if (tumble !== null && tumble !== undefined) {
      if (Array.isArray(tumble)) this.tumblingDice(tumble[0], tumble[1]);
      else this.tumblingDice(tumble);
    } else if (dice) {
      this.dice(dice[0], dice[1]);
    }

    players.forEach((p, i) => {
      if (!hide.includes(i)) this.token(p.pos, i, p.inJail);
    });

    if (title) this.text(centreUp(title, this.g), this.g.titleRow, title, WHITE);
    message.forEach((line, n) => {
      if (!line) return;
      // A placed run -- [col, row, text, colour] -- goes exactly where it is
      // put.  The jail prompt needs it: unlike a landing message it is
      // left-aligned at column 19, and its hot keys are a different colour
      // from the words around them.
      if (Array.isArray(line))
        this.text(line[0], line[1], line[2],
                  line[3] === undefined ? CYAN : line[3]);
      else
        this.text(centreUp(line, this.g), this.g.messageRow + n, line, CYAN);
    });

    const origin = this.cashOrigin(players.length);
    players.forEach((p, i) => {
      const base = origin + i * this.g.cashStep;
      this.text(base + Math.floor((this.g.cashField - p.name.length) / 2),
                this.g.cashNameRow, p.name, WHITE);
      // The figure is right-aligned, always ending at the same column; only
      // the dollar sign is fixed.  Four-digit amounts hide this.
      this.text(base, this.g.cashMoneyRow, "$", WHITE);
      const fig = String(p.cash);
      this.text(base + 2 + (this.g.cashAmountWidth - fig.length),
                this.g.cashMoneyRow, fig, WHITE);
    });
  }

  // 320x200 doubled to 640x400.
  render(img) {
    const p = img.data;
    const W = WIDTH * 2;
    for (let y = 0; y < HEIGHT; y++) {
      for (let x = 0; x < WIDTH; x++) {
        const c = this.palette[this.px[y * WIDTH + x]];
        for (let dy = 0; dy < 2; dy++) {
          for (let dx = 0; dx < 2; dx++) {
            const o = ((y * 2 + dy) * W + (x * 2 + dx)) * 4;
            p[o] = c[0]; p[o + 1] = c[1]; p[o + 2] = c[2]; p[o + 3] = 255;
          }
        }
      }
    }
  }
}
