"""Runtime adapters for NOVA analysis engines."""

from app.platform.engines.registry import get_engine_adapter

__all__ = ["get_engine_adapter"]
