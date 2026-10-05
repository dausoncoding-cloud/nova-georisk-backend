"""Shared execution boundary implemented by every analysis engine."""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


ProgressCallback = Callable[[int], None]


@dataclass(frozen=True)
class EngineExecutionContext:
    task_id: uuid.UUID
    project_id: uuid.UUID
    aoi_id: uuid.UUID
    output_directory: Path
    operation: str
    products: list[str]
    parameters: dict[str, Any]
    gis_metadata: dict[str, Any]
    result_version: int
    aoi_geometry: dict[str, Any] | None = None


@dataclass(frozen=True)
class EngineExecutionOutput:
    result_type: str
    summary: dict[str, Any]
    provenance: dict[str, Any]
    output_files: dict[str, dict[str, Any]]


class EngineAdapter(ABC):
    key: str
    name: str
    version: str

    @abstractmethod
    def execute(
        self,
        context: EngineExecutionContext,
        progress_callback: ProgressCallback,
    ) -> EngineExecutionOutput:
        """Execute an analysis without depending on HTTP or ORM concerns."""

    @abstractmethod
    def contract(self) -> dict[str, Any]:
        """Return browser-safe operations and product capabilities."""
