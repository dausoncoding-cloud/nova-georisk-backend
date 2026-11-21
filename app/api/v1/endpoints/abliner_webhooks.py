"""Abliner webhook receiver (plan §3, review row B3).

Reached only through the gateway location and the BFF's single session-less route: the internal secret is
required (verify_internal_secret), there is no user principal, and the request is authenticated by HMAC.
The raw body is read before any parsing. Answers 2xx quickly; settlement is idempotent.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.security import verify_internal_secret
from app.db.session import get_db
from app.services.abliner import webhooks

router = APIRouter(prefix="/webhooks", tags=["Webhooks"], dependencies=[Depends(verify_internal_secret)],
                   include_in_schema=False)


@router.post("/abliner")
async def abliner_webhook(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    raw = await request.body()
    try:
        outcome = await run_in_threadpool(webhooks.process, db, raw, request.headers)
    except webhooks.Rejected as exc:
        return JSONResponse(status_code=exc.status, content={"status": "rejected", "code": exc.code})
    return JSONResponse(status_code=200, content={"status": outcome.status})
