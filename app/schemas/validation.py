"""Request/response schemas for the model-validation endpoints."""
from __future__ import annotations

from pydantic import BaseModel, field_validator


class RegressionValidationRequest(BaseModel):
    observed: list[float]
    predicted: list[float]

    @field_validator("predicted")
    @classmethod
    def _same_length(cls, value: list[float], info) -> list[float]:
        observed = info.data.get("observed")
        if observed is not None and len(observed) != len(value):
            raise ValueError("observed and predicted must be the same length.")
        return value


class RegressionValidationResponse(BaseModel):
    n: int
    me: float
    mbe: float
    mae: float
    rmse: float
    mape: float
    se: float
    nse: float
    r_squared: float
    see: float
    rrmse: float
    willmott_d: float
    evs: float
    rmse_quality_label: str


class ClassificationValidationRequest(BaseModel):
    y_true: list[int]
    y_pred: list[int]
    y_score: list[float] | None = None
    positive_label: int = 1

    @field_validator("y_pred")
    @classmethod
    def _same_length(cls, value: list[int], info) -> list[int]:
        y_true = info.data.get("y_true")
        if y_true is not None and len(y_true) != len(value):
            raise ValueError("y_true and y_pred must be the same length.")
        return value


class ConfusionCountsSchema(BaseModel):
    tp: int
    tn: int
    fp: int
    fn: int
    n: int


class ClassificationValidationResponse(BaseModel):
    confusion: ConfusionCountsSchema
    overall_accuracy: float
    precision: float
    recall: float
    specificity: float
    f1_score: float
    omission_error: float
    commission_error: float
    cohens_kappa: float
    kappa_label: str
    balanced_accuracy: float
    mcc: float
    error_rate: float
    prevalence: float
    roc_auc: float | None
    auc_label: str | None
