"""Stable engine identifiers and seed metadata shared by migrations/tests/documentation."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EngineDefinition:
    key: str
    name: str
    description: str
    status: str
    enabled: bool
    version: str
    category: str
    route_namespace: str
    icon_identifier: str
    capabilities: tuple[str, ...]
    publicly_available: bool
    subscription_required: bool = True


ENGINE_DEFINITIONS = (
    EngineDefinition("firris", "FIRRIS", "NOVA flood mapping and risk analysis engine", "active", True, "1.0", "risk", "/api/v1/analyses", "flood", ("flood-mapping", "screening-atlas"), True),
    EngineDefinition("wras", "WRAS", "Wildfire Risk Assessment System", "planned", False, "0", "risk", "/api/v1/analyses", "wildfire", (), False),
    EngineDefinition("lucas", "LUCAS", "Land Use / Land Cover Change Analysis System", "planned", False, "0", "change", "/api/v1/lucas", "land-cover", (), False),
    EngineDefinition("hasas", "HASAS", "Habitat Suitability Analysis System", "planned", False, "0", "ecology", "/api/v1/hasas", "habitat", (), False),
    EngineDefinition("veras", "VERAS", "Vegetation Recovery Analysis System", "planned", False, "0", "ecology", "/api/v1/veras", "vegetation", (), False),
    EngineDefinition("diras", "DIRAS", "Drought Impact / Risk Analysis System", "planned", False, "0", "risk", "/api/v1/diras", "drought", (), False),
    EngineDefinition("lstas", "LSTAS", "Land Surface Temperature Analysis System", "planned", False, "0", "climate", "/api/v1/lstas", "temperature", (), False),
    EngineDefinition("wqras", "WQRAS", "Water Quality Risk / Analysis System", "planned", False, "0", "water", "/api/v1/wqras", "water-quality", (), False),
    EngineDefinition("lras", "LRAS", "Landslide Risk Assessment System", "planned", False, "0", "risk", "/api/v1/lras", "landslide", (), False),
    EngineDefinition("megis", "MEGIS", "Mineral Exploration / Geospatial Intelligence System", "planned", False, "0", "exploration", "/api/v1/analyses", "mineral", (), False),
)

ENGINE_KEYS = frozenset(item.key for item in ENGINE_DEFINITIONS)
