"""Saving and resuming a game.

The 1985 version wrote its Pascal records straight to disk with BlockWrite, so
a save file was a raw image of Ply[] and Owner[] and could not survive a
recompile.  This port writes JSON instead: the same fields, but readable and
stable across versions.  The `version` key exists so an older file can be
rejected cleanly rather than loaded as nonsense.

Files land in the working directory, keeping the original's behaviour of
taking a bare name and writing beside the program.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .state import GameState, Player, PropertyState

FORMAT_VERSION = 1
SUFFIX = ".mpl"


def path_for(name: str) -> Path:
    p = Path(name)
    return p if p.suffix else p.with_suffix(SUFFIX)


def save(state: GameState, name: str) -> Path:
    target = path_for(name)
    payload = {
        "version": FORMAT_VERSION,
        "players": [asdict(p) for p in state.players],
        "props": [asdict(s) for s in state.props],
        "current": state.current,
        "dice": list(state.dice),
        "doubles_run": state.doubles_run,
        "chance_order": state.chance_order,
        "chest_order": state.chest_order,
        "chance_next": state.chance_next,
        "chest_next": state.chest_next,
        "sound": state.sound,
        "rng_seed": state.rng_seed,
    }
    target.write_text(json.dumps(payload, indent=1))
    return target


def load(name: str) -> GameState:
    source = path_for(name)
    payload = json.loads(source.read_text())
    if payload.get("version") != FORMAT_VERSION:
        raise ValueError(f"unsupported save format: {payload.get('version')!r}")

    state = GameState(
        players=[Player(**p) for p in payload["players"]],
        props=[PropertyState(**s) for s in payload["props"]],
        current=payload["current"],
        dice=tuple(payload["dice"]),
        doubles_run=payload["doubles_run"],
        chance_order=payload["chance_order"],
        chest_order=payload["chest_order"],
        chance_next=payload["chance_next"],
        chest_next=payload["chest_next"],
        sound=payload["sound"],
        rng_seed=payload["rng_seed"],
    )
    if len(state.props) != 40:
        raise ValueError("save file does not describe a 40-square board")
    return state
