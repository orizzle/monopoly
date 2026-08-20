"""The turn loop and every player interaction.

Flow follows the original: an opening name-entry screen, then rounds of
dice-roll, move, resolve-square, optional business, repeat, until one player
is left standing.

Two mechanics here are the author's own rather than Parker Brothers':

  * Mortgages accrue interest every time their owner's turn comes round, and
    the player is offered the chance to stop it by repaying the principal.
  * When a player cannot cover a debt in cash the bank lends the shortfall
    rather than forcing an immediate sale -- "I WILL LOAN UNTIL YOUR TURN" --
    and the loan must be cleared before that player may move again.
"""

from __future__ import annotations

import random

from . import cards, data, graphics, rules, save, screens, sound
from .cga import BLACK, LIGHTGRAY, WHITE, Screen
from .display import Terminal
from . import state as state_mod
from .state import BANK, GameState
from .tprandom import TurboRandom


class Quit(Exception):
    """Raised to unwind out of the turn loop on request."""


class Game:
    def __init__(self, term: Terminal, seed: int | None = None,
                 audio: str = "auto") -> None:
        self.term = term
        self.scr = Screen()
        self.state: GameState | None = None
        # The 1985 generator, not Python's.  Replaced by the state's own
        # instance in new_game so every draw comes off one sequence.
        self.rng = TurboRandom(seed if seed is not None else state_mod.STOCK_SEED)
        self.seed = seed
        asset = graphics.find_asset()
        try:
            self.board_art = graphics.load_board(asset) if asset else None
        except (graphics.MissingArtwork, ValueError):
            self.board_art = None
        self.speaker = sound.Speaker(audio)
        # The Pascal loop bound at CHN 0x23C7.  Play always uses the original
        # 10; only tools/record.py raises it, to make the tumble watchable.
        self.roll_cycles = sound.ROLL_CYCLES
        # Set while the business menu is open.  Everything reached from that
        # menu is drawn in its panel rather than the ordinary turn panel.
        self.in_business = False

    # ------------------------------------------------------------------
    # Small interaction helpers
    # ------------------------------------------------------------------

    def _show(self) -> None:
        self.term.paint(self.scr)

    def cue(self, name: str) -> None:
        """Play one of the recovered sound effects, if sound is on."""
        if self.state is not None:
            self.speaker.enabled = self.state.sound
        self.speaker.cue(name)

    def wait_key(self, allowed: str | None = None) -> str:
        """Block for a keypress, optionally restricted to a set of letters."""
        while True:
            # A driving terminal (the test auto-player) gets to see which keys
            # the prompt will accept; a human one just reads the keyboard.
            chooser = getattr(self.term, "choose", None)
            try:
                key = chooser(allowed) if chooser else self.term.read_key()
            except EOFError:
                raise Quit
            if key == "\x03":
                raise Quit
            if key == "F1" and self.state:
                self.state.sound = self.speaker.toggle()
                continue
            if allowed is None:
                return key
            k = key.lower()
            if k in allowed:
                return k

    def _panel(self, title: str, lines: list[str],
               options: list[str] | None = None,
               deed: int | None = None) -> tuple[int, int, int, int]:
        """Draw a prompt in whichever panel the game is currently in.

        Screens reached from the business menu keep its green panel and its
        "<name> on <square>." header, which sits a row higher than the turn
        panel's title.  Returns the panel geometry so a caller that reads a
        line knows where to put the cursor.
        """
        if self.in_business:
            screens.draw_business_screen(self.scr, self.state, lines, deed)
            return screens.BUSINESS_PANEL
        screens.draw_turn_screen(self.scr, self.state, title, lines,
                                 options, deed)
        return screens.MESSAGE_PANEL

    def hold(self, ms: float) -> None:
        """Wait out one of the original's Delay() beats, when animating."""
        if self.animating and ms > 0:
            import time
            time.sleep(ms / 1000)

    def notice(self, title: str, lines: list[str],
               deed: int | None = None) -> None:
        """Show a panel and carry straight on, without waiting for a key.

        Rent is charged this way: the captures show the amount owed on screen
        and then the money moving, with no "<Press Any Key>" beat between --
        the next thing the player sees is the Business/Go on prompt.
        """
        self._panel(title, lines, None, deed)
        self._show()

    def announce(self, title: str, lines: list[str],
                 deed: int | None = None) -> None:
        """Show a message and wait for any key -- the '<Press Any Key>' beat."""
        self._panel(title, lines + ["", "<Press Any Key>"], None, deed)
        self._show()
        self.wait_key()

    def ask(self, title: str, lines: list[str], options: list[str],
            deed: int | None = None) -> str:
        """Show a prompt and return the chosen hot key."""
        screens.draw_turn_screen(self.scr, self.state, title, lines,
                                 options, deed)
        self._show()
        keys = "".join(screens.hotkey_of(o) for o in options)
        return self.wait_key(keys)

    def ask_on_board(self, runs, keys: str) -> str:
        """A prompt drawn on the board itself, not in the message panel."""
        self.show_board(runs)
        return self.wait_key(keys)

    def ask_number(self, title: str, lines: list[str], prompt: str,
                   lo: int, hi: int, gap: bool = True) -> int | None:
        """Ask for a number in range; None if the player backs out.

        The price prompts put the question on the last line of the message
        itself -- "Boardwalk?  $" -- with no blank line before it, so `gap`
        turns that spacer off.
        """
        while True:
            body = lines + (["", prompt] if gap else [prompt])
            panel = self._panel(title, body)
            self._show()
            x = panel[0] + 3 + len(prompt)
            y = panel[1] + 3 + len(lines) + (1 if gap else 0)
            text = self.term.read_line(self.scr, x, y, 6,
                                       (1 << 4) | WHITE)
            if text is None or text == "":
                return None
            try:
                value = int(text)
            except ValueError:
                continue
            if lo <= value <= hi:
                return value
            self.announce(title, ["Too many."])

    def invalid(self, lines: list[str]) -> None:
        self.cue("error")
        self._panel(self.state.player.name, lines + ["", "<Press Any Key>"])
        self._show()
        self.wait_key()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def setup(self) -> bool:
        """Name entry.  F2 at the prompt loads a saved game instead."""
        names: list[str] = []
        while len(names) < data.MAX_PLAYERS:
            screens.draw_title(self.scr, names)
            self._show()
            row = screens.FIRST_SLOT_ROW + len(names)
            text = self.term.read_line(
                self.scr, screens.SLOT_NAME_COL, row,
                screens.NAME_FIELD_WIDTH, (6 << 4) | WHITE)

            if text is None:  # F2 -> load
                loaded = self.load_game()
                if loaded:
                    return True
                continue
            if text == "":
                break
            names.append(text)

        if len(names) < data.MIN_PLAYERS:
            screens.draw_title(self.scr, names, show_prompt=False)
            screens.message_panel(
                self.scr, "",
                ["Sorry, there have to be at least",
                 "two players.  Do it again please.",
                 "", "<Press Any Key>"])
            self._show()
            self.wait_key()
            return self.setup()

        self.state = GameState.new_game(names, self.seed)
        self.rng = self.state.rng
        return True

    # ------------------------------------------------------------------
    # Money
    # ------------------------------------------------------------------

    def pay(self, who: int, amount: int, creditor: int | None = None,
            allow_loan: bool = False) -> bool:
        """Move money, raising it if necessary.  False if the player went bust.

        Rent is not lent against: a player who cannot pay has to mortgage or
        sell until they can, and is out if they cannot.  The original keeps
        two deduct helpers for exactly this -- the one at CHN load 0x5EDC
        simply takes the money, while 0x6064 falls back on the routine at
        0x5749 that offers to raise it or advance a loan, and every one of
        0x6064's seven callers is a transaction the player chose to enter
        into: buying from another player, selling, mortgaging, unmortgaging,
        building, and the purchase and auction pair.  Rent goes through the
        first, so `allow_loan` is off unless a caller says otherwise.
        """
        st = self.state
        ply = st.players[who]
        if amount <= 0:
            return True

        while ply.cash < amount:
            # The routine runs straight through: the red box with its five
            # beeps, then "YOU MUST RAISE SOME MONEY.", then Delay(1200), and
            # only then does it decide.  Traced on a player who went bust --
            # beeps at 89.28..90.85 s, the falling tone at 92.40 s -- so the
            # beeps sound in both cases and the fall is what the branch adds.
            self.cue("no_cash")
            screens.draw_no_cash(self.scr, ply.name)
            self._show()
            self.hold(sum(d for _hz, d in sound.CUES["no_cash"].tones))
            self.notice(f"{ply.name}'s turn", ["YOU MUST RAISE SOME MONEY."])
            self.hold(graphics.RAISE_PAUSE_MS)
            if not rules.can_raise(st, who, amount):
                self.notice(f"{ply.name}'s turn", ["YOU HAVE NO ASSETS."])
                self.bankrupt(who, creditor)
                return False
            # Mortgaging and selling is how assets become cash -- but only
            # a real player can work the menu.  A scripted or headless run
            # has no one to drive it, and opening it there would sit waiting
            # for a key that never comes.
            before = ply.cash
            if self.animating:
                self.business_menu(raising=True)
            if ply.cash >= amount:
                break
            if not allow_loan:
                if ply.cash <= before:
                    # Nothing was raised and nothing more can be: the debt
                    # cannot be carried any further.  This is where a player
                    # who will not mortgage or sell goes out.
                    self.notice(f"{ply.name}'s turn", ["YOU HAVE NO ASSETS."])
                    self.bankrupt(who, creditor)
                    return False
                continue
            shortfall = amount - ply.cash
            ply.loan += shortfall
            ply.cash += shortfall
            self.announce(ply.name, ["I WILL LOAN UNTIL YOUR TURN."])

        self.count_cash(who, -amount)
        self.cue("pay")
        if creditor is not None and not st.players[creditor].bankrupt:
            st.players[creditor].cash += amount
        return True

    def receive(self, who: int, amount: int) -> None:
        if not amount:
            return
        self.cue("receive")
        self.count_cash(who, amount)

    def count_cash(self, who: int, delta: int) -> None:
        """Run a total up or down $5 at a time, ticking as it goes.

        The original never snaps a figure to its new value; it counts, and
        the counting is audible.  A headless run sets the total directly --
        the test suite drives thousands of turns and would otherwise sleep
        through hundreds of steps apiece.
        """
        import time

        ply = self.state.players[who]
        target = ply.cash + delta
        if not delta or not self.animating:
            ply.cash = target
            return

        step = graphics.CASH_STEP_AMOUNT if delta > 0 else -graphics.CASH_STEP_AMOUNT
        while (step > 0 and ply.cash < target) or (step < 0 and ply.cash > target):
            nxt = ply.cash + step
            ply.cash = min(nxt, target) if step > 0 else max(nxt, target)
            self.cue("money_up" if delta > 0 else "money")
            screens.cash_line(self.scr, self.state)
            self._show()
            time.sleep(graphics.CASH_STEP_MS / 1000)
        ply.cash = target

    def bankrupt(self, who: int, creditor: int | None = None) -> None:
        st = self.state
        ply = st.players[who]
        ply.bankrupt = True
        self.cue("bankrupt")

        holdings = st.holdings(who)
        if creditor is not None and not st.players[creditor].bankrupt:
            for pos in holdings:
                st.props[pos].owner = creditor
            st.players[creditor].cash += max(ply.cash, 0)
            where = st.players[creditor].name
        else:
            for pos in holdings:
                st.props[pos] = type(st.props[pos])()
            where = "The Bank"
        ply.cash = 0
        self.announce(ply.name,
                      ["YOU ARE OUT OF THE GAME!",
                       f"The cash left goes to {where}."])

    # ------------------------------------------------------------------
    # Turn
    # ------------------------------------------------------------------

    def play_turn(self) -> None:
        st = self.state
        who = st.current
        ply = st.players[who]
        if ply.bankrupt:
            return

        self.cue("turn_end")
        # No interest is charged here.  The routine that says "You have been
        # charged interest" (CHN load 0x8268) has exactly two callers, both
        # in the flows where a property changes hands between players, and
        # nothing in a turn loop calls it: interest falls due when a mortgage
        # is redeemed or a mortgaged property is traded, not every time its
        # owner's turn comes round.  Charging it per turn was this port's
        # invention and it bled players dry.
        if not self.settle_loan(who):
            return

        st.doubles_run = 0
        st.again = False
        while True:
            if ply.in_jail:
                if not self.jail_turn(who):
                    return
                if ply.in_jail:
                    return

            a, b = self.roll_dice()
            st.dice = (a, b)
            doubles = a == b

            if doubles:
                st.doubles_run += 1
                if st.doubles_run == 3:
                    # send_to_jail writes "GO DIRECTLY TO JAIL!" and plays
                    # the descent, the same as every other jail path.
                    self.cue("doubles")
                    self.send_to_jail(who)
                    return
            else:
                st.doubles_run = 0

            self.move_by(who, a + b)
            if ply.bankrupt:
                return
            if not doubles:
                return
            # No panel here: there is no "Doubles" string anywhere in the
            # program, and no capture shows one.  The only sign of a repeat
            # is the board's own title, which the next roll draws.
            st.again = True

    def board_frame(self, message: list[str] | None = None,
                    override: dict[int, int] | None = None,
                    hide: "set[int] | tuple[int, ...]" = (),
                    tumble: int | None = None):
        """The board as the original draws it: CGA 320x200 graphics.

        Returns None when MONOGRAF.GRA is not available, in which case callers
        fall back to the text-mode board.  Used for the graphical front end and
        by tools/verify_graphics.py.
        """
        if self.board_art is None:
            return None
        st = self.state
        frame = graphics.BoardScreen(self.board_art)
        seats = [(p.name, p.cash, (override or {}).get(i, p.position),
                  p.in_jail and (override or {}).get(i) is None)
                 for i, p in enumerate(st.players)]
        frame.draw(self.board_title(), message or [], seats,
                   dice=st.dice if st.dice != (0, 0) else None,
                   hide=hide, tumble=tumble)
        return frame

    def move_frames(self, who: int, start: int, steps: int):
        """Board frames for a token travelling `steps` squares, then blinking.

        Yields (frame, milliseconds).  The graphical front end plays these; the
        terminal shows the endpoints only, since it cannot switch video modes.
        Kept as a generator so the animation can be tested without a display.
        """
        path = graphics.move_path(start, steps)
        for square in path:
            frame = self.board_frame(override={who: square})
            if frame is None:
                return
            yield frame, graphics.STEP_MS
        # The blink happens on the destination square, so the override has to
        # persist past the last travel frame -- the caller may not have moved
        # the player yet.
        landed = {who: path[-1]}
        for _ in range(graphics.BLINK_CYCLES):
            yield self.board_frame(override=landed), graphics.BLINK_ON_MS
            yield (self.board_frame(override=landed, hide={who}),
                   graphics.BLINK_OFF_MS)

    def show_board(self, message: list[str] | None = None) -> None:
        """Draw the board for the terminal.

        The original switches video modes here; a terminal cannot, so the
        text-mode board stands in.  board_frame() gives the real thing.
        """
        screens.draw_board(self.scr, self.state)
        # A message is either a plain line, stacked from MESSAGE_ROW, or a
        # placed run (col, row, text[, colour]) for the things the original
        # puts at a fixed spot -- the jail prompt above all.  The terminal
        # board is a stand-in, so placed runs are laid out relative to each
        # other rather than at their true columns; board_frame() draws them
        # where they actually belong.
        rows: dict[int, dict[int, str]] = {}
        for n, line in enumerate(message or []):
            if isinstance(line, tuple):
                rows.setdefault(line[1], {})[line[0]] = line[2]
            elif line:
                rows.setdefault(graphics.MESSAGE_ROW + n,
                                {})[graphics.TEXT_LEFT] = line
        base = min(rows) if rows else graphics.MESSAGE_ROW
        for row, runs in sorted(rows.items()):
            text = ""
            for col in sorted(runs):
                text = text.ljust(col - graphics.TEXT_LEFT) + runs[col]
            self.scr.write_at(58, 3 + row - base, text[:22], WHITE, BLACK)
        self._show()

    def roll_dice(self) -> tuple[int, int]:
        """Roll, with the beeps the original plays while the dice tumble."""
        st = self.state
        # The board carries no message and no prompt while it waits.  The
        # original's only text here is the title row, which board_frame draws
        # already, and its dice stay on screen showing the previous values --
        # there is no "press a key to roll" string anywhere in the program.
        self.show_board()

        # Measured, not read out of the code: the dice start tumbling the
        # moment the turn comes round and keep going until a key arrives --
        # a run that pressed nothing for twenty seconds rattled for all
        # twenty.  So the wait for the key *is* the roll, and how long a
        # player holds it decides what they throw.
        if self.animating and self.term.can_poll():
            self.tumble(st.current)
        else:
            # Nothing to poll and nothing to draw: spend the generator by the
            # bounded count so a scripted game stays reproducible.
            self.wait_key()
            self.tumble_draws(sound.ROLL_FRAMES)
            self.roll_animation(st.current)

        # Drawn after the tumble, as the original does.
        a, b = self.rng.die(), self.rng.die()
        st.dice = (a, b)
        # No roll-result text: the original never prints one.  Its only
        # "rolled" messages are the jail counter and utility rent, and the
        # dice faces themselves are the readout.
        self.show_board()
        return a, b

    # Each tumble frame picks new art for both dice and beeps twice, and every
    # one of those is a Random call.  Measured under an instrumented DOSBox,
    # which attributed each draw to its call site:
    #
    #   Random(8)    CHN 0x28A8  the first die's art  (8 drawings, 636b each)
    #   Random(2500) CHN 0x2228  the beep, as `for i := 1 to 3 do Random(i*2500)`
    #   Random(5000)   "
    #   Random(7500)   "
    #   Random(8)    CHN 0x28D4  the second die's art
    #   Random(2500) ...         and its beep
    #   Random(5000)
    #   Random(7500)
    #
    # Eight draws a frame, then two for the dice themselves.  A real turn
    # measured 258 draws -- 32 frames times eight, plus two -- and turns of
    # other lengths came out at exactly eight per extra frame.  That is also
    # why the original looks non-reproducible: its tumble runs until a key is
    # pressed, so a slower hand spends more of the sequence before the dice
    # are taken.
    TUMBLE_DRAWS_PER_FRAME = 8

    def tumble_frame(self) -> list[list[int]]:
        """One animation frame: each cube's pose, and the clicks it makes.

        The draw order is the original's -- Random(8) picks the drawing, then
        Random(i*2500) three times gives the tones -- so spending the
        generator and making the sound are the same act.
        """
        bursts = []
        for _die in (0, 1):
            self.rng.random(8)                          # which cube drawing
            bursts.append([self.rng.random(i * sound.RATTLE_RANGE)
                           for i in (1, 2, 3)])
        return bursts

    def tumble_draws(self, frames: int) -> None:
        """Spend the generator exactly as the tumble animation does."""
        for _ in range(frames):
            self.tumble_frame()

    def tumble(self, who: int) -> None:
        """Spin the dice until the player presses a key.

        Each frame is two cubes, and each cube is three random clicks about
        1.2 ms long followed by silence out to 41.5 ms -- the burst period
        measured off the 8253 with MONO_LOGIO.  The clicks are handed to the
        speaker a third of a second at a time because the backend plays
        asynchronously and would drop most of them one burst at a time.
        """
        import time

        pending: list[tuple[int, int]] = []
        queued = 0.0
        i = 0
        while not self.term.key_ready():
            for freqs in self.tumble_frame():
                burst = sound.rattle_burst(freqs)
                pending += burst
                queued += sum(ms for _hz, ms in burst)
            if queued >= sound.RATTLE_CHUNK_MS:
                self.emit_tones(pending)
                pending, queued = [], 0.0
            phase = (i * 2 * sound.RATTLE_PERIOD_MS) // graphics.TUMBLE_HOLD_MS
            # Nothing but the dice moves during a roll: the piece is left
            # alone until the chime that follows it.
            frame = self.board_frame(tumble=int(phase))
            self._emit_board(frame, int(2 * sound.RATTLE_PERIOD_MS))
            self._show()
            time.sleep(2 * sound.RATTLE_PERIOD_MS / 1000)
            i += 1
        self.term.read_key()

    @property
    def animating(self) -> bool:
        """Whether anything will actually consume animation frames.

        Building a board frame blits the whole 123x123 figure, so a headless
        run -- the test suite drives thousands of turns -- must not pay for
        frames nobody will look at.
        """
        return bool(getattr(self.term, "_raw_ok", False))

    def roll_animation(self, who: int) -> None:
        """The token flickers in place while the dice settle.

        CHN 0x23C7 runs `for i := 1 to 10`, redrawing the token through three
        frames of art with a beep and a 40 ms pause on each -- so the piece
        flashes rather than the dice tumbling.  The dice faces never change.
        """
        import time

        if not self.animating:
            return
        for frame, ms in self.roll_frames(who):
            if frame is not None:
                self._emit_board(frame, ms)
            time.sleep(ms / 1000)

    def roll_frames(self, who: int):
        """Board frames for the roll, as (frame, milliseconds).

        Two things happen at once, both measured from the original: the dice
        tumble as blank cubes with no pips, and the rolling player's token
        flickers.  The pipped faces only appear once the tumble stops.
        """
        for i in range(self.roll_cycles * sound.RATTLE_SLOTS):
            hidden = {who} if i % 2 else ()
            # The token flickers once per frame, but a die holds its
            # orientation longer, so the pose runs off elapsed time.
            phase = (i * sound.FRAME_MS) // graphics.TUMBLE_HOLD_MS
            yield (self.board_frame(hide=hidden, tumble=phase),
                   sound.FRAME_MS)

    def _emit_board(self, frame, ms: int) -> None:
        """Hook: the recorder overrides this to capture animation frames."""

    def emit_tones(self, sequence: list[tuple[int, int]]) -> None:
        """Hook: play a raw tone sequence, or capture it when recording.

        The tumble is generated rather than looked up, so it cannot go
        through cue(); this is how a recording still hears the dice.
        """
        self.speaker.play(sequence)

    def move_by(self, who: int, steps: int) -> None:
        st = self.state
        ply = st.players[who]
        # The chime between the dice stopping and the piece setting off,
        # with the piece flashing under it.  Measured across three turns: the
        # 2002/3005/2501 triplet runs right up to the first step chirp -- it
        # ended at 174.540 s and the chirp began at 174.541 s -- and a 59.92
        # fps capture shows the piece toggling only here, never during the
        # tumble itself.
        self.cue("landing")
        self.flash_piece(who)
        start = ply.position
        ply.position = (start + steps) % 40
        # animate_move pays the salary as the piece crosses GO.  Paying it
        # here, after the walk, put the money on screen a second too early.
        self.animate_move(who, start, steps)
        self.resolve_square(who, st.dice[0] + st.dice[1])

    def animate_move(self, who: int, start: int, steps: int,
                     pay_go: bool = True) -> None:
        """Walk the token to its square, then blink it, as the original does.

        In a terminal this redraws the text board a square at a time; the
        pixel-accurate version is what move_frames() produces.
        """
        import time

        if steps <= 0:
            return
        if not self.animating:
            self.state.players[who].position = (start + steps) % 40
            return
        for square in graphics.move_path(start, steps):
            saved = self.state.players[who].position
            self.state.players[who].position = square
            self.show_board()
            self.state.players[who].position = saved
            # A chirp per square; a corner chimes instead, and the piece
            # waits out the whole chime before taking its ordinary step
            # delay -- measured, and the reason a corner feels like a pause.
            corner = square in data.CORNERS
            self.cue("corner" if corner else "step")
            if corner:
                time.sleep(graphics.CORNER_MS / 1000)
                # Passing GO is paid for here, on the square, once the chime
                # has finished -- not lumped in when the move ends.
                if pay_go and square == 0 and square != start:
                    self.count_cash(who, data.GO_SALARY)
            time.sleep(graphics.STEP_MS / 1000)
        self.state.players[who].position = (start + steps) % 40

    def flash_piece(self, who: int) -> None:
        """Blink the piece where it stands, under the post-roll chime."""
        import time

        if not self.animating:
            return
        for i in range(graphics.FLASH_TOGGLES):
            if i % 2:
                self._show_hiding(who)
            else:
                self.show_board()
            time.sleep(graphics.FLASH_TOGGLE_MS / 1000)
        self.show_board()

    def advance_flash(self, who: int) -> None:
        """The piece flashes where it stands before a card moves it.

        Measured: ten cycles of three blits with a beep on each -- 2002,
        3005 and 2501 Hz, about 37 ms apiece, 1223 ms in all -- and only
        when that finishes does the piece start walking to the new square.
        Teleporting it silently, which this port used to do, skips both.
        """
        import time

        self.cue("landing")
        if not self.animating:
            return
        st = self.state
        for i in range(graphics.ADVANCE_BLITS):
            saved = st.players[who].position
            self.show_board() if i % 2 == 0 else self._show_hiding(who)
            st.players[who].position = saved
            time.sleep(graphics.ADVANCE_BLIT_MS / 1000)
        self.show_board()

    def _show_hiding(self, who: int) -> None:
        """One blit of the flash with the piece lifted off the board."""
        st = self.state
        saved = st.players[who].position
        st.players[who].position = -1
        try:
            self.show_board()
        finally:
            st.players[who].position = saved

    def send_to_jail(self, who: int) -> None:
        """Move the piece to jail, announce it, and play the descent.

        The routine at CHN load 0x52E5 does all three, whichever way the
        player got there: it places the piece, blanks the message line,
        writes "GO DIRECTLY TO JAIL!" on the board, sweeps 1000 Hz down to
        200, and waits.  Every jail path goes through it, so the message
        belongs here rather than at one of the call sites.
        """
        ply = self.state.players[who]
        ply.position = data.JAIL
        ply.in_jail = True
        ply.jail_turns = 0
        self.state.doubles_run = 0
        # The message goes on the board, not into a text panel, and no key
        # is pressed: the routine writes it into the board's message area,
        # plays the descent and carries on (CHN load 0x52E5, captured).
        self.cue("jail")
        self.show_board(["GO DIRECTLY TO JAIL!"])
        if self.animating:
            import time
            time.sleep(sum(d for _hz, d in sound.CUES["jail"].tones) / 1000)

    # ------------------------------------------------------------------
    # Landing
    # ------------------------------------------------------------------

    def resolve_square(self, who: int, dice_total: int) -> None:
        st = self.state
        ply = st.players[who]
        pos = ply.position
        sq = data.PLACE[pos]

        # The piece flashes where it stops while the board names the square,
        # under the 2002/3005/2501 chime -- about 2.2 s.  The note that used
        # to sit here, that the original is silent on landing, was wrong: it
        # was read off the landing routine at 0x6620, which indeed makes no
        # sound, while the chime comes from the flash loop at 0x5143.
        self.cue("landing")
        self.announce(ply.name, ["You have landed on", sq.name],
                      deed=pos if sq.ownable else None)

        if sq.ownable:
            self.resolve_property(who, pos, dice_total)
        elif pos == data.GO_TO_JAIL:
            # send_to_jail announces this now.
            self.send_to_jail(who)
        elif pos == data.INCOME_TAX:
            self.income_tax(who)
        elif pos == data.LUXURY_TAX:
            self.announce(ply.name, ["LUXURY TAX", "Pay $75."])
            self.pay(who, data.LUXURY_TAX_AMOUNT)
        elif pos in data.CHANCE_SQUARES:
            self.draw_card(who, "CHANCE", cards.CHANCE, st.draw_chance())
        elif pos in data.CHEST_SQUARES:
            self.draw_card(who, "COMMUNITY CHEST", cards.COMMUNITY_CHEST,
                           st.draw_chest())
        else:
            self.business_or_go(who)

    def resolve_property(self, who: int, pos: int, dice_total: int) -> None:
        st = self.state
        ply = st.players[who]
        owner = st.props[pos].owner
        sq = data.PLACE[pos]

        if owner == BANK:
            self.offer_purchase(who, pos)
            return
        if owner == who:
            self.announce(ply.name, [f"You own {sq.name}."], deed=pos)
            self.business_or_go(who)
            return
        if st.props[pos].mortgaged:
            self.announce(ply.name,
                          [f"{st.players[owner].name} owns {sq.name}",
                           "but it is mortgaged.  No charge."], deed=pos)
            self.business_or_go(who)
            return

        # Wording and line order follow the captures the screens were
        # measured against; see tools/compare_screens.py.
        rent = rules.rent_due(st, pos, dice_total)
        # No full stop: the capture reads "alice owns St. James Place".
        lines = [f"{st.players[owner].name} owns {sq.name}"]
        if sq.kind == data.RAILROAD:
            n = rules.railroads_owned(st, owner)
            if n > 1:
                lines.append(f"and owns a total of {n} railroads.")
            lines.append(f"Your rent is ${rent}.")
        elif sq.kind == data.UTILITY:
            n = rules.utilities_owned(st, owner)
            if n >= 2:
                lines.append("and owns the other utility too.")
                lines.append(f"10 times dice roll of {dice_total}")
            else:
                lines.append(f"You had rolled a {dice_total} so")
            lines.append(f"your rent is ${rent}.")
        else:
            if st.props[pos].houses == 0 and rules.owns_group(st, owner,
                                                              sq.group):
                # Just the one line.  A capture of this exact case -- "alice
                # owns St. James Place / and the entire color group. / Your
                # rent is $28." -- shows no DOUBLED!; that string lives in
                # the overlay for the card that charges double railroad rent.
                lines.append("and the entire color group.")
            lines.append(f"Your rent is ${rent}.")

        self.notice(f"{ply.name}'s turn", lines, deed=pos)
        if self.pay(who, rent, owner):
            self.business_or_go(who)

    def offer_purchase(self, who: int, pos: int) -> None:
        st = self.state
        ply = st.players[who]
        sq = data.PLACE[pos]
        while True:
            choice = self.ask(
                ply.name,
                [f"{sq.name} isn't owned.", ""],
                ["Want to ~Purchase it from the bank?",
                 "     or ~Auction it off?",
                 "do some ~Business first?",
                 "     or ~Go on with the game?"],
                deed=pos)
            if choice == "p":
                if ply.cash < sq.cost:
                    self.invalid([f"You can't afford $ {sq.cost}."])
                    continue
                self.count_cash(who, -sq.cost)
                st.props[pos].owner = who
                self.announce(ply.name, [f"{sq.name} purchased."], deed=pos)
                self.business_or_go(who)
                return
            if choice == "a":
                self.auction(pos)
                return
            if choice == "b":
                self.business_menu()
                continue
            return

    def auction(self, pos: int) -> None:
        """Faithful to the original: the humans run the auction, the program
        only records who won and for how much."""
        st = self.state
        sq = data.PLACE[pos]
        # The original asks once and takes the name straight after the last
        # line -- there is no "Buyer's name?" label anywhere in the binary.
        who = self._ask_player([sq.name, "Have the banker conduct an auction",
                                "and then give me the buyer's name."])
        if who is None:
            return

        price = self.ask_number("Auction",
                                [f"How much did {st.players[who].name} bid"],
                                f"for {sq.name}?  $ ", 0, 100000, gap=False)
        if price is None:
            return
        if st.players[who].cash < price:
            self.announce("Auction", [f"{st.players[who].name} can't afford that."])
            return
        self.count_cash(who, -price)
        st.props[pos].owner = who
        self.cue("auction")
        # The routine's own closing string is " purchased." (CHN 0xA5AF) --
        # the same line a bank purchase prints.  "sold at auction to ..." was
        # invented.
        self.announce("Auction", [f"{sq.name} purchased."], deed=pos)

    # ------------------------------------------------------------------
    # Cards
    # ------------------------------------------------------------------

    def draw_card(self, who: int, deck_name: str,
                  deck: tuple[cards.Card, ...], index: int) -> None:
        card = deck[index]
        self.announce(deck_name, _wrap(card.text, 34))
        self.apply_card(who, card)

    def apply_card(self, who: int, card: cards.Card) -> None:
        st = self.state
        ply = st.players[who]
        act = card.action

        if act == cards.COLLECT:
            self.receive(who, card.amount)
        elif act == cards.PAY:
            self.pay(who, card.amount)
        elif act == cards.COLLECT_EACH:
            total = 0
            for other in st.active:
                if other != who and self.pay(other, card.amount, who):
                    total += 0  # pay() already credited the collector
        elif act == cards.PAY_EACH:
            for other in st.active:
                if other != who:
                    # Owing every other player at once is the one debt the
                    # bank will bridge rather than force a sale for.
                    if not self.pay(who, card.amount, other, allow_loan=True):
                        return
        elif act in (cards.ADVANCE, cards.ADVANCE_NO_GO):
            target = card.target
            steps = (target - ply.position) % 40
            self.advance_flash(who)
            start = ply.position
            ply.position = target
            # The piece walks the rest of the way, so the corner chime and
            # the salary happen where they belong rather than being skipped.
            self.animate_move(who, start, steps,
                              pay_go=act == cards.ADVANCE)
            self.resolve_square(who, sum(st.dice))
        elif act == cards.BACK:
            ply.position = (ply.position - card.target) % 40
            self.resolve_square(who, sum(st.dice))
        elif act == cards.GOTO_JAIL:
            self.send_to_jail(who)
        elif act == cards.JAIL_CARD:
            ply.jail_cards += 1
        elif act == cards.NEAREST_RAILROAD:
            ply.position = cards.nearest(ply.position, data.RAILROAD_SQUARES)
            self._nearest_charge(who, doubled=True)
        elif act == cards.NEAREST_UTILITY:
            ply.position = cards.nearest(ply.position, data.UTILITY_SQUARES)
            self._nearest_charge(who, ten_times=True)
        elif act == cards.REPAIRS:
            bill = rules.repair_bill(st, who, card.amount, card.target)
            self.announce(ply.name, [f"Your repairs were $ {bill}."])
            self.pay(who, bill)

    def _nearest_charge(self, who: int, doubled: bool = False,
                        ten_times: bool = False) -> None:
        st = self.state
        ply = st.players[who]
        pos = ply.position
        owner = st.props[pos].owner
        if owner == BANK:
            self.offer_purchase(who, pos)
            return
        if owner == who or st.props[pos].mortgaged:
            self.business_or_go(who)
            return
        roll = self.rng.die() + self.rng.die()
        # Rent is not a "press any key" beat: the amount goes up, the money
        # moves, and the Business/Go on prompt follows.
        if ten_times:
            rent = roll * 10
            self.notice(f"{ply.name}'s turn", [f"You had rolled a {roll}",
                                               f"10 times dice roll of {roll}",
                                               f"your rent is $ {rent}."],
                        deed=pos)
        else:
            rent = rules.rent_due(st, pos, roll) * (2 if doubled else 1)
            self.notice(f"{ply.name}'s turn",
                        [f"Your rent is $ {rent}", "  DOUBLED!"], deed=pos)
        if self.pay(who, rent, owner):
            self.business_or_go(who)

    # ------------------------------------------------------------------
    # Taxes, jail, interest
    # ------------------------------------------------------------------

    def income_tax(self, who: int) -> None:
        st = self.state
        ply = st.players[who]
        calc = rules.calculated_income_tax(st, who)
        choice = self.ask(ply.name,
                          ["INCOME TAX", "Do you choose to pay"],
                          ["   a ~Flat rate of $200?",
                           "  or ~Calculated 10% tax?"])
        flat = choice == "f"
        amount = data.INCOME_TAX_FLAT if flat else calc

        if calc == data.INCOME_TAX_FLAT:
            verdict = ["Either way turns out",
                       "to be exactly $200."]
        elif flat and calc < data.INCOME_TAX_FLAT:
            verdict = ["Too bad.  Calculating your tax",
                       f"would have been only $ {calc}."]
        elif flat:
            verdict = ["Smart move.  Calculating your tax",
                       f"would have cost you $ {calc}."]
        elif calc > data.INCOME_TAX_FLAT:
            verdict = ["Bad choice.  This is",
                       f"costing you $ {calc}."]
        else:
            verdict = ["Wise choice.  The total",
                       f"calculation is only $ {calc}."]

        self.announce("INCOME TAX", verdict)
        self.pay(who, amount)

    def jail_turn(self, who: int) -> bool:
        """Returns False if the turn ends here."""
        st = self.state
        ply = st.players[who]
        # On the board, not in a panel.  Captured from a game loaded straight
        # into jail: "You are in JAIL." at column 19 row 5 and the options at
        # rows 7 and 8, left-aligned, hot keys in magenta against cyan words.
        # Routing this through ask() put it in the blue message panel, which
        # is a screen the original never shows here.
        choice = self.ask_on_board(graphics.jail_prompt(bool(ply.jail_cards)),
                                   "pr" + ("c" if ply.jail_cards else ""))
        if choice == "p":
            if not self.pay(who, data.JAIL_FINE):
                return False
            ply.in_jail = False
            return True
        if choice == "c" and ply.jail_cards:
            ply.jail_cards -= 1
            ply.in_jail = False
            return True

        # The count is of rolls taken, not of turns spent in jail.  Counting
        # visits and testing before the prompt puts the forced payment on the
        # turn *after* the third roll rather than on the same one.
        ply.jail_turns += 1

        # The same tumbling dice as any other roll.  This used to take two
        # numbers straight off the generator, so a player who chose Roll saw
        # no dice at all: the key they pressed answered the prompt and the
        # turn was over in the same instant.  The thrown faces then stand for
        # a second -- Delay(1000) at CHN load 0xE1BB -- before the throw is
        # even looked at.
        a, b = self.roll_dice()
        self.hold(graphics.JAIL_ROLL_PAUSE_MS)
        if a == b:
            # Nothing is said: CHN load 0xE1CC sets the got-out flag, zeroes
            # the roll count and goes straight to the move.  "Doubles - N and
            # N. / You are out." was this port's invention -- neither string
            # exists in the program.
            ply.in_jail = False
            ply.jail_turns = 0
            self.move_by(who, a + b)
            if ply.bankrupt:
                return False
            # And the throw still earns another roll, like any other double.
            # The advance-player test at CHN load 0xE538 only moves on when
            # the doubles counter is zero, and leaving jail this way sets it
            # to one.  Captured: alice rolls her way out without paying,
            # walks to Kentucky Avenue under "alice's turn", and the board is
            # retitled "alice again" for the roll that follows -- then again
            # for the one after that.  This port ended the turn instead.
            st.doubles_run = 1
            st.again = True
            return True

        if ply.jail_turns >= 3:
            self.jail_fine_due(who, a + b)
            return False

        # A failed roll that is not the third ends the turn with nothing said.
        # Captured from a game loaded in jail: prompt, tumbling dice, the
        # thrown faces left on the board, and then the next player's title --
        # no message and no Business/Go on prompt.  The routine agrees, and
        # returns at CHN load 0xE522 without waiting for a key.  What was
        # missing was the roll itself, not a screen after it.
        return False

    def jail_fine_due(self, who: int, steps: int) -> None:
        """The third roll has failed, so the $50 is no longer a choice.

        Disassembled at CHN load 0xE20D.  The two lines go on the board, not
        into a panel, and nothing waits for a key:

            gotoxy(19, 7); write('You have rolled 3')
            gotoxy(19, 8); write('times and must pay.')
            if sound then Sound(440);
            Delay(300); NoSound; Delay(1000)
            gotoxy(19, 7); write('                 ')     { 17 blanks }
            gotoxy(19, 8); write('                   ')   { 19 blanks }
            Key := 'P'                                    { forced }

        The blanking strings are exactly as long as the lines they cover,
        which is what shows they are wiped rather than scrolled away.  The
        forced 'P' then runs the ordinary Pay branch at 0xE2F8, and that is
        where the other two lines live: "You must pay $50 / to get out of
        jail." belongs to its cash-short arm at 0xE325, not here.  The port
        used to show all four at once, in a panel, and wait for a keypress.
        """
        st = self.state
        ply = st.players[who]
        self.cue("jail_third")
        self.show_board(["You have rolled 3", "times and must pay."])
        self.hold(graphics.JAIL_FINE_MS)
        self.show_board()
        # The cash-short arm redraws the board and says what the money is
        # for before sending the player off to raise it.
        if ply.cash < data.JAIL_FINE:
            self.show_board(["You must pay $50", "to get out of jail."])
        if not self.pay(who, data.JAIL_FINE):
            return
        ply.in_jail = False
        self.move_by(who, steps)

    def charge_mortgage_interest(self, who: int) -> None:
        """The author's recurring-interest rule."""
        st = self.state
        ply = st.players[who]
        mortgaged = [p for p in st.holdings(who) if st.props[p].mortgaged]
        if not mortgaged:
            return

        for pos in mortgaged:
            interest = rules.mortgage_interest(pos)
            principal = rules.mortgage_value(pos)
            sq = data.PLACE[pos]
            choice = self.ask(
                ply.name,
                ["You have been charged interest",
                 f"on {sq.name}",
                 "which is mortgaged.",
                 f"Your interest is $ {interest}.",
                 "",
                 "You can avoid paying the interest",
                 f"again by paying the principal of $ {principal}."],
                [f"Will you pay the ~Interest of ${interest}?",
                 f"          or the ~Principal of ${principal}?"],
                deed=pos)
            if choice == "p" and ply.cash >= principal + interest:
                self.pay(who, principal + interest)
                st.props[pos].mortgaged = False
                self.announce(ply.name, [f"{sq.name}", f"unmortgaged for $ {principal}."],
                              deed=pos)
            else:
                if choice == "p":
                    self.announce(ply.name, ["You cannot afford to pay",
                                             "the principal costs."])
                self.cue("interest")
                if not self.pay(who, interest):
                    return

    def settle_loan(self, who: int) -> bool:
        st = self.state
        ply = st.players[who]
        if ply.loan <= 0:
            return True
        owed = ply.loan
        self.announce(ply.name, ["YOU MUST PAY BACK BANK LOAN",
                                 f"OF ${owed} BEFORE YOU PROCEED."])
        ply.loan = 0
        if not self.pay(who, owed, allow_loan=False):
            return False
        self.announce(ply.name, ["You have repaid the bank loan",
                                 f"of ${owed} and now may proceed."])
        return True

    # ------------------------------------------------------------------
    # Business
    # ------------------------------------------------------------------

    BUSINESS_PROMPT = ["Want to do some ~Business?", "    or ready to ~Go on?"]

    def board_title(self) -> str:
        """What the board writes on its title row.

        A repeat roll is titled "<name> again" rather than "<name>'s turn".
        The suffix is at CHN load 0x4E88, concatenated onto the name when the
        doubles counter is above zero and the ordinary title used otherwise.

        Captured: bob's throw of doubles lands him on St. Charles under
        "bob's turn", and the board is retitled "bob again" for the repeat
        roll that follows -- so the change shows at the start of the repeat,
        which is why this reads a display flag rather than doubles_run.  The
        blue panels are unaffected: right through the repeat turn, the
        purchase and card screens still say "bob's turn".
        """
        st = self.state
        if st.again:
            return f"{st.player.name} again"
        return f"{st.player.name}'s turn"

    def jail_status(self, who: int) -> list[str]:
        """What the in-jail player is told above the Business/Go on prompt.

        Disassembled at CHN load 0xD6D7, which is the whole rule:

            if Ply[cur].inJail then begin
              write('YOU ARE IN JAIL!');
              if doubles > 0 then write('You lose your double roll turn.');
              doubles := 0
            end else write('You are on ', ...)

        So the second line is not part of the status: it is shown only when
        the run of doubles is still standing -- you had another roll coming
        and jail has taken it -- and drawing the status clears that run
        whether or not the line appeared.  The port printed it to everyone in
        jail, every turn, including players who had never rolled a double.
        DS:0x391F is the doubles counter: 0x29AB increments it when the two
        dice match and zeroes it when they do not, and 0x3A73 sends a player
        to jail when it reaches three.
        """
        st = self.state
        lines = ["YOU ARE IN JAIL!"]
        if st.doubles_run > 0:
            lines.append("You lose your double roll turn.")
        st.doubles_run = 0
        return lines

    def business_or_go(self, who: int) -> None:
        """The green overlay prompt, drawn over whatever the panel already says."""
        st = self.state
        pos = st.players[who].position
        screens.draw_turn_screen(
            self.scr, st, f"{st.players[who].name}'s turn",
            # Square 10 is named "just visiting..." in the table, which is
            # what a jailed player used to be told they were doing.  The
            # original says they are in jail (captured: "YOU ARE IN JAIL!"
            # above the same Business/Go on prompt).
            self.jail_status(who) if st.players[who].in_jail
            else [f"You are on {data.PLACE[pos].name}."],
            None, deed=pos if data.PLACE[pos].ownable else None)
        screens.prompt_panel(self.scr, self.BUSINESS_PROMPT)
        self._show()
        if self.wait_key("bg") == "b":
            self.business_menu()

    def business_menu(self, raising: bool = False) -> None:
        st = self.state
        who = st.current
        ply = st.players[who]
        self.in_business = True
        try:
            self._business_loop(who, ply, raising)
        finally:
            self.in_business = False

    def _business_loop(self, who: int, ply, raising: bool) -> None:
        st = self.state
        while True:
            options = screens.BUSINESS_OPTIONS
            pos = ply.position
            screens.draw_turn_screen(
                self.scr, st, "", [],
                None, deed=pos if data.PLACE[pos].ownable else None)
            screens.business_panel(
                self.scr, f"{ply.name} on {data.PLACE[pos].name}.", options)
            self._show()
            choice = self.wait_key(
                "".join(screens.hotkey_of(o) for o in options))
            if choice == "g":
                return
            if choice == "t":
                self.show_deed()
            elif choice == "m":
                self.mortgage_flow()
            elif choice == "u":
                self.unmortgage_flow()
            elif choice == "h":
                self.build_flow()
            elif choice == "r":
                self.return_flow()
            elif choice == "s":
                self.sell_flow()
            elif choice == "b":
                self.buy_flow()
            if raising and ply.cash > 0:
                return

    def _pick_property(self, prompt: str, owned_by: int | None,
                       predicate=None, nothing: str | None = None) -> int | None:
        """The original's shared property prompt (CHN 0x7A60).

        It takes a mode -- 0 title deed, 1 sell, 2 mortgage, 3 unmortgage,
        4 buy -- and each mode carries two phrases: the tail of "property
        to ..." in the prompt and the tail of "There's nothing ..." for when
        nothing qualifies.  Both sets are inline at 0x7A97-0x7C58.

        Measured against the real program: the eligible short names are listed
        in a five-row block before the question, and the empty case is caught
        *before* anything is asked.  Prompting for a name with no list, which
        this used to do, is not what the original shows.
        """
        st = self.state
        eligible = [p for p in range(len(data.PLACE))
                    if data.PLACE[p].short
                    and (owned_by is None or st.props[p].owner == owned_by)
                    and (predicate is None or predicate(p))]
        if nothing is not None and not eligible:
            self.invalid([f"There's nothing {nothing}"])
            return None
        lines = ["Give me the short name of the", prompt, ""]
        lines += data.short_name_rows(eligible)
        panel = self._panel(st.player.name, lines + ["Which? "])
        screens.paint_short_names(self.scr, panel, eligible, 3)
        self._show()
        text = self.term.read_line(self.scr, panel[0] + 3 + len("Which? "),
                                   panel[1] + 3 + len(lines), 8,
                                   (1 << 4) | WHITE)
        if not text:
            return None
        pos = data.find_by_short_name(text)
        if pos is None:
            self.invalid([f"There's nothing named {text}."])
            return None
        if owned_by is not None and st.props[pos].owner != owned_by:
            self.invalid([f"You don't own {data.PLACE[pos].name}."])
            return None
        if predicate and not predicate(pos):
            self.invalid([f"Can't do that with {data.PLACE[pos].name}."])
            return None
        return pos

    def show_deed(self) -> None:
        pos = self._pick_property("Title Deed Card you want to see.", None)
        if pos is not None:
            self.announce(self.state.player.name, [data.PLACE[pos].name],
                          deed=pos)

    def mortgage_flow(self) -> None:
        st = self.state
        who = st.current
        pos = self._pick_property("property to mortgage.", who,
                                  lambda p: not st.props[p].mortgaged
                                  and st.props[p].houses == 0,
                                  nothing="to mortgage.")
        if pos is None:
            return
        amount = rules.mortgage_value(pos)
        st.props[pos].mortgaged = True
        self.receive(who, amount)
        self.announce(st.players[who].name,
                      [data.PLACE[pos].name, f"mortgaged for $ {amount}."],
                      deed=pos)

    def unmortgage_flow(self) -> None:
        st = self.state
        who = st.current
        pos = self._pick_property("property to unmortgage.", who,
                                  lambda p: st.props[p].mortgaged,
                                  nothing="to unmortgage.")
        if pos is None:
            return
        cost = rules.unmortgage_cost(pos)
        if st.players[who].cash < cost:
            self.invalid([f"You can't afford $ {cost}."])
            return
        self.count_cash(who, -cost)
        st.props[pos].mortgaged = False
        self.announce(st.players[who].name,
                      [data.PLACE[pos].name, f"unmortgaged for $ {cost}."],
                      deed=pos)

    def _pick_group(self, prompt: str,
                    groups: list[int] | None = None) -> int | None:
        """Ask for a colour group by listing them and taking one keypress.

        The original does not read a typed name here: it upper-cases a single
        key and tests it against L/C/D/O/R/Y/G/B/N, echoing the group's name
        back.  N is the way out.

        The list itself is not the fixed eight.  The loop at CHN 0x9154 walks
        groups 1..8 and skips any the player does not own outright, or that
        carries a mortgage, so only the groups you can actually act on are
        offered.  Each line is seven spaces -- the last two of them a swatch
        in the group's own colours -- then the name with its first letter in
        the hot-key colour, and the way out reads "    or None... changed my
        mind."  Listing all eight behind a "   L  " key column, which this
        port used to do, is not what the program draws.
        """
        st = self.state
        if groups is None:
            groups = data.color_group_ids()
        keys = dict((n, k) for k, n in data.GROUP_KEYS)
        listed = [g for g in data.color_group_ids() if g in groups]
        # One eligible group is taken without asking.  CHN load 0x9078,
        # right after the counting pass and before anything is drawn:
        #
        #     if count = 1 then begin Chosen := theOnlyOne; goto done end
        #
        # Captured both ways: a player owning only the Cyan group goes from
        # the business menu straight to "Zoning Regulations allow 15", while
        # one owning Cyan and Orange is asked which.
        if len(listed) == 1:
            return listed[0]
        lines = ["Tell me the color group", prompt, ""]
        for g in listed:
            lines.append(" " * data.GROUP_ROW_INDENT
                         + "~" + data.COLOR_GROUPS[g].name)
        lines.append(f"    or ~{data.GROUP_CANCEL_KEY}one... changed my mind.")

        panel = self._panel(st.player.name, lines)
        screens.paint_group_rows(self.scr, panel, listed, 3)
        self._show()
        allowed = "".join(keys[data.COLOR_GROUPS[g].name].lower()
                          for g in listed)
        allowed += data.GROUP_CANCEL_KEY.lower()
        choice = self.wait_key(allowed)
        if choice == data.GROUP_CANCEL_KEY.lower():
            return None
        for g in listed:
            if keys[data.COLOR_GROUPS[g].name].lower() == choice:
                return g
        return None

    def build_flow(self) -> None:
        st = self.state
        who = st.current
        # Measured: pressing H with nothing to build on answers straight away,
        # without ever showing the colour-group list.  The test comes first.
        buildable = [g for g in data.color_group_ids()
                     if rules.can_build_on(st, who, g)]
        if not buildable:
            self.invalid(["You have no property to build",
                          "on.  The entire color group",
                          "must be owned and unmortgaged."])
            return
        group = self._pick_group("you wish to improve.", buildable)
        if group is None:
            return
        if not rules.can_build_on(st, who, group):
            self.invalid(["You have no property to build",
                          "on.  The entire color group",
                          "must be owned and unmortgaged."])
            return
        allowed = rules.max_units_in_group(group)
        now = rules.units_in_group(st, group)
        if now >= allowed:
            self.invalid(["That property is already fully",
                          "developed.  No more building."])
            return
        cost = rules.house_cost(group)
        name = data.COLOR_GROUPS[group].name
        # No space after the dollar sign in any of these: the deed card
        # writes "$ 100" in a column, but the prompts write "$50." against
        # the text.  Captured at rows 5-8 of the panel, column 5.
        prompt = "How many units will you buy? "
        lines = [f"Zoning Regulations allow {allowed}",
                 f"units in the {name} group.",
                 f"There are {now or 'no'} units now.",
                 f"Each unit costs ${cost}."]
        count = self.ask_number(st.players[who].name, lines,
                                prompt, 1, allowed - now)
        if not count:
            return
        total = count * cost
        if st.players[who].cash < total:
            self.invalid(["You can't afford that."])
            return
        # The total appears two rows under the question, on the screen that
        # is already up -- not in a fresh panel with a "<Press Any Key>",
        # which is what this port used to do.  Then the money goes, and only
        # then do the houses start going up.
        body = lines + ["", f"{prompt}{count}", "", f"That will cost ${total}."]
        self.notice(st.players[who].name, body)
        self.count_cash(who, -total)
        self.place_units(rules.distribute_units(st, group, count), body, +1)

    def place_units(self, squares: list[int], body: list[str],
                    delta: int) -> None:
        """Put up or take down one unit at a time, as the original does.

        Each pass draws the title deed of the square receiving or giving up
        the unit and plays a whole burst of the sound -- the four sweeps are
        inside the loop, not around it -- so six houses make six bursts, not
        one.  Measured off the speaker at 514 ms a house going up and 464 ms
        coming down.
        """
        st = self.state
        cue = "build" if delta > 0 else "houses_sold"
        beat = graphics.BUILD_UNIT_MS if delta > 0 else graphics.RETURN_UNIT_MS
        for pos in squares:
            st.props[pos].houses += delta
            self.notice(st.players[st.current].name, body, deed=pos)
            self.cue(cue)
            self.hold(beat)

    def return_flow(self) -> None:
        st = self.state
        who = st.current
        # As with building, the "nothing to return" answer comes before the
        # colour-group list rather than after a choice.
        holding = [g for g in data.color_group_ids()
                   if rules.units_in_group(st, g) and rules.owns_group(st, who, g)]
        if not holding:
            self.invalid(["You have no houses or", "hotels to return."])
            return
        group = self._pick_group("to return improvements.", holding)
        if group is None:
            return
        now = rules.units_in_group(st, group)
        if not now or not rules.owns_group(st, who, group):
            self.invalid(["You have no houses or", "hotels to return."])
            return
        each = rules.sale_value_per_unit(group)
        name = data.COLOR_GROUPS[group].name
        # One line, with the group's name in it -- "There are 6 units on
        # Cyan." -- not two saying "units on" and "the Cyan group."  The
        # string at CHN 0x69C6 is " units on " and the name is written
        # straight after it, in the group's own colours.
        prompt = "How many units to return? "
        lines = [f"There are {now} units on {name}.",
                 f"Each will bring ${each}."]
        count = self.ask_number(st.players[who].name, lines,
                                prompt, 1, now)
        if not count:
            return
        gain = count * each
        body = lines + ["", f"{prompt}{count}", "", f"That will bring ${gain}."]
        self.notice(st.players[who].name, body)
        self.receive(who, gain)
        self.place_units(rules.collect_units(st, group, count), body, -1)

    def _ask_player(self, lines: list[str]) -> int | None:
        """Ask for another player by name.

        The original writes "Give me the name of the / player you are selling
        / <Property> to." and takes the name after the last line -- there is
        no "Name?" label (CHN 0x890F-0x896D).
        """
        st = self.state
        panel = self._panel(st.player.name, lines)
        self._show()
        # The name is typed after the last line.  "and then give me the
        # buyer's name." nearly fills the panel, so when there is no room the
        # field drops to the next line rather than spilling past the frame.
        col = panel[0] + 4 + len(lines[-1])
        row = panel[1] + 2 + len(lines)
        if col + 12 > panel[2]:
            col, row = panel[0] + 3, row + 1
        text = self.term.read_line(self.scr, col, row, 12, (1 << 4) | WHITE)
        if not text:
            return None
        for i, p in enumerate(st.players):
            if p.name.lower() == text.lower() and not p.bankrupt:
                return i
        self.invalid([f"There's nobody named {text}."])
        return None

    def sell_flow(self) -> None:
        st = self.state
        who = st.current
        pos = self._pick_property("property to sell.", who,
                                  lambda p: st.props[p].houses == 0,
                                  nothing="to sell.")
        if pos is None:
            return
        buyer = self._ask_player(["Give me the name of the",
                                  "player you are selling",
                                  f"{data.PLACE[pos].name} to."])
        if buyer is None:
            return
        price = self.ask_number(st.players[who].name,
                                [f"What price have {st.players[buyer].name} and",
                                 "you agreed on to sell"],
                                f"{data.PLACE[pos].name}?  $ ", 0, 100000,
                                gap=False)
        if price is None:
            return
        if st.players[buyer].cash < price:
            self.invalid([f"{st.players[buyer].name} can't afford $ {price}."])
            return
        self.count_cash(buyer, -price)
        self.receive(who, price)
        st.props[pos].owner = buyer
        # The sell routine (CHN 0x888C-0x8BBD) carries no closing line: unlike
        # mortgage and unmortgage, which each print one, it simply returns to
        # the menu.  "sold to ... for $" was invented.

    def buy_flow(self) -> None:
        st = self.state
        who = st.current
        pos = self._pick_property("property to buy.", None,
                                  lambda p: st.props[p].owner not in (BANK, who)
                                  and st.props[p].houses == 0,
                                  nothing="to buy.")
        if pos is None:
            return
        seller = st.props[pos].owner
        price = self.ask_number(st.players[who].name,
                                [f"What price has {st.players[seller].name}",
                                 "quoted for you to buy"],
                                f"{data.PLACE[pos].name}?  $ ", 0, 100000,
                                gap=False)
        if price is None:
            return
        if st.players[who].cash < price:
            self.invalid([f"You can't afford $ {price}."])
            return
        self.count_cash(who, -price)
        self.receive(seller, price)
        st.props[pos].owner = who
        # As with selling, the buy routine has no closing line of its own.

    # ------------------------------------------------------------------
    # Save / load
    # ------------------------------------------------------------------

    def save_game(self) -> None:
        screens.draw_turn_screen(self.scr, self.state, "Save Game",
                                 ["The file name you use must follow DOS rules.", "",
                                  "File name? "])
        self._show()
        name = self.term.read_line(self.scr, 12, 10, 20, (1 << 4) | WHITE)
        if not name:
            return
        try:
            save.save(self.state, name)
        except OSError as exc:
            self.announce("Save Game", ["DISK WRITE ERROR", str(exc)[:34]])

    def load_game(self) -> bool:
        self.state = self.state or GameState.new_game(["-", "-"])
        screens.draw_turn_screen(self.scr, self.state, "Resume Game",
                                 ["Ready to resume a previously saved game.",
                                  "", "File name? "])
        self._show()
        name = self.term.read_line(self.scr, 12, 10, 20, (1 << 4) | WHITE)
        if not name:
            self.state = None
            return False
        try:
            self.state = save.load(name)
            return True
        except (OSError, ValueError):
            self.announce("Resume Game",
                          ["DISK READ ERROR -- Wrong file name?"])
            self.state = None
            return False

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Play until one player is left, or until the input runs out."""
        try:
            if not self.setup():
                return
            while len(self.state.active) > 1:
                self.play_turn()
                self.state.next_player()
            self.endgame()
        except Quit:
            return

    def endgame(self) -> None:
        st = self.state
        alive = st.active
        winner = st.players[alive[0]].name if alive else "Nobody"
        self.cue("winner")
        self.scr.set_attr(LIGHTGRAY, BLACK)
        self.scr.clrscr()
        screens.message_panel(
            self.scr, "",
            ["", f"{winner} is the WINNER!", "",
             "Thanks for playing Monopoly.", "", "<Press Any Key>"])
        self._show()
        self.wait_key()


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines
