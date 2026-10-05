"""Evidence-linked quantitative delivery; no inferred scientific thresholds."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class DeliveryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ClassArea(DeliveryModel):
    product_key: str
    class_value: int
    label: str
    cells: int = Field(ge=0)
    area_m2: float = Field(ge=0)
    area_ha: float = Field(ge=0)
    area_km2: float = Field(ge=0)
    percent_of_valid: float = Field(ge=0, le=100)
    denominator_area_m2: float = Field(gt=0)
    area_method: str
    classification_basis: str
    evidence_ref: str


class QuantitativeSeries(DeliveryModel):
    product_key: str
    kind: Literal["class_area", "histogram", "observed_time_series"]
    units: str
    points: list[dict[str, Any]]
    basis: str
    evidence_refs: list[str]


class ResultAnalytics(DeliveryModel):
    schema_version: Literal["1.0"] = "1.0"
    class_areas: list[ClassArea] = Field(default_factory=list)
    series: list[QuantitativeSeries] = Field(default_factory=list)
    limitations: list[str]


class EvidenceStatement(DeliveryModel):
    text: str
    evidence_refs: list[str] = Field(min_length=1)


class ResultInterpretation(DeliveryModel):
    method: Literal["deterministic_evidence_rules_v1"] = "deterministic_evidence_rules_v1"
    findings: list[EvidenceStatement]
    recommendations: list[EvidenceStatement]
    limitations: list[str]
    independent_scientific_validation: Literal[False] = False
