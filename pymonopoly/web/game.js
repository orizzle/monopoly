// The turn loop, the rules, and the screens.
//
// This mirrors the Python port module for module: the same square and card
// tables, the same generator, the same geometry.  Where the original's own
// behaviour is unusual it is reproduced rather than corrected -- the mortgage
// interest that accrues every turn, the bank overdraft that must be cleared
// before you may move again, and the tumble that spends eight Random draws a
// frame before the dice are taken.

import { DATA } from "./data.js";
import { TurboRandom } from "./rng.js";
import { TextScreen, COLS, ROWS, WIDTH as TW, HEIGHT as TH } from "./cga.js";
import { BoardScreen, MAGENTA, CYAN, WHITE as GWHITE } from "./gfx.js";
import { Speaker } from "./sound.js";

const SQ = DATA.squares;
const GROUPS = DATA.groups;
// The eight colour-group indices, in the order the picker lists them.
const GROUP_IDS = DATA.text.groupKeys.map(
  ([, name]) => GROUPS.findIndex((g) => g && g.name === name));
const R = DATA.rules;
const PROPERTY = 0, RAILROAD = 1, UTILITY = 2;
const BANK = -1;
const JAIL = 10, GO_TO_JAIL = 30;
const CORNERS = [0, 10, 20, 30];

const T = DATA.text;
const C = T.colours;
// The measured geometry.  Several methods bind their own `G = DATA.geom`
// locally; this is the same table for the ones that do not.
const G = DATA.geom;

// The in-jail question and its options, as placed board runs.  Geometry
// measured off a board capture; see graphics.jail_prompt, which this mirrors.
function jailPrompt(cards) {
  const rows = [[G.jailPromptCol, G.jailPromptRow, "You are in JAIL.", CYAN]];
  const options = [["Want to ", "P", "ay $50?"], ["     or ", "R", "oll?"]];
  if (cards) options.push([" or use ", "C", "ard?"]);
  options.forEach(([lead, key, rest], n) => {
    const row = G.jailOptionRow + n;
    rows.push([G.jailPromptCol, row, lead, CYAN]);
    rows.push([G.jailHotkeyCol, row, key, MAGENTA]);
    rows.push([G.jailHotkeyCol + 1, row, rest, CYAN]);
  });
  return rows;
}

// An attribute is foreground | background << 4.  With blink disabled the
// background nibble is four bits wide, which is what lets the original use
// brown and blue fills rather than only the eight dark colours.
const at = (fg, bg) => (fg & 0x0f) | ((bg & 0x0f) << 4);

// ---------------------------------------------------------------------------
// input
// ---------------------------------------------------------------------------

class Keyboard {
  // Desktop reports every key through keydown.  Android soft keyboards often
  // do not: Gboard fires keydown with key "Unidentified" (keyCode 229) and
  // delivers the real character through beforeinput instead, so both paths
  // are handled and de-duplicated.  `input` is the hidden field that exists
  // only to give the on-screen keyboard something to be focused on.
  constructor(input) {
    this.waiting = null;
    this.buffer = [];
    this.fromKeydown = false;

    window.addEventListener("keydown", (e) => {
      if (e.key === "F5" || (e.ctrlKey && e.key === "r")) return;
      if (e.key === "Unidentified" || e.keyCode === 229) {
        this.fromKeydown = false;      // let beforeinput deliver it
        return;
      }
      e.preventDefault();
      this.fromKeydown = true;
      // Do not fold case here: typed names keep their capitals.  Hot keys
      // are matched case-insensitively in key() instead.
      this.push(e.key);
    });

    if (input) {
      input.addEventListener("beforeinput", (e) => {
        // The field must never actually accumulate text; it is only a target
        // for the soft keyboard.
        e.preventDefault();
        input.value = "";
        if (this.fromKeydown) { this.fromKeydown = false; return; }
        const t = e.inputType;
        if (t === "deleteContentBackward") this.push("Backspace");
        else if (t === "insertLineBreak" || t === "insertParagraph") {
          this.push("Enter");
        } else if (e.data) {
          for (const ch of e.data) this.push(ch);
        }
      });
      input.addEventListener("input", () => { input.value = ""; });
    }
  }
  push(k) {
    if (this.waiting) { const w = this.waiting; this.waiting = null; w(k); }
    else this.buffer.push(k);
  }
  key() {
    if (this.buffer.length) return Promise.resolve(this.buffer.shift());
    return new Promise((res) => { this.waiting = res; });
  }
}

// setTimeout treats undefined as zero, so a mistyped constant does not fail:
// it just makes the animation run flat out, which is how the dice came to
// tumble at the browser's timer floor instead of the original's 41.5 ms.
const sleep = (ms) => {
  if (typeof ms !== "number" || !(ms >= 0)) {
    throw new Error(`sleep(${ms}): timing constant missing`);
  }
  return new Promise((r) => setTimeout(r, ms));
};

// Card text is written for a 34-column panel, so it is folded rather than
// clipped -- the original wraps on words.
function wrap(text, width) {
  const out = [];
  let line = "";
  for (const word of String(text).split(/\s+/)) {
    if (!word) continue;
    if (line && (line + " " + word).length > width) { out.push(line); line = word; }
    else line = line ? line + " " + word : word;
  }
  if (line) out.push(line);
  return out;
}

// First square in `targets` at or ahead of pos, wrapping at GO.
function nearest(pos, targets) {
  for (let step = 1; step <= 40; step++) {
    const c = (pos + step) % 40;
    if (targets.includes(c)) return c;
  }
  return pos;
}

// ---------------------------------------------------------------------------
// state
// ---------------------------------------------------------------------------

function newState(names, seed) {
  const rng = new TurboRandom(seed);
  const st = {
    rng,
    players: names.map((n) => ({
      name: n, cash: R.startingCash, pos: R.go, inJail: false,
      jailTurns: 0, jailCards: 0, bankrupt: false, loan: 0,
    })),
    props: SQ.map(() => ({ owner: BANK, mortgaged: false, houses: 0 })),
    current: 0,
    dice: [1, 1],
    doubles: 0,
    // display only: titles a repeat roll "<name> again"
    again: false,
    sound: true,
    chanceOrder: [], chestOrder: [], chanceNext: 0, chestNext: 0,
  };
  // The original's descending Fisher-Yates, fifteen draws a deck.
  const shuffle = (n) => {
    const deck = Array.from({ length: n }, (_, i) => i);
    for (let i = n; i > 1; i--) {
      const j = rng.random(i) + 1;
      [deck[i - 1], deck[j - 1]] = [deck[j - 1], deck[i - 1]];
    }
    return deck;
  };
  st.chanceOrder = shuffle(DATA.chance.length);
  st.chestOrder = shuffle(DATA.chest.length);
  st.dice = [rng.die(), rng.die()];
  return st;
}

const active = (st) => st.players.filter((p) => !p.bankrupt);
const holdings = (st, i) =>
  SQ.map((_, p) => p).filter((p) => st.props[p].owner === i);

function ownsGroup(st, who, group) {
  const g = GROUPS[group];
  if (!g) return false;
  return g.members.every((p) => st.props[p].owner === who);
}
const groupUnimproved = (st, group) =>
  ((GROUPS[group] && GROUPS[group].members) || []).every((p) => st.props[p].houses === 0);

const countKind = (st, who, kind) =>
  SQ.filter((s, p) => s.kind === kind && st.props[p].owner === who).length;

const railroadRent = (n) => (n ? 25 * 2 ** (n - 1) : 0);
const utilityRent = (n, total) => total * (n >= 2 ? 10 : 4);

function rentDue(st, pos, total) {
  const sq = SQ[pos], ps = st.props[pos];
  if (!sq.ownable || ps.owner === BANK || ps.mortgaged) return 0;
  if (sq.kind === RAILROAD) return railroadRent(countKind(st, ps.owner, RAILROAD));
  if (sq.kind === UTILITY) return utilityRent(countKind(st, ps.owner, UTILITY), total);
  if (ps.houses) return sq.rent[ps.houses];
  const base = sq.rent[0];
  return (ownsGroup(st, ps.owner, sq.group) && groupUnimproved(st, sq.group))
    ? base * 2 : base;
}

const mortgageValue = (pos) => Math.floor(SQ[pos].cost / 2);
const mortgageInterest = (pos) => Math.floor(mortgageValue(pos) / 10);
const unmortgageCost = (pos) => mortgageValue(pos) + mortgageInterest(pos);

function netWorth(st, i) {
  let w = st.players[i].cash;
  for (const p of holdings(st, i)) {
    const ps = st.props[p];
    w += ps.mortgaged ? 0 : SQ[p].cost;
    w += ps.houses * ((GROUPS[SQ[p].group] && GROUPS[SQ[p].group].houseCost) || 0);
  }
  return w;
}

// ---------------------------------------------------------------------------
// the game
// ---------------------------------------------------------------------------

