/* Targeted tracing for the Monopoly port project.
 *
 * The question this exists to answer is where the 1985 program reads the
 * keyboard, and what touches its RandSeed.  Static analysis kept
 * contradicting itself and a from-scratch DOS emulator could not reach the
 * first prompt, so the instrumentation goes where the program already runs
 * correctly: inside DOSBox.
 *
 * Everything is opt-in through the environment, so an unset MONO_LOG leaves
 * the emulator behaving exactly as it did before.
 *
 *   MONO_LOG=/path/to/log     enable logging
 *   MONO_WATCH=0x1234         log writes to this guest physical address
 */

#ifndef MONOLOG_H
#define MONOLOG_H

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>

static FILE *mono_fp_ = NULL;
static int mono_ready_ = 0;

static inline FILE *mono_out(void) {
	if (!mono_ready_) {
		const char *p = getenv("MONO_LOG");
		mono_ready_ = 1;
		/* append: the header is included by several translation units,
		 * each with its own handle, and "w" would let them truncate
		 * one another */
		if (p && *p) mono_fp_ = fopen(p, "a");
	}
	return mono_fp_;
}

static inline void mono_log(const char *fmt, ...) {
	FILE *f = mono_out();
	if (!f) return;
	va_list ap;
	va_start(ap, fmt);
	vfprintf(f, fmt, ap);
	va_end(ap);
	fputc('\n', f);
	fflush(f);
}

/* Canned keyboard input.
 *
 * The program blocks in INT 16h AH=00 until a key arrives, so it cannot be
 * driven deterministically from outside -- real keystrokes land at whatever
 * moment the window manager delivers them, and the game branches on when
 * they arrive.  Feeding the keys here instead removes wall-clock time from
 * the input path entirely, and leaves the guest binary untouched.
 *
 *   MONO_KEYS=414c...   the key stream, as hex ASCII bytes
 *   MONO_RATE=64        polls of AH=01 before the next key is offered
 */

static unsigned char mono_keys_[4096];
static int mono_nkeys_ = -1;

static inline int mono_keys_len(void) {
	if (mono_nkeys_ < 0) {
		const char *p = getenv("MONO_KEYS");
		mono_nkeys_ = 0;
		if (p) {
			while (p[0] && p[1] && mono_nkeys_ < (int)sizeof(mono_keys_)) {
				char b[3];
				b[0] = p[0]; b[1] = p[1]; b[2] = 0;
				mono_keys_[mono_nkeys_++] =
					(unsigned char)strtoul(b, NULL, 16);
				p += 2;
			}
		}
	}
	return mono_nkeys_;
}

static inline unsigned mono_rate(void) {
	static int done = 0;
	static unsigned r = 64;
	if (!done) {
		const char *p = getenv("MONO_RATE");
		done = 1;
		if (p && *p) r = (unsigned)strtoul(p, NULL, 0);
		if (!r) r = 1;
	}
	return r;
}

static inline unsigned char mono_key_at(int i) {
	return mono_keys_[i % mono_nkeys_];
}

/* Logging every INT 16h poll is half a million lines a minute, and the
 * fflush on each one slows the emulator so much the game never reaches its
 * first dice roll.  Keep it behind its own switch. */
static inline int mono_log_int(void) {
	static int done = 0, on = 0;
	if (!done) { const char *p = getenv("MONO_LOGINT"); done = 1;
	             on = (p && *p && *p != '0'); }
	return on;
}

static inline unsigned long mono_watchlen(void) {
	static int done = 0;
	static unsigned long n = 4;
	if (!done) { const char *p = getenv("MONO_WATCHLEN"); done = 1;
	             if (p && *p) n = strtoul(p, NULL, 0); if (!n) n = 4; }
	return n;
}

/* Freeze the guest at a fixed point in *program* time.  Once this many
 * keys have been consumed the injector stops offering any, so the game
 * blocks in its keyboard wait and the screen goes static -- which is what
 * makes two runs comparable at the same point rather than at the same
 * wall-clock moment. */
static inline int mono_stop(void) {
	static int done = 0, n = 0;
	if (!done) { const char *p = getenv("MONO_STOP"); done = 1;
	             if (p && *p) n = (int)strtol(p, NULL, 0); }
	return n;
}

static inline unsigned long mono_watch(void) {
	static int done = 0;
	static unsigned long addr = 0;
	if (!done) {
		const char *p = getenv("MONO_WATCH");
		done = 1;
		if (p && *p) addr = strtoul(p, NULL, 0);
	}
	return addr;
}

#endif
