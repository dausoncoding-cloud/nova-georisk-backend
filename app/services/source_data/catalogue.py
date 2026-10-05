"""Versioned, machine-readable FIRRIS source-data handoff contract."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def get_catalogue() -> dict:
    catalogue = json.loads(Path(__file__).with_name("firris_catalogue.json").read_text(encoding="utf-8"))
    profiles = catalogue["profiles"]
    if not profiles or any(not profile.get("downstream_rows") for profile in profiles.values()):
        raise RuntimeError("FIRRIS source-data catalogue is incomplete")
    return catalogue


def get_profile(category: str) -> dict:
    try:
        return get_catalogue()["profiles"][category]
    except KeyError as exc:
        raise ValueError(f"Unknown FIRRIS source-data category: {category}") from exc
