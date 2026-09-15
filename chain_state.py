"""Persists the Giselle/Yousuf reaction chain to disk so it survives bot
restarts. Each reaction lands after a random delay of up to an hour — long
enough that a deploy, a crash, or a systemd restart can easily land mid-wait.
Without this, that in-flight reaction is silently dropped forever."""

from __future__ import annotations

import json
from pathlib import Path

STATE_FILE = Path(__file__).parent / "chain_state.json"


def _load_all() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_all(chains: dict):
    STATE_FILE.write_text(json.dumps(chains, indent=2))


def save_chain(marc_tweet_id: str, state: dict):
    chains = _load_all()
    chains[marc_tweet_id] = state
    _save_all(chains)


def clear_chain(marc_tweet_id: str):
    chains = _load_all()
    chains.pop(marc_tweet_id, None)
    _save_all(chains)


def load_pending_chains() -> list[dict]:
    return list(_load_all().values())
