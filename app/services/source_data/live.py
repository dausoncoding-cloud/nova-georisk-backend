"""Authenticated durable ingestion and reviewed comparisons, never a guessed forecast model."""
import json
import operator
from datetime import datetime, timezone
from sqlalchemy import select, text
from app.models.live import LiveEvent
from app.services.source_data.readiness import load_registered_source, SourceNotReady
from app.services.source_data.bundle4 import reviewed_policy
from app.services.tasks.execution import fingerprint


def load_policy(db, policy_id, project_id, *, root=None):
    source = load_registered_source(db, policy_id, project_id, root=root)
    policy = source.manifest.live_feed_policy
    if source.manifest.category != 'sensor_registry' or policy is None:
        raise SourceNotReady('Live feed requires an explicitly registered sensor registry and policy')
    reviewed_policy(source, policy.policy_reference, 'live_policy_verified')
    sensors = {}
    for feature in json.loads(source.data)['features']:
        row = feature['properties']
        if row['sensor_id'] in sensors: raise SourceNotReady('Duplicate sensor identity')
        sensors[row['sensor_id']] = row
    for rule in policy.alert_rules.values():
        if rule.sensor_id not in sensors or rule.units != sensors[rule.sensor_id]['unit']:
            raise SourceNotReady('Reviewed alert rule sensor/units are incompatible with registry')
    return source, sensors


def evaluate_event(source, sensors, event, now):
    policy = source.manifest.live_feed_policy
    sensor = sensors.get(event.sensor_id)
    if sensor is None or event.units != sensor['unit']:
        raise SourceNotReady('Unknown sensor or incompatible measurement units')
    period = source.manifest.temporal_coverage
    if not period.start <= event.issued_at <= event.valid_at <= period.end:
        raise SourceNotReady('Event times are outside reviewed policy temporal coverage')
    age = (now-event.issued_at).total_seconds()
    if age > policy.max_lateness_seconds or age < -policy.max_future_skew_seconds:
        raise SourceNotReady('Event is outside reviewed lateness/future-skew limits')
    if event.kind == 'nowcast' and (event.model_reference not in policy.nowcast_model_references
            or (event.valid_at-event.issued_at).total_seconds() > policy.max_nowcast_horizon_seconds):
        raise SourceNotReady('Nowcast model or horizon is not supported by reviewed policy')
    comparisons = {'gt':operator.gt,'ge':operator.ge,'lt':operator.lt,'le':operator.le}
    return [{'rule_id':key,'label':rule.label,'operator':rule.operator,'threshold':rule.threshold,'units':rule.units,
             'policy_reference':policy.policy_reference,'event_kind':event.kind,'model_reference':event.model_reference,
             'status':'triggered','scientific_validation':'not_asserted'}
            for key,rule in policy.alert_rules.items() if rule.sensor_id==event.sensor_id and comparisons[rule.operator](event.value,rule.threshold)]


def source_snapshot(source):
    return {'lineage':source.lineage(), 'manifest':source.manifest.model_dump(mode='json'), 'manifest_sha256':fingerprint(source.manifest.model_dump(mode='json'))}


def ingest_event(db, project_id, event, actor_id, *, root=None, now=None):
    # Serializes project writers so a cursor cannot skip an earlier uncommitted sequence.
    db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:project, 0))'), {'project':str(project_id)})
    source, sensors = load_policy(db,event.policy_dataset_id,project_id,root=root)
    payload = event.model_dump(mode='json')
    digest = fingerprint(payload)
    existing = db.scalar(select(LiveEvent).where(LiveEvent.project_id==project_id,LiveEvent.policy_dataset_id==event.policy_dataset_id,LiveEvent.event_key==event.event_id))
    if existing is not None:
        if existing.payload_sha256 != digest or existing.source_snapshot != source_snapshot(source):
            raise SourceNotReady('Event identity was reused with different payload or source approval')
        return existing
    now = now or datetime.now(timezone.utc)
    alerts = evaluate_event(source,sensors,event,now)
    record = LiveEvent(project_id=project_id,policy_dataset_id=event.policy_dataset_id,event_key=event.event_id,
                       payload=payload,payload_sha256=digest,source_snapshot=source_snapshot(source),alerts=alerts,actor_id=actor_id,received_at=now)
    db.add(record)
    db.flush()
    return record


def verify_event_source(db, record, *, root=None):
    source, _ = load_policy(db,record.policy_dataset_id,record.project_id,root=root)
    if source_snapshot(source) != record.source_snapshot or fingerprint(record.payload) != record.payload_sha256:
        raise SourceNotReady('Live event source approval, payload or manifest changed')


def event_response(record):
    return {'id':record.id,'sequence':record.sequence,'payload':record.payload,'received_at':record.received_at,
            'source_snapshot':record.source_snapshot,'alerts':record.alerts,'delivery_status':'protected_feed_only'}
