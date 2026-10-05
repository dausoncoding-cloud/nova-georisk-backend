"""
Validation endpoints — synchronous, pure-math wrappers around
app.services.validation. Given a set of observed/predicted (or
true/predicted-label) pairs, returns the full metric suite from
Docs 1/3's dual-assessment framework.
"""
from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Depends, HTTPException

from app.core.security import verify_internal_secret
from app.schemas.validation import (
    ClassificationValidationRequest,
    ClassificationValidationResponse,
    ConfusionCountsSchema,
    RegressionValidationRequest,
    RegressionValidationResponse,
)
from app.services.validation.classification_metrics import compute_classification_metrics
from app.services.validation.regression_metrics import compute_regression_metrics

router = APIRouter(prefix="/validation", tags=["Validation"], dependencies=[Depends(verify_internal_secret)])


@router.post("/regression", response_model=RegressionValidationResponse)
def validate_regression(payload: RegressionValidationRequest) -> RegressionValidationResponse:
    try:
        metrics = compute_regression_metrics(
            observed=np.array(payload.observed), predicted=np.array(payload.predicted)
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return RegressionValidationResponse(
        n=metrics.n,
        me=metrics.me,
        mbe=metrics.mbe,
        mae=metrics.mae,
        rmse=metrics.rmse,
        mape=metrics.mape,
        se=metrics.se,
        nse=metrics.nse,
        r_squared=metrics.r_squared,
        see=metrics.see,
        rrmse=metrics.rrmse,
        willmott_d=metrics.willmott_d,
        evs=metrics.evs,
        rmse_quality_label=metrics.rmse_quality_label(),
    )


@router.post("/classification", response_model=ClassificationValidationResponse)
def validate_classification(payload: ClassificationValidationRequest) -> ClassificationValidationResponse:
    try:
        metrics = compute_classification_metrics(
            y_true=np.array(payload.y_true),
            y_pred=np.array(payload.y_pred),
            y_score=np.array(payload.y_score) if payload.y_score is not None else None,
            positive_label=payload.positive_label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return ClassificationValidationResponse(
        confusion=ConfusionCountsSchema(
            tp=metrics.confusion.tp,
            tn=metrics.confusion.tn,
            fp=metrics.confusion.fp,
            fn=metrics.confusion.fn,
            n=metrics.confusion.n,
        ),
        overall_accuracy=metrics.overall_accuracy,
        precision=metrics.precision,
        recall=metrics.recall,
        specificity=metrics.specificity,
        f1_score=metrics.f1_score,
        omission_error=metrics.omission_error,
        commission_error=metrics.commission_error,
        cohens_kappa=metrics.cohens_kappa,
        kappa_label=metrics.kappa_label(),
        balanced_accuracy=metrics.balanced_accuracy,
        mcc=metrics.mcc,
        error_rate=metrics.error_rate,
        prevalence=metrics.prevalence,
        roc_auc=metrics.roc_auc,
        auc_label=metrics.auc_label(),
    )
