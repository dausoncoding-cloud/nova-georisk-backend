"""Tenant-protected event ledger, resumable SSE alert delivery and sourced feedback."""
import json
import time
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.security import RequestContext, get_request_context, verify_internal_secret
from app.api.v1.endpoints.source_data import _authorize
from app.models.live import LiveEvent, LiveFeedback
from app.schemas.firris_evidence import LiveEventRequest, LiveEventResponse, LiveEventPage, LiveFeedbackRequest, LiveFeedbackResponse
from app.services.source_data.live import ingest_event, load_policy, verify_event_source, event_response
from app.services.source_data.readiness import SourceNotReady

router = APIRouter(prefix='/projects/{project_id}/live',tags=['FIRRIS live evidence'],dependencies=[Depends(verify_internal_secret)])


def _events(db,project_id,policy_id,cursor,limit):
    load_policy(db,policy_id,project_id)
    records = db.scalars(select(LiveEvent).where(LiveEvent.project_id==project_id,LiveEvent.policy_dataset_id==policy_id,LiveEvent.sequence>cursor).order_by(LiveEvent.sequence).limit(limit)).all()
    for record in records: verify_event_source(db,record)
    return records


@router.post('/events',response_model=LiveEventResponse)
def ingest(project_id:uuid.UUID,body:LiveEventRequest,db:Session=Depends(get_db),context:RequestContext=Depends(get_request_context)):
    _authorize(db,context,project_id)
    try:
        event=ingest_event(db,project_id,body,context.user_id)
        db.commit()
        return event_response(event)
    except SourceNotReady as exc:
        db.rollback()
        raise HTTPException(409,str(exc)) from exc


@router.get('/events',response_model=LiveEventPage)
def events(project_id:uuid.UUID,policy_dataset_id:uuid.UUID,cursor:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=500),db:Session=Depends(get_db),context:RequestContext=Depends(get_request_context)):
    _authorize(db,context,project_id,read_only=True)
    try: records=_events(db,project_id,policy_dataset_id,cursor,limit)
    except SourceNotReady as exc: raise HTTPException(409,str(exc)) from exc
    return {'items':[event_response(record) for record in records],'next_cursor':records[-1].sequence if records else cursor,'external_delivery':'unavailable_not_configured'}


@router.get('/stream',response_class=StreamingResponse,responses={200:{'content':{'text/event-stream':{}},'description':'Bounded resumable protected event stream'}})
def stream(project_id:uuid.UUID,policy_dataset_id:uuid.UUID,cursor:int=Query(0,ge=0),wait_seconds:float=Query(1,ge=0,le=30),db:Session=Depends(get_db),context:RequestContext=Depends(get_request_context)):
    _authorize(db,context,project_id,read_only=True)
    try: initial=_events(db,project_id,policy_dataset_id,cursor,100)
    except SourceNotReady as exc: raise HTTPException(409,str(exc)) from exc
    def generate():
        next_cursor=cursor
        deadline=time.monotonic()+wait_seconds
        records=initial
        while True:
            for record in records:
                payload=LiveEventResponse.model_validate(event_response(record)).model_dump(mode='json')
                yield 'id: '+str(record.sequence)+'\nevent: sourced-event\ndata: '+json.dumps(payload,allow_nan=False)+'\n\n'
                next_cursor=record.sequence
            # Close transactions between polls. Recheck access and approval on every batch.
            db.rollback()
            if time.monotonic()>=deadline: break
            time.sleep(min(.25,max(0,deadline-time.monotonic())))
            try:
                _authorize(db,context,project_id,read_only=True)
                records=_events(db,project_id,policy_dataset_id,next_cursor,100)
            except (SourceNotReady,HTTPException):
                yield 'event: unavailable\ndata: {"reason":"Access or reviewed source is unavailable"}\n\n'
                return
        yield 'event: cursor\ndata: '+json.dumps({'next_cursor':next_cursor,'external_delivery':'unavailable_not_configured'})+'\n\n'
    return StreamingResponse(generate(),media_type='text/event-stream',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})


@router.post('/events/{event_id}/feedback',response_model=LiveFeedbackResponse,status_code=201)
def feedback(project_id:uuid.UUID,event_id:uuid.UUID,body:LiveFeedbackRequest,db:Session=Depends(get_db),context:RequestContext=Depends(get_request_context)):
    _authorize(db,context,project_id)
    event=db.get(LiveEvent,event_id)
    if event is None or event.project_id!=project_id: raise HTTPException(404,'Event not found')
    try: verify_event_source(db,event)
    except SourceNotReady as exc: raise HTTPException(409,str(exc)) from exc
    record=LiveFeedback(event_id=event_id,actor_id=context.user_id,verdict=body.verdict,notes=body.notes,evidence_references=body.evidence_references)
    db.add(record)
    db.commit()
    return record


@router.get('/events/{event_id}/feedback',response_model=list[LiveFeedbackResponse])
def feedback_history(project_id:uuid.UUID,event_id:uuid.UUID,db:Session=Depends(get_db),context:RequestContext=Depends(get_request_context)):
    _authorize(db,context,project_id,read_only=True)
    event=db.get(LiveEvent,event_id)
    if event is None or event.project_id!=project_id: raise HTTPException(404,'Event not found')
    try: verify_event_source(db,event)
    except SourceNotReady as exc: raise HTTPException(409,str(exc)) from exc
    return db.scalars(select(LiveFeedback).where(LiveFeedback.event_id==event_id).order_by(LiveFeedback.created_at,LiveFeedback.id).limit(500)).all()
