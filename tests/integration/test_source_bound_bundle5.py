"""Disposable PostGIS proof with explicitly synthetic sources, policies and nowcasts."""
import hashlib
import json
import uuid
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import numpy as np
import pytest
from geoalchemy2.elements import WKTElement
from shapely.geometry import shape
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import get_settings
from app.models.aoi import AOI
from app.models.dataset import Dataset
from app.models.result import Result
from app.models.task import Task, TaskStatus
from app.models.live import LiveEvent, LiveFeedback
from app.workers.celery_tasks import execute_engine_task, run_engine_analysis
from tests.integration.test_source_data_science import REVIEW, _tenant, _survey
from tests.unit.test_source_bound_bundle5 import fixture, live_fixture, live_event, mlr_fixture, REF


def register(client,headers,project_id,source,*,review=True):
    manifest=source.manifest.model_copy(update={'project_id':project_id})
    ext='.tif' if manifest.spatial_resolution else '.csv' if manifest.category=='flood_predictor_observations' else '.geojson'
    response=client.post('/api/v1/source-datasets',headers=headers,data={'manifest':manifest.model_dump_json()},files={'file':('synthetic'+ext,source.data)})
    assert response.status_code==201,response.text
    identifier=response.json()['dataset_id']
    if review:
        response=client.post(f'/api/v1/source-datasets/{identifier}/approve',headers=headers,json={**REVIEW,'evidence_refs':[REF],
            'validation_definition_verified':True,'independent_observations_verified':True,'scoring_policy_verified':True,
            'impact_definition_verified':True,'dss_definitions_verified':True,'live_policy_verified':True,'predictor_catalogue_verified':True})
        assert response.status_code==200,response.text
    return identifier


@pytest.mark.parametrize('module', ['continuous_validation','classification_validation','decision_support','predictor_mlr'])
def test_reviewed_evidence_workflow_persists_dashboards_protects_exports_and_rechecks_approval(client,db_session,monkeypatch,tmp_path,module):
    monkeypatch.setattr(get_settings(),'output_storage_dir',str(tmp_path))
    project,_,headers=_tenant(db_session,'synthetic-bundle5-'+module)
    _,_,foreign=_tenant(db_session,'synthetic-bundle5-other-'+module)
    request,geometry,sources=mlr_fixture() if module=='predictor_mlr' else fixture(module,optional=module.endswith('_validation'))
    aoi=AOI(project_id=project.id,name='Synthetic evidence AOI',source_type='drawn_polygon',geometry=WKTElement(shape(geometry).wkt,srid=4326))
    db_session.add(aoi);db_session.commit()
    identifiers={role:register(client,headers,project.id,source,review=False) for role,source in sources.items()}
    payload=request.model_dump(mode='json');payload.update(project_id=str(project.id),aoi_id=str(aoi.id),sources=identifiers)
    monkeypatch.setattr(run_engine_analysis,'delay',lambda _:SimpleNamespace(id='synthetic-bundle5'))
    assert client.post('/api/v1/analyses/source-bound',headers=headers,json=payload).status_code==422
    for identifier in identifiers.values():
        r=client.post(f'/api/v1/source-datasets/{identifier}/approve',headers=headers,json={**REVIEW,'evidence_refs':[REF],'validation_definition_verified':True,'scoring_policy_verified':True,'dss_definitions_verified':True,'predictor_catalogue_verified':True})
        assert r.status_code==200,r.text
    response=client.post('/api/v1/analyses/source-bound',headers=headers,json=payload)
    assert response.status_code==202,response.text
    task_id=uuid.UUID(response.json()['task']['id']);execute_engine_task(db_session,task_id)
    task=db_session.get(Task,task_id);assert task.status==TaskStatus.COMPLETED,task.error_summary
    result=db_session.query(Result).filter_by(task_id=task_id).one()
    read=client.get(f'/api/v1/results/{result.id}',headers=headers)
    assert read.status_code==200,read.text
    field='decision_support' if module=='decision_support' else 'validation_dashboard'
    assert read.json()[field]==result.summary[field]
    assert client.get(f'/api/v1/results/{result.id}',headers=foreign).status_code==404
    for key,entry in result.output_files.items():
        response=client.get(f'/api/v1/results/{result.id}/products/{key}',headers=headers)
        assert response.status_code==200,(key,response.text)
        assert hashlib.sha256(response.content).hexdigest()==entry['checksum_sha256']
    queued=client.post('/api/v1/analyses/source-bound',headers=headers,json=payload)
    assert queued.status_code==202,queued.text
    identifier=next(iter(identifiers.values()))
    assert client.post(f'/api/v1/source-datasets/{identifier}/revoke',headers=headers).status_code==200
    task_id=uuid.UUID(queued.json()['task']['id']);execute_engine_task(db_session,task_id)
    assert db_session.get(Task,task_id).status==TaskStatus.FAILED
    assert db_session.query(Result).filter_by(task_id=task_id).count()==0


def live_setup(client,db,monkeypatch,tmp_path):
    monkeypatch.setattr(get_settings(),'output_storage_dir',str(tmp_path))
    project,_,headers=_tenant(db,'synthetic-live')
    _,_,foreign=_tenant(db,'synthetic-live-foreign')
    db.commit()
    now=datetime.now(timezone.utc)
    source,_=live_fixture(now)
    identifier=register(client,headers,project.id,source)
    payload=live_event(source,now=now).model_dump(mode='json');payload['policy_dataset_id']=identifier
    return project,headers,foreign,identifier,payload


def test_live_ingestion_idempotency_sourced_alerts_cursor_stream_feedback_and_tenant_isolation(client,db_session,monkeypatch,tmp_path):
    project,headers,foreign,identifier,payload=live_setup(client,db_session,monkeypatch,tmp_path)
    base=f'/api/v1/projects/{project.id}/live'
    response=client.post(base+'/events',headers=headers,json=payload)
    assert response.status_code==200,response.text
    first=response.json();assert first['alerts'][0]['threshold']==4 and first['delivery_status']=='protected_feed_only'
    retry=client.post(base+'/events',headers=headers,json=payload)
    assert retry.status_code==200 and retry.json()['id']==first['id']
    assert db_session.query(LiveEvent).count()==1
    assert client.post(base+'/events',headers=headers,json={**payload,'value':5}).status_code==409
    nowcast={**payload,'event_id':'synthetic-nowcast','kind':'nowcast','model_reference':REF+'-model',
             'valid_at':(datetime.fromisoformat(payload['issued_at'].replace('Z','+00:00'))+timedelta(seconds=120)).isoformat()}
    response=client.post(base+'/events',headers=headers,json=nowcast)
    assert response.status_code==200,response.text
    second=response.json();assert second['alerts'][0]['event_kind']=='nowcast'
    assert second['alerts'][0]['scientific_validation']=='not_asserted'
    response=client.get(base+'/events',headers=headers,params={'policy_dataset_id':identifier,'cursor':first['sequence']})
    assert response.status_code==200 and [row['id'] for row in response.json()['items']]==[second['id']]
    response=client.get(base+'/stream',headers=headers,params={'policy_dataset_id':identifier,'cursor':first['sequence'],'wait_seconds':0})
    assert response.status_code==200 and 'event: sourced-event' in response.text and second['id'] in response.text
    assert first['id'] not in response.text and 'event: cursor' in response.text
    response=client.post(base+f'/events/{first["id"]}/feedback',headers=headers,json={'verdict':'inconclusive','notes':'Synthetic human review only','evidence_references':[REF]})
    assert response.status_code==201,response.text
    assert db_session.query(LiveFeedback).count()==1
    history=client.get(base+f'/events/{first["id"]}/feedback',headers=headers)
    assert history.status_code==200 and history.json()[0]['verdict']=='inconclusive'
    assert db_session.get(LiveEvent,uuid.UUID(first['id'])).payload==payload
    for suffix,params in [('/events',{'policy_dataset_id':identifier}),('/stream',{'policy_dataset_id':identifier,'wait_seconds':0}),(f'/events/{first["id"]}/feedback',{})]:
        assert client.get(base+suffix,headers=foreign,params=params).status_code in {403,404}
    assert client.post(base+'/events',headers=foreign,json=payload).status_code in {403,404}
    assert client.post(f'/api/v1/source-datasets/{identifier}/revoke',headers=headers).status_code==200
    assert client.get(base+'/events',headers=headers,params={'policy_dataset_id':identifier}).status_code==409
    assert client.post(base+'/events',headers=headers,json=payload).status_code==409
    assert client.get(base+f'/events/{first["id"]}/feedback',headers=headers).status_code==409


@pytest.mark.parametrize('mutation',['manifest','bytes','review'])
def test_live_read_rejects_changed_source_identity_or_approval(client,db_session,monkeypatch,tmp_path,mutation):
    project,headers,_,identifier,payload=live_setup(client,db_session,monkeypatch,tmp_path)
    base=f'/api/v1/projects/{project.id}/live'
    response=client.post(base+'/events',headers=headers,json=payload);assert response.status_code==200,response.text
    record=db_session.get(Dataset,uuid.UUID(identifier))
    if mutation=='bytes':
        from pathlib import Path
        Path(record.processed_asset_ref).write_bytes(b'changed synthetic bytes')
    else:
        if mutation=='manifest': record.metadata_json['source_manifest']['live_feed_policy']['max_lateness_seconds']=120
        else: record.metadata_json['readiness']['reviewed_at']='changed synthetic approval'
        flag_modified(record,'metadata_json');db_session.commit()
    assert client.get(base+'/events',headers=headers,params={'policy_dataset_id':identifier}).status_code==409


def test_six_module_map_assembly_preserves_raw_bytes_versions_and_revocation_gates(client,db_session,monkeypatch,tmp_path):
    from tests.integration.test_source_bound_exposure import _register, _setup_hazard, _vectors
    from tests.integration.test_source_bound_insecurity import _capacity
    from tests.integration.test_source_bound_risk import _submit, _run_result, _boundaries, _survey_source
    from tests.unit.test_source_bound_hazard import _fixture as hazard_fixture, _raster
    monkeypatch.setattr(get_settings(), "output_storage_dir", str(tmp_path))
    project, _, headers = _tenant(db_session, "bundle5-maps")
    foreign_project, foreign_aoi, foreign_headers = _tenant(db_session, "bundle5-maps-foreign")
    hazard_request, aoi_geometry, _ = hazard_fixture()
    aoi = AOI(project_id=project.id, name="Risk fixture AOI", source_type="drawn_polygon",
              geometry=WKTElement(shape(aoi_geometry).wkt, srid=4326))
    db_session.add(aoi)
    db_session.commit()
    db_session.refresh(aoi)
    monkeypatch.setattr(run_engine_analysis, "delay", lambda _: SimpleNamespace(id="risk-fixture"))
    hazard = _setup_hazard(client, db_session, headers, project, aoi, monkeypatch)

    exposure_sources = {
        "population": _register(client, headers, project.id, "population", "population_density", _raster(np.full((10, 10), 100))),
        "cropland": _register(client, headers, project.id, "cropland", "cropland_fraction", _raster(np.full((10, 10), 0.5))),
        "livestock": _register(client, headers, project.id, "livestock", "livestock_density", _raster(np.full((10, 10), 20))),
    }
    categories = {"buildings": "buildings", "roads": "roads", "critical_infrastructure": "critical_infrastructure"}
    reviewed_types = {"buildings": ["residential"],
                      "critical_infrastructure": ["school", "hospital", "power"]}
    for role, category in categories.items():
        exposure_sources[role] = _register(client, headers, project.id, role, category,
            _vectors(category, aoi_geometry), inventory_asset_types=reviewed_types.get(role))
    for role, dataset_id in exposure_sources.items():
        approved = client.post(f"/api/v1/source-datasets/{dataset_id}/approve", headers=headers,
            json={**REVIEW, "coverage_complete_verified": role in categories})
        assert approved.status_code == 200, approved.text
    exposure_payload = {"project_id": str(project.id), "aoi_id": str(aoi.id), "module": "exposure",
        "sources": exposure_sources, "upstream_results": {"hazard": str(hazard.id)},
        "period": hazard_request.period.model_dump(mode="json"),
        "target_grid": hazard_request.target_grid.model_dump(),
        "exposure_options": {"hazard_min_level": "moderate"}}
    exposure = _run_result(db_session, _submit(client, headers, exposure_payload))

    unit_sources = {
        "boundaries": _survey_source(client, headers, project.id, "boundaries", "administrative_boundaries",
                                     "risk-boundaries", _boundaries(aoi_geometry)),
        "indicators": _survey_source(client, headers, project.id, "indicators", "vulnerability_indicators",
                                     "risk-vulnerability", _survey()),
        "capacity": _survey_source(client, headers, project.id, "capacity", "community_capacity_indicators",
                                   "risk-capacity", _capacity()),
    }
    fvi_payload = {"project_id": str(project.id), "aoi_id": str(aoi.id), "module": "vulnerability",
                   "sources": {role: unit_sources[role] for role in ("boundaries", "indicators")},
                   "period": hazard_request.period.model_dump(mode="json")}
    fvi = _run_result(db_session, _submit(client, headers, fvi_payload))
    fii_payload = {"project_id": str(project.id), "aoi_id": str(aoi.id), "module": "insecurity",
                   "sources": {role: unit_sources[role] for role in ("boundaries", "capacity")},
                   "upstream_results": {"vulnerability": str(fvi.id)},
                   "period": hazard_request.period.model_dump(mode="json")}
    fii = _run_result(db_session, _submit(client, headers, fii_payload))


    base = {"project_id":str(project.id),"aoi_id":str(aoi.id),"period":hazard_request.period.model_dump(mode="json")}
    risk = _run_result(db_session,_submit(client,headers,{**base,"module":"risk","upstream_results":{"hazard":str(hazard.id),"exposure":str(exposure.id),"insecurity":str(fii.id)},"target_grid":hazard_request.target_grid.model_dump()}))
    resilience = _run_result(db_session,_submit(client,headers,{**base,"module":"resilience","sources":{role:unit_sources[role] for role in ("boundaries","capacity")}}))
    _,_,impact_sources = fixture('prediction_outputs')
    impacts = register(client,headers,project.id,impact_sources['impacts'])
    maps = {"hazard":hazard,"exposure":exposure,"vulnerability":fvi,"insecurity":fii,"risk":risk,"resilience":resilience}
    payload = {**base,"module":"prediction_outputs","sources":{"impacts":impacts},"upstream_results":{role:str(result.id) for role,result in maps.items()}}
    from geoalchemy2.shape import to_shape
    from shapely.geometry import mapping
    aoi_geometry = mapping(to_shape(aoi.geometry))
    from app.services.source_data.module_results import load_module_result
    from app.schemas.source_bindings import SourceBoundAnalysisRequest
    for role, original in maps.items():
        load_module_result(db_session, original.id, SourceBoundAnalysisRequest.model_validate(payload), role, aoi_geometry)
    result = _run_result(db_session,_submit(client,headers,payload))
    assert result.summary['impact']['households']==3
    assert result.summary['impact']['loss_amount']==12.5
    assert set(result.summary['module_maps'])==set(maps)
    for role,upstream in maps.items():
        for key,entry in upstream.output_files.items():
            if entry.get('role')!='product' or entry.get('artifact_type') not in {'raster','vector'}: continue
            assembled=result.output_files[role+'_'+key]
            assert assembled['checksum_sha256']==entry['checksum_sha256']
            assert assembled['gis_metadata']['source_result_version']==upstream.version
            response=client.get(f'/api/v1/results/{result.id}/products/{role}_{key}',headers=headers)
            assert response.status_code==200 and hashlib.sha256(response.content).hexdigest()==entry['checksum_sha256']
    assert client.get(f'/api/v1/results/{result.id}',headers=foreign_headers).status_code==404
    for changed in ({**payload,'upstream_results':{role:str(hazard.id) for role in maps}},
                    {**payload,'upstream_results':{role:identifier for role,identifier in payload['upstream_results'].items() if role!='resilience'}}):
        assert client.post('/api/v1/analyses/source-bound',headers=headers,json=changed).status_code==422
    queued = _submit(client,headers,payload)
    assert client.post(f'/api/v1/source-datasets/{unit_sources["capacity"]}/revoke',headers=headers).status_code==200
    execute_engine_task(db_session,queued)
    assert db_session.get(Task,queued).status==TaskStatus.FAILED
    assert db_session.query(Result).filter_by(task_id=queued).count()==0
