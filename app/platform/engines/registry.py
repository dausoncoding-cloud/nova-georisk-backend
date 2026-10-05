"""Runtime engine adapter lookup; planned engines have no placeholder executor."""
from __future__ import annotations

from app.platform.engines.base import EngineAdapter
from app.platform.engines.firris import FIRRISEngineAdapter


_ADAPTERS: dict[str, EngineAdapter] = {"firris": FIRRISEngineAdapter()}


def get_engine_adapter(engine_key: str) -> EngineAdapter:
    try:
        return _ADAPTERS[engine_key]
    except KeyError as exc:
        raise LookupError(f"No runtime adapter is available for engine '{engine_key}'.") from exc
