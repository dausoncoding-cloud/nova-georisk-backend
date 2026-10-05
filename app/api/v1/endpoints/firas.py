"""
Legacy FIRRIS index calculator endpoints. Each takes already-extracted sample data
(named indicator arrays) and returns the computed composite index:
per-sample scores, the entropy-derived weights used, per-sample
classification labels, and a summary (mean/min/max/dominant class) —
the shape the frontend's results dashboard needs directly.
"""
from __future__ import annotations

from collections import Counter

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from app.core.security import verify_internal_secret
from app.core.entitlements import require_current_engine
from app.schemas.firas import (
    CapacitySubindexRequest,
    CapacitySubindexResponse,
    CompositeIndexResponse,
    CriRequest,
    FiiRequest,
    FriRequest,
    FriResponse,
    FviRequest,
    IndexSummary,
    IndicatorMatrixRequest,
)
from app.services.firas import exposure as exposure_service
from app.services.firas import hazard as hazard_service
from app.services.firas import insecurity as insecurity_service
from app.services.firas import resilience as resilience_service
from app.services.firas import risk as risk_service
from app.services.firas import vulnerability as vulnerability_service
from app.services.firas.classification import classify_series
from app.services.firas.common import CompositeIndexResult
from app.services.statistics.entropy_weight import IndicatorDirection

router = APIRouter(
    prefix="/firas",
    tags=["FIRRIS Legacy Calculators"],
    dependencies=[Depends(verify_internal_secret), Depends(require_current_engine("firris"))],
)


def _to_dataframe(indicators: dict[str, list[float]]) -> pd.DataFrame:
    return pd.DataFrame(indicators)


def _to_directions(
    directions: dict[str, str] | None,
) -> dict[str, IndicatorDirection] | None:
    if directions is None:
        return None
    return {name: IndicatorDirection(value) for name, value in directions.items()}


def _summarize(scores: pd.Series, labels: pd.Series) -> IndexSummary:
    dominant = Counter(labels).most_common(1)[0][0]
    return IndexSummary(
        mean=float(scores.mean()),
        min=float(scores.min()),
        max=float(scores.max()),
        dominant_class=dominant,
    )


def _composite_response(result: CompositeIndexResult, bands) -> CompositeIndexResponse:
    labels = classify_series(result.scores, bands)
    return CompositeIndexResponse(
        scores=result.scores.tolist(),
        weights=result.weights,
        classifications=labels.tolist(),
        summary=_summarize(result.scores, labels),
    )


@router.post("/hazard", response_model=CompositeIndexResponse)
def compute_hazard(payload: IndicatorMatrixRequest) -> CompositeIndexResponse:
    from app.services.firas.classification import HAZARD_BANDS

    data = _to_dataframe(payload.indicators)
    directions = _to_directions({k: v.value for k, v in (payload.directions or {}).items()}) if payload.directions else None
    try:
        result = hazard_service.compute_hazard_index(data, directions=directions)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _composite_response(result, HAZARD_BANDS)


@router.post("/exposure", response_model=CompositeIndexResponse)
def compute_exposure(payload: IndicatorMatrixRequest) -> CompositeIndexResponse:
    from app.services.firas.classification import GENERIC_BANDS

    data = _to_dataframe(payload.indicators)
    directions = _to_directions({k: v.value for k, v in (payload.directions or {}).items()}) if payload.directions else None
    try:
        result = exposure_service.compute_exposure_index(data, directions=directions)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _composite_response(result, GENERIC_BANDS)


@router.post("/capacity-subindex", response_model=CapacitySubindexResponse)
def compute_capacity_subindex(payload: CapacitySubindexRequest) -> CapacitySubindexResponse:
    """
    Generic entropy-weighted sub-index — used for CPC (Community
    Preparedness Capacity), EWE (Early Warning Effectiveness), KF
    (Knowledge on Flooding), DRE (Disaster Response Effectiveness), and
    RC (Recovery Capacity). Call this once per capacity type with that
    capacity's own indicators, then feed the resulting `scores` arrays
    into /firas/insecurity or /firas/resilience.
    """
    data = _to_dataframe(payload.indicators)
    try:
        result = insecurity_service.compute_capacity_subindex(data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CapacitySubindexResponse(
        scores=result.scores.tolist(),
        weights=result.weights,
        summary=IndexSummary(
            mean=float(result.scores.mean()),
            min=float(result.scores.min()),
            max=float(result.scores.max()),
            dominant_class="n/a",  # capacity sub-indices have no FIRAS classification scheme of their own
        ),
    )


@router.post("/vulnerability", response_model=CompositeIndexResponse)
def compute_vulnerability(payload: FviRequest) -> CompositeIndexResponse:
    from app.services.firas.classification import GENERIC_BANDS

    try:
        result = vulnerability_service.compute_fvi(
            social=pd.Series(payload.social),
            physical=pd.Series(payload.physical),
            economic=pd.Series(payload.economic),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _composite_response(result, GENERIC_BANDS)


@router.post("/insecurity", response_model=CompositeIndexResponse)
def compute_insecurity(payload: FiiRequest) -> CompositeIndexResponse:
    from app.services.firas.classification import INSECURITY_BANDS

    try:
        result = insecurity_service.compute_fii(
            cpc=pd.Series(payload.cpc),
            ewe=pd.Series(payload.ewe),
            kf=pd.Series(payload.kf),
            dre=pd.Series(payload.dre),
            rc=pd.Series(payload.rc),
            fvi=pd.Series(payload.fvi),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _composite_response(result, INSECURITY_BANDS)


@router.post("/resilience", response_model=CompositeIndexResponse)
def compute_resilience(payload: CriRequest) -> CompositeIndexResponse:
    from app.services.firas.classification import RESILIENCE_BANDS

    try:
        result = resilience_service.compute_cri(
            cpc=pd.Series(payload.cpc),
            ewe=pd.Series(payload.ewe),
            kf=pd.Series(payload.kf),
            dre=pd.Series(payload.dre),
            rc=pd.Series(payload.rc),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _composite_response(result, RESILIENCE_BANDS)


@router.post("/risk", response_model=FriResponse)
def compute_risk(payload: FriRequest) -> FriResponse:
    from app.services.firas.classification import RISK_BANDS

    try:
        scores = risk_service.compute_fri(
            hazard=pd.Series(payload.hazard),
            exposure=pd.Series(payload.exposure),
            insecurity=pd.Series(payload.insecurity),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    labels = classify_series(scores, RISK_BANDS)
    return FriResponse(
        scores=scores.tolist(),
        classifications=labels.tolist(),
        summary=_summarize(scores, labels),
    )