export class Game {
  constructor(canvas, statusEl) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    // Text mode is 720x400 and the board is 640x400, so the surface changes
    // size with the video mode -- which is exactly what the real display does.
    this.textImg = this.ctx.createImageData(TW, TH);
    this.boardImg = this.ctx.createImageData(640, 400);
    this.text = new TextScreen(DATA);
    // Set while the business menu is open: everything reached from it is
    // drawn in that menu's panel rather than the ordinary turn panel.
    this.inBusiness = false;
    this.board = new BoardScreen(DATA);
    this.kb = new Keyboard(document.getElementById("kbd"));
    this.spk = new Speaker();
    this.statusEl = statusEl;
    this.st = null;
  }

  // -- painting ----------------------------------------------------------

  surface(w, h) {
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w; this.canvas.height = h;
    }
  }
  paintText() {
    this.onBoard = false;
    this.surface(TW, TH);
    this.text.render(this.textImg);
    this.ctx.putImageData(this.textImg, 0, 0);
  }
  paintBoard() {
    this.onBoard = true;
    this.surface(640, 400);
    this.board.render(this.boardImg);
    this.ctx.putImageData(this.boardImg, 0, 0);
  }

  status(s) { if (this.statusEl) this.statusEl.textContent = s; }

  async key(allowed = null) {
    for (;;) {
      const k = await this.kb.key();
      this.spk.resume();
      if (k === "F1" && this.st) {
        this.st.sound = this.spk.toggle();
        continue;
      }
      if (!allowed) return k;
      const low = k.length === 1 ? k.toLowerCase() : k;
      if (allowed.includes(low)) return low;
    }
  }

  cue(name) { if (!this.st || this.st.sound) this.spk.cue(name); }

  // -- board screen ------------------------------------------------------

  players() {
    return this.st.players.map((p) => ({
      name: p.name, cash: p.cash, pos: p.pos, inJail: p.inJail,
    }));
  }

  showBoard(message = [], opts = {}) {
    const st = this.st;
    const title = opts.title !== undefined ? opts.title : this.boardTitle();
    this.board.draw(title, message, this.players(),
                    opts.tumble !== undefined ? null : st.dice,
                    opts.hide || [], opts.tumble, opts.label || "");
    this.paintBoard();
  }

  // -- text panels -------------------------------------------------------
  //
  // The message panel is a light-grey frame around a blue interior, with the
  // hot key of each option picked out in light cyan.  The title deed sits in
  // its own brown panel on the right with a light-grey card inside it.  All
  // of this is measured geometry from screens.py, not styling chosen here.

  fill(x0, y0, x1, y1, attr) {
    this.text.box(x0, y0, x1, y1, attr);
  }

  framed(bounds, frame, interior) {
    const [l, t, r, b] = bounds;
    this.fill(l, t, r, b, at(frame, frame));
    this.fill(l + 1, t + 1, r - 1, b - 1, at(interior, interior));
  }

  // Which panel a prompt lands in.  Everything reached from the business
  // menu keeps that menu's green panel and its "<name> on <square>." header,
  // which sits a row higher than the turn panel's title -- measured from the
  // real program, where even the error answers stay in the green frame.
  activePanel() {
    return this.inBusiness ? T.businessPanel : T.messagePanel;
  }

  businessPanel(lines, options = null, deed = null) {
    const t = this.text;
    const st = this.st, ply = st.players[st.current], pos = ply.pos;
    t.clear(at(C.LIGHTGRAY, C.BLACK));
    const [l, top, r, bot] = T.businessPanel;
    this.framed(T.businessPanel, C.BROWN, C.GREEN);
    const ink = at(C.WHITE, C.GREEN);
    const keyInk = at(C.YELLOW, C.GREEN);
    const title = `${ply.name} on ${SQ[pos].name}.`;
    t.write(l + 1 + Math.floor(((r - l - 1) - title.length) / 2), top + 1,
            title, ink);
    let row = top + 3;
    for (const line of [...lines, ...(options ? ["", ...options] : [])]) {
      if (row > bot - 1) break;
      this.hotkey(l + 3, row, line, ink, keyInk);
      row += 1;
    }
    const card = deed !== null && deed !== undefined ? deed
               : (SQ[pos].ownable ? pos : null);
    if (card !== null) this.deedCard(card);
    this.cashLine();
    this.paintText();
  }

  panel(title, lines, options = null, deed = null) {
    if (this.inBusiness) return this.businessPanel(lines, options, deed);
    const t = this.text;
    t.clear(at(C.LIGHTGRAY, C.BLACK));
    const [l, top, r, bot] = T.messagePanel;
    this.framed(T.messagePanel, C.LIGHTGRAY, C.BLUE);

    const ink = at(C.WHITE, C.BLUE);
    if (title) {
      t.write(l + 1 + Math.floor(((r - l - 1) - title.length) / 2), top + 1,
              title, ink);
    }
    let row = top + 3;
    for (const line of lines) {
      if (row > bot - 1) break;
      t.write(l + 3, row, line.slice(0, r - l - 3), ink);
      row += 1;
    }
    if (options) {
      row += 1;
      for (const opt of options) {
        if (row > bot - 1) break;
        this.hotkey(l + 3, row, opt, ink, at(C.LIGHTCYAN, C.BLUE));
        row += 1;
      }
    }
    if (deed !== null && deed !== undefined) this.deedCard(deed);
    this.cashLine();
    this.paintText();
  }

  // The per-player cash boxes, and under each one a miniature board showing
  // the short name of every property that player holds.  The marker's row
  // comes from the square's Side field and its column from ScreenPos, offset
  // by the player's slot -- those two fields in the Place[] record exist for
  // exactly this.  A mortgaged holding is shown in lower case; a developed
  // one carries its house count.
  cashLine() {
    if (!this.st) return;
    const t = this.text;
    this.st.players.forEach((ply, i) => {
      if (i >= T.cashBoxX.length) return;
      const x = T.cashBoxX[i];
      const fg = ply.bankrupt ? C.DARKGRAY : C.WHITE;
      const ink = at(fg, C.LIGHTGRAY);
      this.fill(x, T.cashRow, x + T.cashBoxW - 1, T.cashRow + 1,
                at(C.LIGHTGRAY, C.LIGHTGRAY));
      const mid = (str) =>
        x + Math.floor(((T.cashBoxW) - str.length + 1) / 2);
      const name = ply.name.slice(0, T.cashBoxW);
      t.write(mid(name), T.cashRow, name, ink);
      const cash = ply.bankrupt ? "BANKRUPT" : `$ ${ply.cash}`;
      t.write(mid(cash), T.cashRow + 1, cash, ink);

      for (const pos of holdings(this.st, i)) {
        const sq = SQ[pos], ps = this.st.props[pos];
        const g = GROUPS[sq.group];
        // #7: the name keeps the capitalisation it has in the table --
        // lower-casing it on mortgage was mine.  #8: a mortgaged holding is
        // distinguished by colour instead, drawn in light red.
        let mark = sq.short;
        if (!ps.mortgaged && ps.houses) mark = `${mark}${ps.houses}`;
        const col = sq.screenPos + T.holdingsBaseCol + T.holdingsPlayerStep * i;
        const row = T.holdingsBaseRow + sq.side;
        // Mortgaged overrides the group's colours with LightGray on Black
        // -- TextColor(7)/TextBackground(0) at CHN 0x5E41.
        const ink = ps.mortgaged
          ? at(C.LIGHTGRAY, C.BLACK)
          : (g ? at(g.ttext, g.tback) : at(C.WHITE, C.BLACK));
        if (row >= 1 && row <= ROWS && col >= 1) t.write(col, row, mark, ink);
      }
    });
  }

  // '~' marks the hot key, which is drawn in its own attribute.
  hotkey(col, row, spec, ink, keyInk) {
    let x = col;
    for (let i = 0; i < spec.length; i++) {
      if (spec[i] === "~") continue;
      const isKey = i > 0 && spec[i - 1] === "~";
      this.text.put(x, row, spec.charCodeAt(i), isKey ? keyInk : ink);
      x += 1;
    }
  }

  // The title deed card, with the column positions the original writes at.
  // None of it is centred: the program writes fixed-width label strings and
  // then the figure, which is why Cost sits a column left of the rent ladder.
  deedCard(pos) {
    const t = this.text, sq = SQ[pos];
    if (!sq.ownable) return;
    const g = sq.group ? GROUPS[sq.group] : null;
    const [tfg, tbg, fg, bg] = g
      ? [g.ttext, g.tback, g.ttext2, g.tback2]
      : [C.YELLOW, C.BROWN, C.WHITE, C.LIGHTGRAY];
    const ink = at(fg, bg);

    const [pl, pt, pr, pb] = T.deedPanel;
    this.fill(pl, pt, pr, pb, at(tbg, tbg));
    const titleCol = pl + Math.floor(((pr - pl + 1) - sq.name.length + 1) / 2);
    t.write(titleCol, 3, sq.name, at(tfg, tbg));

    const [cl, ct, cr, cb] = T.deedCard;
    this.fill(cl, ct, cr, cb, at(bg, bg));

    const money = (y, dollarX, rightX, amount) => {
      const text = String(amount);
      t.write(dollarX, y, "$", ink);
      t.write(rightX - text.length + 1, y, text, ink);
    };

    t.write(58, 6, "Cost", ink);
    money(6, 67, 71, sq.cost);
    let mortgageRow;

    if (sq.kind === PROPERTY) {
      t.write(57, 8, "Rent", ink);
      money(8, 68, 72, sq.rent[0]);
      for (let n = 1; n <= 4; n++) {
        t.write(58, 8 + n, String(n), ink);
        t.write(60, 8 + n, n === 1 ? "house" : "houses", ink);
        money(8 + n, 68, 72, sq.rent[n]);
      }
      t.write(60, 13, "hotel", ink);
      money(13, 68, 72, sq.rent[5]);
      t.write(51, 15, `Cost of each house is $${g ? g.houseCost : 0}.`, ink);
      mortgageRow = 16;
    } else if (sq.kind === RAILROAD) {
      t.write(57, 8, "Rent", ink);
      money(8, 69, 73, railroadRent(1));
      for (const n of [2, 3, 4]) {
        t.write(59, 7 + n, "if", ink);
        t.write(62, 7 + n, String(n), ink);
        t.write(64, 7 + n, "RRs", ink);
        money(7 + n, 69, 73, railroadRent(n));
      }
      mortgageRow = 13;
    } else {
      for (const [row, line] of [[8, "Rent if one utility owned is"],
                                 [9, "  four times amount on dice."],
                                 [11, "If both utilities are owned"],
                                 [12, "  then ten times the dice."]]) {
        t.write(50, row, line, ink);
      }
      mortgageRow = 14;
    }
    t.write(54, mortgageRow, `Mortgage value is $${mortgageValue(pos)}.`, ink);
    // What is standing on the property.  The original writes character 219 --
    // a full block -- at the card's (3,2), which is the title band, and the
    // count is the development itself: one block per house, six for a hotel.
    // The colour is picked for contrast against the card, houses white on
    // backgrounds 2 and 3 and green otherwise, a hotel white on 4 and 6 and
    // red otherwise (CHN file 0x3BF0 and 0x3C95).  The "1 HOUSE" / "HOTEL"
    // caption this port used to print appears nowhere in the program.
    if (this.st) {
      const h = this.st.props[pos].houses;
      if (h) {
        const hotel = h >= R.housesPerHotel;
        const n = hotel ? 6 : h;
        const fg = hotel ? (bg === 4 || bg === 6 ? C.WHITE : C.RED)
                         : (bg === 2 || bg === 3 ? C.WHITE : C.GREEN);
        const [dl, dt] = T.deedPanel;
        t.write(dl + 2, dt + 1, "\u00db".repeat(n), at(fg, bg));
      }
    }
    if (this.st && this.st.props[pos].mortgaged) {
      const w = "MORTGAGED";
      t.write(51 + Math.floor((78 - 51 + 1 - w.length) / 2), mortgageRow - 2,
              w, at(C.LIGHTRED, bg));
    }
  }

  // The dark-red box that drops over the message panel when a player cannot
  // meet a payment: the player's name between dashes and "YOU DON'T HAVE
  // ENOUGH CASH.", measured at columns 5..36, rows 9..23.  It hangs below the
  // blue panel rather than sitting inside it.
  noCashBox(name) {
    const t = this.text;
    const [l, top, r, bottom] = T.noCashPanel;
    this.fill(l, top, r, bottom, at(C.WHITE, C.RED));
    const tag = `--${name}--`;
    t.write(l + Math.floor((r - l + 1 - tag.length) / 2), top + 1, tag,
            at(C.WHITE, C.RED));
    const line = "YOU DON'T HAVE ENOUGH CASH.";
    const col = l + Math.floor((r - l + 1 - line.length) / 2);
    t.write(col, top + 2, line, at(C.WHITE, C.RED));
    this.text.cursor = [col, top + 3];
    this.paintText();
  }

  // Show a panel and carry straight on, without waiting for a key.  Rent is
  // charged this way: the captures show the amount owed and then the money
  // moving, with no "<Press Any Key>" beat -- the next thing on screen is
  // the Business/Go on prompt.
  notice(title, lines, deed = null) {
    this.panel(title, lines, null, deed);
  }

  async announce(title, lines, deed = null) {
    this.panel(title, [...lines, "", "<Press Any Key>"], null, deed);
    await this.key();
  }

  async ask(title, lines, options, deed = null) {
    this.panel(title, lines, options, deed);
    const keys = options.map((o) => o[o.indexOf("~") + 1].toLowerCase());
    return await this.key(keys);
  }

  // A prompt drawn on the board itself rather than in the message panel.
  async askOnBoard(runs, keys) {
    this.showBoard(runs);
    return await this.key(keys);
  }

  invalid(lines) {
    this.cue("error");
    return this.announce(this.st.players[this.st.current].name, lines);
  }

  // -- setup -------------------------------------------------------------

  // The opening screen is not black: two credit lines in dark grey, a brown
  // logo panel, and a brown entry panel holding the numbered name slots.  An
  // earlier version of this port drew plain text on a black field, which is
  // the one thing the original never does here.
  titleScreen(names, showPrompt = true) {
    const t = this.text;
    t.clear(at(C.LIGHTGRAY, C.BLACK));
    t.write(10, 1, T.trademark, at(C.DARKGRAY, C.BLACK));
    t.write(14, 2, T.adaptation, at(C.DARKGRAY, C.BLACK));

    this.framed(T.titlePanel, C.LIGHTGRAY, C.BROWN);
    t.write(36, 8, "Monopoly", at(C.WHITE, C.BROWN));

    t.write(27, 13, "Welcome to the Monopoly Game", at(C.GREEN, C.BLACK));

    this.framed(T.entryPanel, C.LIGHTGRAY, C.BROWN);
    t.write(31, 16, "Who are the players?", at(C.YELLOW, C.BROWN));

    const rows = names.length + (showPrompt ? 1 : 0);
    for (let i = 0; i < rows; i++) {
      const row = T.firstSlotRow + i;
      t.write(T.slotMarkerCol, row, `${i + 1}>`, at(C.LIGHTGRAY, C.BROWN));
      if (i < names.length) {
        t.write(T.slotNameCol, row, names[i], at(C.WHITE, C.BROWN));
      } else {
        t.write(T.slotNameCol, row, ".".repeat(T.nameFieldWidth),
                at(C.LIGHTGRAY, C.BROWN));
      }
    }
    t.write(3, 25, T.keysLine, at(C.DARKGRAY, C.BLACK));
  }

  async setup() {
    const names = [];
    for (;;) {
      this.titleScreen(names);
      this.paintText();
      const row = T.firstSlotRow + names.length;
      const name = await this.readLine(T.slotNameCol, row, T.nameFieldWidth,
                                       at(C.WHITE, C.BROWN));
      if (name === "") {
        if (names.length >= R.minPlayers) break;
        await this.announce("", ["Sorry, there have to be at least",
                                 "two players.  Do it again please."]);
        continue;
      }
      names.push(name);
      if (names.length >= R.maxPlayers) break;
    }
    this.st = newState(names, 0);
    return true;
  }

  // A field with the flashing cursor the original shows while it waits.
  async readLine(col, row, width, attr, dots = true) {
    let s = "";
    let blink = true;
    // The name slot shows dots until it is typed into; panel prompts do not.
    if (dots) this.text.write(col, row, ".".repeat(width), attr);
    this.paintText();
    const timer = setInterval(() => {
      blink = !blink;
      this.text.cursor = blink ? [col + s.length, row] : null;
      this.paintText();
    }, 266);
    try {
      for (;;) {
        const k = await this.key();
        if (k === "Enter") return s.trim();
        if (k === "Backspace") {
          if (s.length) {
            s = s.slice(0, -1);
            this.text.put(col + s.length, row, dots ? 0x2e : 0x20, attr);
          }
        } else if (k.length === 1 && s.length < width) {
          s += k;
          this.text.put(col + s.length - 1, row, k.charCodeAt(0), attr);
        }
        this.paintText();
      }
    } finally {
      clearInterval(timer);
      this.text.cursor = null;
    }
  }

  // -- money -------------------------------------------------------------

  // Rent is not lent against: a player who cannot pay has to mortgage or
  // sell until they can, and is out if they cannot.  The original keeps two
  // deduct helpers for exactly this -- the one at CHN load 0x5EDC simply
  // takes the money, while 0x6064 falls back on the routine at 0x5749 that
  // offers to raise it or advance a loan, and every one of 0x6064's seven
  // callers is a transaction the player chose to enter into: buying from
  // another player, selling, mortgaging, unmortgaging, building, and the
  // purchase and auction pair.  Rent goes through the first, so `allowLoan`
  // is off unless a caller says otherwise.
  async pay(who, amount, creditor = null, allowLoan = false) {
    const st = this.st, ply = st.players[who];
    if (amount <= 0) return true;
    while (ply.cash < amount) {
      // The routine runs straight through: the red box with its five beeps,
      // then "YOU MUST RAISE SOME MONEY.", then Delay(1200), and only then
      // does it decide.  Traced on a player who went bust -- beeps at
      // 89.28..90.85 s, the falling tone at 92.40 s -- so the beeps sound in
      // both cases, and the fall is what the branch adds.
      this.cue("no_cash");
      this.noCashBox(ply.name);
      await sleep(DATA.cues.no_cash.reduce((n, t) => n + t[1], 0));
      this.notice(`${ply.name}'s turn`, ["YOU MUST RAISE SOME MONEY."]);
      await sleep(DATA.geom.raisePauseMs);
      if (netWorth(st, who) < amount) {
        this.notice(`${ply.name}'s turn`, ["YOU HAVE NO ASSETS."]);
        await this.bankrupt(who, creditor);
        return false;
      }
      // Mortgaging and selling is how assets become cash.
      const before = ply.cash;
      await this.business(who, true);
      if (ply.cash >= amount) break;
      if (!allowLoan) {
        if (ply.cash <= before) {
          this.notice(`${ply.name}'s turn`, ["YOU HAVE NO ASSETS."]);
          await this.bankrupt(who, creditor);
          return false;
        }
        continue;
      }
      const short = amount - ply.cash;
      await this.announce(ply.name, ["I WILL LOAN UNTIL YOUR TURN."]);
      ply.cash += short;
      ply.loan += short;
    }
    this.cue("pay");        // cash leaving a player
    await this.countCash(who, -amount);
    if (creditor !== null && creditor !== undefined && creditor >= 0) {
      await this.collect(creditor, amount);
    }
    return true;
  }

  // The original counts a total up or down $5 at a time, about 19 ms a
  // step, ticking once per step -- measured from the cash variable and the
  // speaker together.  It never snaps straight to the new figure.
  async countCash(who, delta) {
    const st = this.st, ply = st.players[who];
    const target = ply.cash + delta;
    const step = DATA.geom.cashStepAmount;
    const dir = delta < 0 ? -step : step;
    while ((dir < 0 && ply.cash > target) || (dir > 0 && ply.cash < target)) {
      const next = ply.cash + dir;
      ply.cash = (dir < 0) ? Math.max(next, target) : Math.min(next, target);
      // Money coming in ticks at 1500 Hz, money going out at 900 Hz.
      this.cue(delta > 0 ? "money_up" : "money");
      // The cash boxes have to be rewritten, not just repainted: paintText
      // pushes the existing text buffer to the canvas, so without this the
      // total sat unchanged through the whole count and only caught up on
      // the next full panel draw -- the sound moved, the number did not.
      if (this.onBoard) {
        this.showBoard([]);
      } else {
        this.cashLine();
        this.paintText();
      }
      await sleep(DATA.geom.cashStepMs);
    }
    ply.cash = target;
  }

  async collect(who, amount) {
    if (amount <= 0) return;
    this.cue("receive");
    await this.countCash(who, amount);
  }

  async bankrupt(who, creditor) {
    const st = this.st, ply = st.players[who];
    ply.bankrupt = true;
    this.cue("bankrupt");
    const toPlayer = creditor !== null && creditor !== undefined
      && creditor >= 0 && !st.players[creditor].bankrupt;
    for (const p of holdings(st, who)) {
      if (toPlayer) st.props[p].owner = creditor;
      else st.props[p] = { owner: BANK, mortgaged: false, houses: 0 };
    }
    let where = "The Bank";
    if (toPlayer) {
      st.players[creditor].cash += Math.max(ply.cash, 0);
      where = st.players[creditor].name;
    }
    ply.cash = 0;
    await this.announce(ply.name, ["YOU ARE OUT OF THE GAME!",
                                   `The cash left goes to ${where}.`]);
  }

  // -- movement ----------------------------------------------------------

  // The tumble spends the generator before the dice are drawn: each frame
  // picks art for both dice with Random(8) and beeps twice, and each beep is
  // `for i := 1 to 3 do Random(i*2500)`.  Eight draws a frame, measured under
  // an instrumented emulator.  Skipping them would read the same sequence at
  // the wrong offsets and roll different numbers from the same seed.
  // Returns the frequencies drawn, because they are not throwaway numbers:
  // the original passes each Random(i*2500) straight to Sound(), so the
  // rattle you hear during a roll IS this sequence.  Discarding them and
  // playing only the 2000/3000/2500 cycle gives a clean beep, not a rattle.
  tumbleDraws(frames) {
    const tones = [];
    for (let f = 0; f < frames; f++) {
      for (let d = 0; d < 2; d++) tones.push(...this.tumbleCube());
    }
    return tones;
  }

  // One cube's share of a frame: the drawing it turns to, then the three
  // tones it clicks.  Taking them a cube at a time keeps the draw order
  // identical to taking them a frame at a time, and lets the roll redraw and
  // sound each cube on its own 41.5 ms beat -- which is what the recording
  // shows: the dice box changes about every 41.5 ms, not every 83.
  tumbleCube() {
    const pose = this.st.rng.random(8);
    const tones = [];
    for (let i = 1; i <= 3; i++) tones.push(this.st.rng.random(i * 2500));
    this.lastPose = pose;
    return tones;
  }

  async rollDice() {
    const st = this.st;
    const G = DATA.geom;

    // The dice turn on their own and keep turning until a key stops them.
    // That is the original's behaviour, and it is also why its rolls look
    // unreproducible: every tumble frame spends eight draws, so a slower
    // hand takes the dice from further along the sequence.
    let stopped = false;
    const waiter = this.key().then(() => { stopped = true; });
    this.spk.stopRoll();

    // One cube per beat, alternating, which is how the original redraws and
    // sounds them: the draws it takes are the tones it plays.  The beat runs
    // off a deadline rather than a plain sleep: setTimeout overshoots by a
    // few milliseconds every time, which stretched a 41.5 ms beat to nearly
    // 48 and made the dice turn slower than the machine did.
    let half = 0;
    const pose = [0, 0];
    let due = performance.now();
    while (!stopped) {
      const d = half % 2;
      const noise = this.tumbleCube();
      pose[d] = this.lastPose;
      // Nothing but the dice moves during a roll: the piece is left alone
      // until the chime that follows it.  Measured from a 59.92 fps capture
      // -- through the whole tumble the only changing pixels on the board
      // are the two cubes.
      this.showBoard([], { tumble: [pose[0], pose[1]] });
      if (st.sound) this.spk.rattle(noise);
      half += 1;
      due += G.rattlePeriodMs;
      await sleep(Math.max(0, due - performance.now()));
      if (half > 8000) break;           // never spin forever
    }
    // The pair has to leave the loop having taken a whole frame's draws, or
    // the dice would come off a half-frame boundary in the sequence.
    if (half % 2) this.tumbleCube();
    await waiter;
    this.spk.stopRoll();

    const a = st.rng.die(), b = st.rng.die();
    st.dice = [a, b];
    this.showBoard([]);
    return [a, b];
  }

  // Measured: ten cycles of three blits with a beep on each -- 2002, 3005
  // and 2501 Hz, about 37 ms apiece, 1223 ms in all -- and only then does
  // the piece start walking to the square the card names.
  // Blink the piece where it stands, under the post-roll chime.  Measured:
  // about thirty toggles at ~37 ms, and only here -- never while the dice
  // are still turning.
  async flashPiece(who) {
    const G = DATA.geom;
    for (let i = 0; i < G.flashToggles; i++) {
      this.showBoard([], { hide: i % 2 ? [who] : [] });
      await sleep(G.flashToggleMs);
    }
    this.showBoard([]);
  }

  async advanceFlash(who) {
    const G = DATA.geom;
    this.cue("landing");
    for (let i = 0; i < G.advanceBlits; i++) {
      this.showBoard([], { hide: i % 2 ? [who] : [] });
      await sleep(G.advanceBlitMs);
    }
    this.showBoard([]);
  }

  async animateMove(who, start, steps, payGo = true) {
    const st = this.st, G = DATA.geom;
    // A 900->800 chirp on every square, 374 ms apart, and a 707 ms rising
    // chime on a corner -- both measured off the speaker, not inferred.
    for (let i = 1; i <= steps; i++) {
      const pos = (start + i) % 40;
      st.players[who].pos = pos;
      this.showBoard([]);
      const corner = CORNERS.includes(pos);
      this.cue(corner ? "corner" : "step");
      if (corner) {
        // The piece sits out the whole chime before taking its ordinary
        // step delay, which is why a corner reads as a pause.
        await sleep(G.cornerMs);
        // Passing GO is paid here, on the square, once the chime has
        // finished -- not credited up front when the roll ends.
        if (payGo && pos === 0 && start !== 0) await this.countCash(who, 200);
      }
      await sleep(G.stepMs);
    }
    await this.landingFlash(who, (start + steps) % 40);
  }

  // Where the piece stops it flashes, and the board names the square it has
  // reached -- "You have landed on <name>" in the message area, under the
  // 2002/3005/2501 chime, for about 2.2 s before anything else happens.
  // Captured from the real program: the port used to blink silently and, for
  // a property, never named the square at all -- it cut straight to the text
  // screen.
  async landingFlash(who, pos) {
    const G = DATA.geom;
    const line = ["You have landed on", SQ[pos].name];
    this.cue("landing");
    for (let i = 0; i < G.advanceBlits; i++) {
      this.showBoard(line, { hide: i % 2 ? [who] : [] });
      await sleep(G.advanceBlitMs);
    }
    this.showBoard(line);
  }

  // -- squares -----------------------------------------------------------

  async landOn(who, total) {
    const st = this.st, ply = st.players[who], pos = ply.pos, sq = SQ[pos];

    if (pos === GO_TO_JAIL) { await this.gotoJail(who); return; }
    if (sq.name === "Chance" || sq.name === "Community Chest") {
      await this.drawCard(who, sq.name === "Chance");
      return;
    }

    // #4: the original writes "You have landed on <name>" and goes straight
    // on to the square's own screen -- the routine at 0x6620 returns without
    // waiting for a key.  The <Press Any Key> beat here was mine.
    // The original makes no sound when a piece lands: there is no Sound()
    // call in the landing routine at 0x6620.  This used to play the F2
    // save-game beep.
    // The square has already been named on the board by landingFlash.

    if (sq.name.includes("Income Tax")) { await this.incomeTax(who); return; }
    if (sq.name.includes("Luxury Tax")) {
      await this.pay(who, 75);
      return;
    }
    if (!sq.ownable) return;

    const ps = st.props[pos];
    if (ps.owner === BANK) { await this.offerPurchase(who, pos); return; }
    if (ps.owner === who) return;
    if (ps.mortgaged) {
      await this.announce(ply.name, ["but it is mortgaged.  No charge."],
                          pos);
      return;
    }
    // The wording and line order follow the captures: the owner is named,
    // railroads and utilities say how many are held, and a full colour group
    // doubles the rent.  No key is pressed here -- the amount goes up, the
    // money moves, and the Business/Go on prompt follows.
    const rent = rentDue(st, pos, total);
    // No full stop: the capture reads "alice owns St. James Place".
    const lines = [`${st.players[ps.owner].name} owns ${sq.name}`];
    if (sq.kind === RAILROAD) {
      const n = countKind(st, ps.owner, RAILROAD);
      if (n > 1) lines.push(`and owns a total of ${n} railroads.`);
      lines.push(`Your rent is $${rent}.`);
    } else if (sq.kind === UTILITY) {
      const n = countKind(st, ps.owner, UTILITY);
      if (n >= 2) {
        lines.push("and owns the other utility too.");
        lines.push(`10 times dice roll of ${total}`);
      } else {
        lines.push(`You had rolled a ${total} so`);
      }
      lines.push(`your rent is $${rent}.`);
    } else {
      // Just the one line: a capture of this case shows no DOUBLED!, which
      // belongs to the card that charges double railroad rent.
      if (ps.houses === 0 && ownsGroup(st, ps.owner, sq.group)) {
        lines.push("and the entire color group.");
      }
      lines.push(`Your rent is $${rent}.`);
    }
    this.notice(`${ply.name}'s turn`, lines, pos);
    await this.pay(who, rent, ps.owner);
  }

  // The original's four-way offer, not a yes/no.  Auction is run by the
  // players themselves; the program only records the outcome.
  async offerPurchase(who, pos) {
    const st = this.st, ply = st.players[who], sq = SQ[pos];
    for (;;) {
      const c = await this.ask(ply.name, [`${sq.name} isn't owned.`, ""],
        ["Want to ~Purchase it from the bank?",
         "     or ~Auction it off?",
         "do some ~Business first?",
         "     or ~Go on with the game?"], pos);
      if (c === "p") {
        if (ply.cash < sq.cost) {
          await this.invalid([`You can't afford $ ${sq.cost}.`]);
          continue;
        }
        st.props[pos].owner = who;
        this.cue("pay");            // cash leaving a player
        await this.countCash(who, -sq.cost);
        await this.announce(ply.name, [`${sq.name} purchased.`], pos);
        return;
      }
      if (c === "a") { await this.auction(who, pos); return; }
      if (c === "b") { await this.business(who); continue; }
      return;
    }
  }

  // #10: the humans run the auction; the program records who won and for
  // how much, then takes the money.  Previously this only showed a notice.
  async auction(who, pos) {
    const st = this.st, sq = SQ[pos];
    this.cue("auction");
    // The original asks once and takes the name straight after the last
    // line -- there is no "Buyer's name?" label anywhere in the binary.
    const idx = await this.askPlayer([sq.name,
      "Have the banker conduct an auction",
      "and then give me the buyer's name."]);
    if (idx === null) return;
    const price = await this.askNumber("Auction",
      [`How much did ${st.players[idx].name} bid`],
      `for ${sq.name}?  $ `, 0, 100000, false);
    if (price === null) return;
    if (st.players[idx].cash < price) {
      await this.announce("Auction",
        [`${st.players[idx].name} can't afford that.`]);
      return;
    }
    await this.countCash(idx, -price);
    st.props[pos].owner = idx;
    // The routine's own closing string is " purchased." (CHN 0xA5AF) -- the
    // same line a bank purchase prints.
    await this.announce("Auction", [`${sq.name} purchased.`], pos);
  }

  // Move the piece to jail, announce it, and play the descent.  The routine
  // at CHN load 0x52E5 does all three, whichever way the player got there:
  // it places the piece, blanks the message line, writes "GO DIRECTLY TO
  // JAIL!" on the board, sweeps 1000 Hz down to 200 and waits.  Every jail
  // path goes through it, so the message belongs here -- this used to move
  // the piece silently and say nothing at all.
  async gotoJail(who) {
    const ply = this.st.players[who];
    ply.pos = JAIL; ply.inJail = true; ply.jailTurns = 0;
    this.st.doubles = 0;
    // The message goes on the board, not into a text panel, and no key is
    // pressed: the routine writes it into the board's message area, plays
    // the descent and carries on (CHN load 0x52E5, captured).
    this.cue("jail");
    this.showBoard(["GO DIRECTLY TO JAIL!"]);
    await sleep(DATA.cues.jail.reduce((n, t) => n + t[1], 0));
  }

  async drawCard(who, isChance) {
    const st = this.st;
    const deck = isChance ? DATA.chance : DATA.chest;
    const order = isChance ? st.chanceOrder : st.chestOrder;
    const idx = isChance ? st.chanceNext : st.chestNext;
    const card = deck[order[idx]];
    if (isChance) st.chanceNext = (idx + 1) % order.length;
    else st.chestNext = (idx + 1) % order.length;

    const label = isChance ? "CHANCE" : "COMMUNITY CHEST";
    this.showBoard([], { label });
    await sleep(400);
    await this.announce(label, wrap(card.text, 34));
    await this.applyCard(who, card);
  }

  async applyCard(who, card) {
    const st = this.st, ply = st.players[who];
    const others = st.players.map((_, i) => i)
      .filter((i) => i !== who && !st.players[i].bankrupt);

    switch (card.action) {
      case "collect": await this.collect(who, card.amount); break;
      case "pay": await this.pay(who, card.amount); break;
      case "collect_each":
        for (const o of others) await this.pay(o, card.amount, who);
        break;
      case "pay_each":
        // Owing every other player at once is the one debt the bank will
        // bridge rather than force a sale for.
        for (const o of others) {
          if (!await this.pay(who, card.amount, o, true)) return;
        }
        break;
      case "advance":
      case "advance_no_go": {
        const steps = (card.target - ply.pos + 40) % 40;
        // The piece flashes where it stands before it sets off, and the
        // salary is paid as it crosses GO rather than afterwards.
        await this.advanceFlash(who);
        await this.animateMove(who, ply.pos, steps,
                               card.action === "advance");
        ply.pos = card.target;
        await this.landOn(who, st.dice[0] + st.dice[1]);
        break;
      }
      case "back": {
        // The distance is in `target`, not `amount`.  It walks backwards a
        // square at a time on the board rather than teleporting (#14).
        const start = ply.pos;
        this.showBoard([]);
        for (let i = 1; i <= card.target; i++) {
          const p = (start - i + 40) % 40;
          ply.pos = p;
          this.showBoard([]);
          this.cue(CORNERS.includes(p) ? "corner" : "step");
          await sleep(DATA.geom.stepMs);
        }
        await this.landOn(who, st.dice[0] + st.dice[1]);
        break;
      }
      case "goto_jail": await this.gotoJail(who); break;
      case "jail_card": ply.jailCards += 1; break;
      case "nearest_railroad":
      case "nearest_utility": {
        const rr = card.action === "nearest_railroad";
        const tgt = nearest(ply.pos,
          rr ? DATA.cards.railroadSquares : DATA.cards.utilitySquares);
        const steps = (tgt - ply.pos + 40) % 40;
        await this.animateMove(who, ply.pos, steps);   // walk it (#14)
        ply.pos = tgt;
        await this.nearestCharge(who, rr, !rr);
        break;
      }
      case "repairs": {
        // amount is charged per house, target per hotel.
        let bill = 0;
        for (const p of holdings(st, who)) {
          const h = st.props[p].houses;
          bill += h === R.housesPerHotel ? card.target : h * card.amount;
        }
        await this.announce(ply.name, [`Your repairs were $ ${bill}.`]);
        await this.pay(who, bill);
        break;
      }
      default: break;
    }
  }

  // The two "advance to the nearest" cards do not charge ordinary rent: the
  // railroad pays double, and the utility ten times a freshly thrown pair.
  async nearestCharge(who, doubled, tenTimes) {
    const st = this.st, ply = st.players[who], pos = ply.pos;
    const ps = st.props[pos];
    this.showBoard([]);
    if (ps.owner === BANK) { await this.offerPurchase(who, pos); return; }
    if (ps.owner === who || ps.mortgaged) return;

    const roll = st.rng.die() + st.rng.die();
    let rent;
    if (tenTimes) {
      rent = roll * 10;
      // Rent is not a "press any key" beat.
      this.notice(`${ply.name}'s turn`, [`You had rolled a ${roll}`,
        `10 times dice roll of ${roll}`, `your rent is $ ${rent}.`], pos);
    } else {
      rent = rentDue(st, pos, roll) * (doubled ? 2 : 1);
      this.notice(`${ply.name}'s turn`,
                  [`Your rent is $ ${rent}`, "  DOUBLED!"], pos);
    }
    await this.pay(who, rent, ps.owner);
  }

  // The tax screen tells the player afterwards whether they chose well --
  // five different verdicts, depending on how the flat rate compared.
  async incomeTax(who) {
    const st = this.st, ply = st.players[who];
    const flatRate = R.incomeTaxFlat;
    const calc = Math.floor(netWorth(st, who) * R.incomeTaxRate / 100);
    const c = await this.ask(ply.name, ["INCOME TAX", "Do you choose to pay"],
      ["   a ~Flat rate of $200?", "  or ~Calculated 10% tax?"]);
    const flat = c === "f";
    const amount = flat ? flatRate : calc;

    let verdict;
    if (calc === flatRate) {
      verdict = ["Either way turns out", "to be exactly $200."];
    } else if (flat && calc < flatRate) {
      verdict = ["Too bad.  Calculating your tax",
                 `would have been only $ ${calc}.`];
    } else if (flat) {
      verdict = ["Smart move.  Calculating your tax",
                 `would have cost you $ ${calc}.`];
    } else if (calc > flatRate) {
      verdict = ["Bad choice.  This is", `costing you $ ${calc}.`];
    } else {
      verdict = ["Wise choice.  The total",
                 `calculation is only $ ${calc}.`];
    }
    await this.announce("INCOME TAX", verdict);
    await this.pay(who, amount);
  }

  // -- business menu -----------------------------------------------------

  // The green overlay: business first, or get on with the game.
  // What the board writes on its title row.  A repeat roll is titled
  // "<name> again" rather than "<name>'s turn"; the suffix is at CHN load
  // 0x4E88, concatenated onto the name when the doubles counter is above
  // zero.  Captured: bob's throw of doubles lands him on St. Charles under
  // "bob's turn", and the board is retitled "bob again" for the repeat roll
  // that follows -- so the change shows at the start of the repeat, which is
  // why this reads a display flag rather than the counter.  The blue panels
  // keep saying "bob's turn" right through the repeat turn.
  boardTitle() {
    const st = this.st, name = st.players[st.current].name;
    return st.again ? `${name} again` : `${name}'s turn`;
  }

  // What an in-jail player is told above the Business/Go on prompt.
  // Disassembled at CHN load 0xD6D7, which is the whole rule:
  //
  //     if Ply[cur].inJail then begin
  //       write('YOU ARE IN JAIL!');
  //       if doubles > 0 then write('You lose your double roll turn.');
  //       doubles := 0
  //     end else write('You are on ', ...)
  //
  // The second line is not part of the status: it appears only while a run
  // of doubles is still standing -- another roll was coming and jail has
  // taken it -- and drawing the status clears that run either way.  This
  // port showed it to everyone in jail on every turn, doubles or not.
  // DS:0x391F is the counter: 0x29AB bumps it when the dice match and zeroes
  // it when they do not, and 0x3A73 jails a player when it reaches three.
  jailStatus() {
    const lines = ["YOU ARE IN JAIL!"];
    if (this.st.doubles > 0) lines.push("You lose your double roll turn.");
    this.st.doubles = 0;
    return lines;
  }

  async businessOrGo(who) {
    const st = this.st, pos = st.players[who].pos;
    const t = this.text;
    this.panel(`${st.players[who].name}'s turn`,
               // Square 10 is named "just visiting..." in the table, which
               // is what a jailed player used to be told they were doing.
               (st.players[who].inJail
                 ? this.jailStatus()
                 : [`You are on ${SQ[pos].name}.`]), null,
               SQ[pos].ownable ? pos : null);
    // A brown-framed green box laid over the message panel, with its hot keys
    // white on the same green rather than the blue panel's light cyan.
    this.framed(T.promptPanel, C.BROWN, C.GREEN);
    let row = T.promptPanel[1] + 2;
    for (const opt of R.businessPrompt) {
      this.hotkey(T.promptPanel[0] + 2, row, opt, at(C.WHITE, C.GREEN),
                  at(C.YELLOW, C.GREEN));
      row += 1;
    }
    this.paintText();
    if (await this.key(["b", "g"]) === "b") await this.business(who);
  }

  // `raising` is set when the menu was opened because the player owes money
  // they cannot pay: it closes the menu as soon as they have raised enough,
  // rather than making them find the Go-on option again.
  async business(who, raising = false) {
    this.inBusiness = true;
    try {
      await this.businessLoop(who, raising);
    } finally {
      this.inBusiness = false;
    }
  }

  async businessLoop(who, raising = false) {
    const owed = raising ? this.st.players[who].cash : null;
    for (;;) {
      if (raising && this.st.players[who].cash > owed) return;
      const options = T.businessOptions;
      this.businessPanel(options);

      const keys = options.map((o) => o[o.indexOf("~") + 1].toLowerCase());
      const c = await this.key(keys);
      if (c === "g") return;
      else if (c === "b") await this.buyFlow(who);
      else if (c === "s") await this.sellFlow(who);
      else if (c === "h") await this.buildFlow(who);
      else if (c === "t") await this.showDeed();
      else if (c === "m") await this.mortgageFlow(who);
      else if (c === "r") await this.returnFlow(who);
      else if (c === "u") await this.unmortgageFlow(who);
    }
  }

  // -- typed input -------------------------------------------------------
  //
  // Every one of these flows asks the player to type something -- a short
  // property name, a colour group, another player's name, a number -- rather
  // than picking from a list.  An earlier version of this port replaced them
  // with lettered menus, which is not how any of it works.

  async panelInput(title, lines, prompt, width, gap = true, after = null) {
    this.panel(title, gap ? [...lines, "", prompt] : [...lines, prompt]);
    if (after) { after(); this.paintText(); }
    const [l, top, r] = this.activePanel();
    // A prompt that nearly fills the panel leaves no room for the field, so
    // it drops to the next line rather than spilling past the frame.
    let col = l + 3 + prompt.length;
    let row = top + 3 + lines.length + (gap ? 1 : 0);
    if (col + width > r) { col = l + 3; row += 1; }
    return await this.readLine(col, row, width, at(C.WHITE, C.BLUE), false);
  }

  // The price prompts put the question on the last line of the message
  // itself -- "Boardwalk?  $" -- with no blank line before it, so `gap`
  // turns that spacer off.
  async askNumber(title, lines, prompt, lo, hi, gap = true) {
    for (;;) {
      const text = await this.panelInput(title, lines, prompt, 6, gap);
      if (text === "") return null;
      const v = parseInt(text, 10);
      if (!isNaN(v) && v >= lo && v <= hi) return v;
      await this.invalid(["Too many."]);
    }
  }

  findByShortName(text) {
    const key = text.trim().toUpperCase();
    if (!key) return null;
    for (let p = 0; p < SQ.length; p++) {
      if (SQ[p].ownable && SQ[p].shortUc === key) return p;
    }
    return null;
  }

  findGroup(text) {
    const key = text.trim().toUpperCase();
    if (!key) return null;
    for (let i = 0; i < GROUPS.length; i++) {
      if (GROUPS[i] && GROUPS[i].name.toUpperCase().startsWith(key)) return i;
    }
    return null;
  }

  // The five-row block the original lists the eligible short names in.  Each
  // row is one pair of colour groups in board order, which is why every row
  // comes to eighteen columns; names run together with no separator.
  // Every name in the picker wears its group's board colours -- measured
  // from a capture: Medit and Balt on 0x51, Ori/Ver/Con on 0x3F, and so on
  // for all ten groups.  Drawn in the panel's own colours, as this port did,
  // the only cue to which group a name belongs is lost.
  paintShortNames(positions, firstLine) {
    const t = this.text;
    const [l, top] = this.activePanel();
    const keep = [...positions].sort((a, b) => a - b);
    [[1, 2], [3, 4], [5, 6], [7, 8], [9, 10]].forEach((groups, r) => {
      let col = l + 3 + 7;
      const row = top + 3 + firstLine + r;
      for (const g of groups) {
        const grp = GROUPS[g];
        for (const p of keep) {
          if (SQ[p].short && SQ[p].group === g) {
            t.write(col, row, SQ[p].short, at(grp.ttext, grp.tback));
            col += SQ[p].short.length;
          }
        }
      }
    });
  }

  shortNameRows(positions) {
    const keep = [...positions].sort((a, b) => a - b);
    const rows = [];
    for (const groups of [[1, 2], [3, 4], [5, 6], [7, 8], [9, 10]]) {
      let names = "";
      for (const g of groups) {
        for (const p of keep) {
          if (SQ[p].short && SQ[p].group === g) names += SQ[p].short;
        }
      }
      rows.push(" ".repeat(7) + names);
    }
    return rows;
  }

  // The original's shared property prompt (CHN 0x7A60) takes a mode -- title
  // deed, sell, mortgage, unmortgage, buy -- and each mode carries a phrase
  // for "There's nothing ...".  Measured against the real program: the list
  // is shown before the question and the empty case is answered without
  // asking anything at all.
  async pickProperty(prompt, ownedBy, predicate, nothing) {
    const st = this.st;
    const eligible = [];
    for (let p = 0; p < SQ.length; p++) {
      if (!SQ[p].short) continue;
      if (ownedBy !== null && st.props[p].owner !== ownedBy) continue;
      if (predicate && !predicate(p)) continue;
      eligible.push(p);
    }
    if (nothing && !eligible.length) {
      await this.invalid([`There's nothing ${nothing}`]);
      return null;
    }
    const lines = ["Give me the short name of the", prompt, "",
                   ...this.shortNameRows(eligible)];
    const paint = () => this.paintShortNames(eligible, 3);
    const text = await this.panelInput(st.players[st.current].name, lines,
                                       "Which? ", 8, false, paint);
    if (text === "") return null;
    const pos = this.findByShortName(text);
    if (pos === null) {
      await this.invalid([`There's nothing named ${text}.`]);
      return null;
    }
    if (ownedBy !== null && st.props[pos].owner !== ownedBy) {
      await this.invalid([`You don't own ${SQ[pos].name}.`]);
      return null;
    }
    if (predicate && !predicate(pos)) {
      await this.invalid([`Can't do that with ${SQ[pos].name}.`]);
      return null;
    }
    return pos;
  }

  // The original lists the groups and takes a single keypress -- L/C/D/O/R/
  // Y/G/B, with N to back out -- rather than reading a typed name.  The set
  // is tested one letter at a time at CHN 0x93EB..0x941B.
  //
  // The list is not the fixed eight.  The loop at CHN 0x9154 walks groups
  // 1..8 and skips any the player does not own outright, or that carries a
  // mortgage, so only the groups you can act on are offered.  Each row is
  // seven columns of lead-in -- the last two a swatch in the group's own
  // colours -- then the name with its first letter in the hot-key colour.
  async pickGroup(prompt, groups = null) {
    const st = this.st;
    const ids = groups === null ? GROUP_IDS : GROUP_IDS.filter(
      (g) => groups.includes(g));
    const keyOf = new Map(T.groupKeys.map(([k, n]) => [n, k]));
    const lines = ["Tell me the color group", prompt, ""];
    for (const g of ids) lines.push(" ".repeat(7) + "~" + GROUPS[g].name);
    lines.push(`    or ~${T.groupCancelKey}one... changed my mind.`);

    this.panel(st.players[st.current].name, lines);
    this.paintGroupRows(ids, 3);
    this.paintText();

    const allowed = ids.map((g) => keyOf.get(GROUPS[g].name).toLowerCase())
      .concat([T.groupCancelKey.toLowerCase()]);
    const c = await this.key(allowed);
    if (c === T.groupCancelKey.toLowerCase()) return null;
    for (const g of ids) {
      if (keyOf.get(GROUPS[g].name).toLowerCase() === c) return g;
    }
    return null;
  }

  // The original sets TextBackground from the ColorGroup record's +25 field
  // and TextColor from +23 before writing the swatch and the name, with the
  // first letter in LightCyan (CHN 0x9282-0x92B8).  The five spaces before
  // the swatch keep the panel's colours, so they are left as drawn.
  paintGroupRows(ids, firstLine) {
    const t = this.text;
    const [l, top] = this.activePanel();
    ids.forEach((g, i) => {
      const grp = GROUPS[g];
      const row = top + 3 + firstLine + i;
      let col = l + 3 + 5;
      t.write(col, row, "  ", at(grp.ttext, grp.tback));
      col += 2;
      t.write(col, row, grp.name.slice(0, 1), at(C.LIGHTCYAN, grp.tback));
      t.write(col + 1, row, grp.name.slice(1), at(grp.ttext, grp.tback));
    });
  }

  // The original writes "Give me the name of the / player you are selling /
  // <Property> to." and takes the name after the last line -- there is no
  // "Name?" label (CHN 0x890F-0x896D).
  async askPlayer(lines) {
    const st = this.st;
    const text = await this.panelInput(st.players[st.current].name,
      lines.slice(0, -1), lines[lines.length - 1] + " ", 12, false);
    if (text === "") return null;
    for (let i = 0; i < st.players.length; i++) {
      if (st.players[i].name.toLowerCase() === text.toLowerCase()
          && !st.players[i].bankrupt) return i;
    }
    await this.invalid([`There's nobody named ${text}.`]);
    return null;
  }

  // -- group arithmetic ---------------------------------------------------

  // #20: while any property in a colour group carries houses, nothing in
  // that group may be mortgaged or sold -- the houses must go back first.
  groupHasHouses(group) {
    const g = GROUPS[group];
    if (!g) return false;
    return g.members.some((p) => this.st.props[p].houses > 0);
  }

  unitsInGroup(group) {
    return GROUPS[group].members
      .reduce((n, p) => n + this.st.props[p].houses, 0);
  }
  maxUnitsInGroup(group) {
    return R.housesPerHotel * GROUPS[group].members.length;
  }
  canBuildOn(who, group) {
    const g = GROUPS[group];
    return !!g && g.buildable && ownsGroup(this.st, who, group)
      && g.members.every((p) => !this.st.props[p].mortgaged);
  }
  // Units go on evenly, lowest square first; they come off the same way in
  // reverse, so a group is never left unbalanced.
  distributeUnits(group, count) {
    const members = GROUPS[group].members.slice();
    const level = {}; members.forEach((p) => { level[p] = this.st.props[p].houses; });
    const picks = [];
    for (let i = 0; i < count; i++) {
      const c = members.filter((p) => level[p] < R.housesPerHotel);
      if (!c.length) break;
      c.sort((a, b) => (level[a] - level[b]) || (a - b));
      level[c[0]] += 1; picks.push(c[0]);
    }
    return picks;
  }
  collectUnits(group, count) {
    const members = GROUPS[group].members.slice();
    const level = {}; members.forEach((p) => { level[p] = this.st.props[p].houses; });
    const picks = [];
    for (let i = 0; i < count; i++) {
      const c = members.filter((p) => level[p] > 0);
      if (!c.length) break;
      c.sort((a, b) => (level[b] - level[a]) || (a - b));
      level[c[0]] -= 1; picks.push(c[0]);
    }
    return picks;
  }

  // -- the seven business flows -------------------------------------------

  async showDeed() {
    const pos = await this.pickProperty("Title Deed Card you want to see.",
                                        null, null);
    if (pos !== null) {
      await this.announce(this.st.players[this.st.current].name,
                          [SQ[pos].name], pos);
    }
  }

  async mortgageFlow(who) {
    const st = this.st;
    const pos = await this.pickProperty("property to mortgage.", who,
      (p) => !st.props[p].mortgaged && !this.groupHasHouses(SQ[p].group),
      "to mortgage.");
    if (pos === null) return;
    const amount = mortgageValue(pos);
    st.props[pos].mortgaged = true;
    await this.collect(who, amount);
    await this.announce(st.players[who].name,
      [SQ[pos].name, `mortgaged for $ ${amount}.`], pos);
  }

  async unmortgageFlow(who) {
    const st = this.st;
    const pos = await this.pickProperty("property to unmortgage.", who,
      (p) => st.props[p].mortgaged, "to unmortgage.");
    if (pos === null) return;
    const cost = unmortgageCost(pos);
    if (st.players[who].cash < cost) {
      await this.invalid([`You can't afford $ ${cost}.`]); return;
    }
    st.props[pos].mortgaged = false;
    await this.countCash(who, -cost);
    await this.announce(st.players[who].name,
      [SQ[pos].name, `unmortgaged for $ ${cost}.`], pos);
  }

  async buildFlow(who) {
    const st = this.st;
    // Measured: pressing H with nothing to build on answers straight away,
    // without ever showing the colour-group list.  The test comes first.
    const buildable = GROUP_IDS.filter((g) => this.canBuildOn(who, g));
    if (!buildable.length) {
      await this.invalid(["You have no property to build",
                          "on.  The entire color group",
                          "must be owned and unmortgaged."]);
      return;
    }
    const group = await this.pickGroup("you wish to improve.", buildable);
    if (group === null) return;
    if (!this.canBuildOn(who, group)) {
      await this.invalid(["You have no property to build",
                          "on.  The entire color group",
                          "must be owned and unmortgaged."]);
      return;
    }
    const allowed = this.maxUnitsInGroup(group);
    const now = this.unitsInGroup(group);
    if (now >= allowed) {
      await this.invalid(["That property is already fully",
                          "developed.  No more building."]);
      return;
    }
    const cost = GROUPS[group].houseCost;
    const count = await this.askNumber(st.players[who].name,
      [`Zoning Regulations allow ${allowed}`,
       `units in the ${GROUPS[group].name} group.`,
       `There are ${now || "no"} units now.`,
       `Each unit costs $ ${cost}.`],
      "How many units will you buy? ", 1, allowed - now);
    if (!count) return;
    const total = count * cost;
    if (st.players[who].cash < total) {
      await this.invalid(["You can't afford that."]); return;
    }
    this.cue("build");
    await this.countCash(who, -total);
    for (const p of this.distributeUnits(group, count)) st.props[p].houses += 1;
    await this.announce(st.players[who].name, [`That will cost $ ${total}.`]);
  }

  async returnFlow(who) {
    const st = this.st;
    // As with building, "nothing to return" comes before the group list.
    const holding = GROUP_IDS.filter(
      (g) => this.unitsInGroup(g) && ownsGroup(st, who, g));
    if (!holding.length) {
      await this.invalid(["You have no houses or", "hotels to return."]);
      return;
    }
    const group = await this.pickGroup("to return improvements.", holding);
    if (group === null) return;
    const now = this.unitsInGroup(group);
    if (!now || !ownsGroup(st, who, group)) {
      await this.invalid(["You have no houses or", "hotels to return."]);
      return;
    }
    // Returned units bring back half what they cost.
    const each = Math.floor(GROUPS[group].houseCost / 2);
    const count = await this.askNumber(st.players[who].name,
      [`There are ${now} units on`, `the ${GROUPS[group].name} group.`,
       `Each will bring $ ${each}.`],
      "How many units to return? ", 1, now);
    if (!count) return;
    this.cue("houses_sold");
    for (const p of this.collectUnits(group, count)) st.props[p].houses -= 1;
    const gain = count * each;
    await this.collect(who, gain);
    await this.announce(st.players[who].name, [`That will bring $ ${gain}.`]);
  }

  async sellFlow(who) {
    const st = this.st;
    const pos = await this.pickProperty("property to sell.", who,
      (p) => !this.groupHasHouses(SQ[p].group), "to sell.");
    if (pos === null) return;
    const buyer = await this.askPlayer(["Give me the name of the",
      "player you are selling", `${SQ[pos].name} to.`]);
    if (buyer === null) return;
    const price = await this.askNumber(st.players[who].name,
      [`What price have ${st.players[buyer].name} and`,
       "you agreed on to sell"], `${SQ[pos].name}?  $ `, 0, 100000, false);
    if (price === null) return;
    if (st.players[buyer].cash < price) {
      await this.invalid([`${st.players[buyer].name} can't afford $ ${price}.`]);
      return;
    }
    await this.countCash(buyer, -price);
    await this.collect(who, price);
    st.props[pos].owner = buyer;
    // The sell routine (CHN 0x888C-0x8BBD) carries no closing line: unlike
    // mortgage and unmortgage, which each print one, it returns to the menu.
  }

  async buyFlow(who) {
    const st = this.st;
    const pos = await this.pickProperty("property to buy.", null,
      (p) => st.props[p].owner !== BANK && st.props[p].owner !== who
             && st.props[p].houses === 0, "to buy.");
    if (pos === null) return;
    const seller = st.props[pos].owner;
    const price = await this.askNumber(st.players[who].name,
      [`What price has ${st.players[seller].name}`, "quoted for you to buy"],
      `${SQ[pos].name}?  $ `, 0, 100000, false);
    if (price === null) return;
    if (st.players[who].cash < price) {
      await this.invalid([`You can't afford $ ${price}.`]); return;
    }
    await this.countCash(who, -price);
    await this.collect(seller, price);
    st.props[pos].owner = who;
    // As with selling, the buy routine has no closing line of its own.
  }

  // -- turns -------------------------------------------------------------

  async jailTurn(who) {
    const st = this.st, ply = st.players[who];

    // On the board, not in a panel.  Captured from a game loaded straight
    // into jail: "You are in JAIL." at column 19 row 5 and the options at
    // rows 7 and 8, left-aligned, the words cyan and the hot letters
    // magenta.  Every option string runs exactly eight characters before its
    // hot letter -- "Want to ", "     or ", " or use " -- so P, R and C all
    // land on column 27.  Routing this through ask() put it in the blue
    // message panel, a screen the original never shows here.
    const c = await this.askOnBoard(jailPrompt(!!ply.jailCards),
                                    ply.jailCards ? "prc" : "pr");
    if (c === "p") {
      if (!await this.pay(who, R.jailFine)) return false;
      ply.inJail = false;
      return true;
    }
    if (c === "c" && ply.jailCards) {
      ply.jailCards -= 1; ply.inJail = false; return true;
    }

    // The count is of rolls taken, not of turns spent in jail.  Counting
    // visits and testing before the prompt -- which is what this did -- puts
    // the forced payment on the turn *after* the third roll instead of on
    // the same one.
    ply.jailTurns += 1;

    // The same tumbling dice as any other roll, on the board.  The thrown
    // faces then stand for a second -- Delay(1000) at CHN load 0xE1BB --
    // before the throw is even looked at.  Without that beat a failed roll
    // flicked past so fast that the turn appeared to end the moment the key
    // went down, which is exactly what it looked like.
    const [a, b] = await this.rollDice();
    await sleep(G.jailRollPauseMs);

    if (a === b) {
      // Nothing is said: CHN load 0xE1CC sets the got-out flag, zeroes the
      // roll count and goes straight to the move.  "Doubles - N and N. /
      // You are out." was this port's invention -- neither string exists in
      // the program, and none of 233 captured text screens shows one.
      ply.inJail = false;
      ply.jailTurns = 0;
      await this.animateMove(who, ply.pos, a + b);
      await this.landOn(who, a + b);
      if (ply.bankrupt) return false;
      // The square is resolved and the Business/Go on prompt comes up, as
      // after any move.
      await this.businessOrGo(who);
      // And the throw still earns another roll, like any other double.  The
      // advance-player test at CHN load 0xE538 only moves on when the
      // doubles counter is zero, and leaving jail this way sets it to one.
      // Captured: alice rolls her way out without paying, walks to Kentucky
      // Avenue under "alice's turn", and the board is retitled "alice again"
      // for the roll that follows.  This port ended the turn instead.
      st.doubles = 1;
      st.again = true;
      return true;
    }

    if (ply.jailTurns >= 3) {
      // The third roll has failed, so the fine is no longer a choice.
      // Disassembled at CHN load 0xE20D, and captured from a game loaded
      // straight into jail:
      //
      //     gotoxy(19, 7); write('You have rolled 3')
      //     gotoxy(19, 8); write('times and must pay.')
      //     if sound then Sound(440);
      //     Delay(300); NoSound; Delay(1000)
      //     gotoxy(19, 7); write('                 ')    { 17 blanks }
      //     gotoxy(19, 8); write('                   ')  { 19 blanks }
      //     Key := 'P'                                   { forced }
      //
      // Two lines on the board, wiped by blanking strings cut to their exact
      // lengths, with no keypress anywhere -- not the four-line panel with a
      // "<Press Any Key>" that this port used to show.  "You must pay $50 /
      // to get out of jail." is not part of it: those belong to the cash-
      // short arm of the Pay branch at 0xE325.
      this.cue("jail_third");
      this.showBoard(["You have rolled 3", "times and must pay."]);
      await sleep(G.jailFineMs);
      this.showBoard([]);
      if (ply.cash < R.jailFine)
        this.showBoard(["You must pay $50", "to get out of jail."]);
      if (!await this.pay(who, R.jailFine)) return false;
      ply.inJail = false;
      await this.animateMove(who, ply.pos, a + b);
      await this.landOn(who, a + b);
      if (!ply.bankrupt) await this.businessOrGo(who);
      return false;
    }

    // A failed roll that is not the third ends the turn with nothing said.
    // Captured: prompt, tumbling dice, the thrown faces left on the board,
    // then the next player's title -- no message and no Business/Go on
    // prompt.  The routine returns at CHN load 0xE522 without waiting.
    return false;
  }

  async turn() {
    const st = this.st, who = st.current, ply = st.players[who];
    if (ply.bankrupt) return;

    // No interest is charged here.  The routine that says "You have been
    // charged interest" (CHN load 0x8268) has exactly two callers, both in
    // the flows where a property changes hands between players, and nothing
    // in a turn loop calls it: interest falls due when a mortgage is
    // redeemed or a mortgaged property is traded, not every time its owner's
    // turn comes round.  Charging it per turn was this port's invention.
    if (ply.loan) {
      const owed = ply.loan;
      await this.announce(ply.name, ["YOU MUST PAY BACK BANK LOAN",
                                     `OF $${owed} BEFORE YOU PROCEED.`]);
      ply.loan = 0;
      if (!await this.pay(who, owed, null, false)) return;
      await this.announce(ply.name, ["You have repaid the bank loan",
                                     `of $${owed} and now may proceed.`]);
    }

    // Reset before the jail call, not after: rolling a double out of jail
    // seeds both -- it counts as the first double of a run and earns another
    // roll -- and clearing them afterwards threw that away.
    st.doubles = 0;
    st.again = false;
    if (ply.inJail) {
      if (!await this.jailTurn(who)) return;
      // A card drawn on the way out can put the player straight back.
      if (ply.inJail) return;
    }

    for (;;) {
      const [a, b] = await this.rollDice();
      const total = a + b;
      if (a === b) {
        st.doubles += 1;
        if (st.doubles >= 3) {
          // Captured from the real program: the third double writes "GO
          // DIRECTLY TO JAIL!" into the board's message area and holds it
          // for several seconds before the turn passes.  "Three doubles in a
          // row" is in the binary too but is not what this path shows.
          this.cue("doubles");
          await this.gotoJail(who);
          return;
        }
      }
      const start = ply.pos;
      const dest = (start + total) % 40;
      // The chime between the dice stopping and the piece setting off:
      // measured running right up to the first step chirp.  animateMove pays
      // the salary as the piece crosses GO, on the square and after the
      // corner chime, rather than up front.
      this.cue("landing");
      await this.flashPiece(who);
      await this.animateMove(who, start, total);
      await this.landOn(who, total);
      if (ply.bankrupt) return;
      await this.businessOrGo(who);
      if (a !== b || ply.inJail) return;
      // No panel for a repeat: there is no "Doubles" string anywhere in the
      // program and no capture shows one.  The only sign of it is the
      // board's own title, which the next roll draws.
      st.again = true;
    }
  }

  async run() {
    await this.setup();
    this.status("F1 toggles sound");
    for (;;) {
      await this.turn();
      const left = active(this.st);
      if (left.length <= 1) {
        this.cue("winner");
        const w = left[0];
        await this.announce("", ["", `${w ? w.name : "Nobody"} is the WINNER!`,
                                 "", "Thanks for playing Monopoly."]);
        return;
      }
      do { this.st.current = (this.st.current + 1) % this.st.players.length; }
      while (this.st.players[this.st.current].bankrupt);
    }
  }
}
