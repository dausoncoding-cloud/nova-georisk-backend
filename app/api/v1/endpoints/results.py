"""Authorized delivery of persisted analysis-result artifacts."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.serializers import serialize_result
from app.core.artifact_storage import artifact_root
from app.core.entitlements import active_engine_keys, require_active_membership, require_engine_entitlement
from app.core.security import RequestContext, get_request_context, require_project_access, verify_internal_secret
from app.db.session import get_db
from app.models.project import Project
from app.models.result import Result
from app.schemas.results import ResultPage, ResultResponse

router = APIRouter(prefix="/results", tags=["Results"], dependencies=[Depends(verify_internal_secret)])


def _single_byte_range(value: str, size: int) -> tuple[int, int]:
    """Parse one RFC 7233 byte range and return an inclusive interval."""
    try:
        unit, requested = value.split("=", 1)
        if unit.strip().lower() != "bytes" or "," in requested:
            raise ValueError
        start_text, end_text = requested.strip().split("-", 1)
        if not start_text:
            suffix_length = int(end_text)
            if suffix_length <= 0:
                raise ValueError
            start = max(0, size - suffix_length)
            end = size - 1
        else:
            start = int(start_text)
            end = min(int(end_text), size - 1) if end_text else size - 1
        if start < 0 or start >= size or end < start:
            raise ValueError
        return start, end
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=416,
            detail="Requested byte range is not satisfiable.",
            headers={"Content-Range": f"bytes */{size}"},
        ) from exc


def _file_chunks(path: Path, start: int, length: int) -> Iterator[bytes]:
    remaining = length
    with path.open("rb") as handle:
        handle.seek(start)
        while remaining > 0:
            chunk = handle.read(min(64 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _protected_file_response(
    request: Request,
    path: Path,
    *,
    media_type: str,
    filename: str,
):
    """Stream an authorized file, including single-range COG reads."""
    stat = path.stat()
    base = FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        content_disposition_type="attachment",
        stat_result=stat,
    )
    range_header = request.headers.get("range")
    if not range_header:
        return base

    start, end = _single_byte_range(range_header, stat.st_size)
    length = end - start + 1
    headers = dict(base.headers)
    headers.update(
        {
            "accept-ranges": "bytes",
            "content-range": f"bytes {start}-{end}/{stat.st_size}",
            "content-length": str(length),
        }
    )
    return StreamingResponse(
        _file_chunks(path, start, length),
        status_code=206,
        media_type=media_type,
        headers=headers,
    )


@router.get("", response_model=ResultPage)
def list_results(
    project_id: uuid.UUID | None = None,
    aoi_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    result_type: str | None = None,
    engine_key: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> ResultPage:
    query = db.query(Result).join(Project, Result.project_id == Project.id)
    if not context.is_service:
        require_active_membership(db, context)
        query = query.filter(
            Project.organization_id == context.organization_id,
            Result.engine_key.in_(active_engine_keys(db, context.organization_id)),
        )
    if project_id is not None:
        query = query.filter(Result.project_id == project_id)
    if aoi_id is not None:
        query = query.filter(Result.aoi_id == aoi_id)
    if task_id is not None:
        query = query.filter(Result.task_id == task_id)
    if result_type is not None:
        query = query.filter(Result.result_type == result_type)
    if engine_key is not None:
        query = query.filter(Result.engine_key == engine_key.strip().lower())

    total = query.with_entities(func.count(Result.id)).scalar() or 0
    results = (
        query.order_by(Result.created_at.desc(), Result.version.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return ResultPage(
        items=[serialize_result(result) for result in results],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{result_id}", response_model=ResultResponse)
def get_result(
    result_id: uuid.UUID,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> ResultResponse:
    result = db.get(Result, result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Result not found.")
    project = db.get(Project, result.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Result not found.")
    require_active_membership(db, context)
    require_project_access(project, context)
    require_engine_entitlement(db, context, result.engine_key)
    return serialize_result(result)


@router.get("/{result_id}/products/{product_key}")
def get_result_product(
    result_id: uuid.UUID,
    product_key: str,
    request: Request,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
):
    result = db.get(Result, result_id)
    if result is None or result.project_id is None:
        raise HTTPException(status_code=404, detail="Result not found.")
    project = db.get(Project, result.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Result not found.")
    require_active_membership(db, context)
    require_project_access(project, context)
    require_engine_entitlement(db, context, result.engine_key)

    entry = (result.output_files or {}).get(product_key)
    if not isinstance(entry, dict) or not entry.get("path"):
        raise HTTPException(status_code=404, detail="Result product not found.")

    root = artifact_root()
    output_path = (root / entry["path"]).resolve()
    try:
        output_path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Result product not found.") from exc
    if not output_path.is_file():
        raise HTTPException(status_code=404, detail="Result product file is missing.")
    return _protected_file_response(
        request,
        output_path,
        media_type=entry.get("media_type", "application/octet-stream"),
        filename=entry.get("download_name") or output_path.name,
    )
