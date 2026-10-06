"""Synthetic reviewed Bundle 4 API, PostGIS persistence and protected publication."""
import hashlib
import uuid
from types import SimpleNamespace

import pytest
from geoalchemy2.elements import WKTElement
from shapely.geometry import shape

from app.core.config import get_settings
from app.models.aoi import AOI
from app.models.result import Result
from app.models.task import Task, TaskStatus
from app.services.source_data.bindings import BUNDLE4_MODULES
from app.workers.celery_tasks import execute_engine_task, run_engine_analysis
from tests.integration.test_source_data_science import REVIEW, _tenant
from tests.unit.test_source_bound_bundle4 import SYNTHETIC_REF, fixture, kriging_fixture


def setup(client, db, monkeypatch, tmp_path, module):
    monkeypatch.setattr(get_settings(), 'output_storage_dir', str(tmp_path))
    project, _, headers = _tenant(db, 'synthetic-bundle4-'+module)
    _, _, foreign = _tenant(db, 'synthetic-bundle4-foreign-'+module)
    request, geometry, sources = kriging_fixture() if module == "rainfall_kriging" else fixture(module)
    aoi = AOI(project_id=project.id, name='Synthetic Bundle 4 AOI', source_type='drawn_polygon',
              geometry=WKTElement(shape(geometry).wkt, srid=4326))
    db.add(aoi)
    db.commit()
    identifiers = {}
    for role, source in sources.items():
        m = source.manifest.model_copy(update={'project_id': project.id})
        extension = '.tif' if m.spatial_resolution else '.geojson' if source.data.startswith(b'{') else '.csv'
        response = client.post('/api/v1/source-datasets', headers=headers,
            data={'manifest': m.model_dump_json()}, files={'file': (role+extension, source.data)})
        assert response.status_code == 201, response.text
        identifiers[role] = response.json()['dataset_id']
    payload = request.model_dump(mode='json')
    payload.update(project_id=str(project.id), aoi_id=str(aoi.id), sources=identifiers)
    monkeypatch.setattr(run_engine_analysis, 'delay', lambda _: SimpleNamespace(id='synthetic-bundle4'))
    return payload, identifiers, sources, headers, foreign


def approve(client, identifiers, headers, *, scoring=True):
    for identifier in identifiers.values():
        response = client.post(f'/api/v1/source-datasets/{identifier}/approve', headers=headers,
            json={**REVIEW, 'evidence_refs': [SYNTHETIC_REF], 'coverage_complete_verified': True,
                  'annual_record_complete_verified': True, 'hydrologic_coverage_verified': True,
                  'dem_conditioning_verified': True, 'scoring_policy_verified': scoring, 'predictor_catalogue_verified': True})
        assert response.status_code == 200, response.text


@pytest.mark.parametrize('module', sorted(BUNDLE4_MODULES | {'rainfall_kriging'}))
def test_reviewed_workflow_publishes_source_pinned_protected_result(client, db_session, monkeypatch, tmp_path, module):
    payload, identifiers, sources, headers, foreign = setup(client, db_session, monkeypatch, tmp_path, module)
    assert client.post('/api/v1/analyses/source-bound', headers=headers, json=payload).status_code == 422
    approve(client, identifiers, headers)
    response = client.post('/api/v1/analyses/source-bound', headers=headers, json=payload)
    assert response.status_code == 202, response.text
    task_id = uuid.UUID(response.json()['task']['id'])
    execute_engine_task(db_session, task_id)
    task = db_session.get(Task, task_id)
    assert task.status == TaskStatus.COMPLETED, task.error_summary
    result = db_session.query(Result).filter_by(task_id=task_id).one()
    assert result.result_type == 'source_bound_'+payload['module']
    assert set(result.provenance['source_bindings']) == set(sources)
    assert result.summary['delivery'] and result.summary['interpretation']
    for role, source in sources.items():
        assert result.provenance['source_bindings'][role]['sha256'] == hashlib.sha256(source.data).hexdigest()
    assert client.get(f'/api/v1/results/{result.id}', headers=headers).status_code == 200
    assert client.get(f'/api/v1/results/{result.id}', headers=foreign).status_code == 404
    products = [key for key, entry in result.output_files.items() if entry.get('role') == 'product']
    for key in products+['report_package', 'provenance', 'quantitative_data']:
        downloaded = client.get(f'/api/v1/results/{result.id}/products/{key}', headers=headers)
        assert downloaded.status_code == 200, (key, downloaded.text)
        assert hashlib.sha256(downloaded.content).hexdigest() == result.output_files[key]['checksum_sha256']
        assert client.get(f'/api/v1/results/{result.id}/products/{key}', headers=foreign).status_code == 404
    # A queued task cannot publish after the bound source's review is revoked.
    queued = client.post('/api/v1/analyses/source-bound', headers=headers, json=payload)
    assert queued.status_code == 202, queued.text
    identifier = next(iter(identifiers.values()))
    assert client.post(f'/api/v1/source-datasets/{identifier}/revoke', headers=headers).status_code == 200
    revoked_task_id = uuid.UUID(queued.json()['task']['id'])
    execute_engine_task(db_session, revoked_task_id)
    assert db_session.get(Task, revoked_task_id).status == TaskStatus.FAILED
    assert db_session.query(Result).filter_by(task_id=revoked_task_id).count() == 0


@pytest.mark.parametrize('module', ['feature_proximity', 'soil_infiltration'])
def test_generic_readiness_does_not_approve_a_scoring_policy(client, db_session, monkeypatch, tmp_path, module):
    payload, identifiers, _, headers, _ = setup(client, db_session, monkeypatch, tmp_path, module)
    approve(client, identifiers, headers, scoring=False)
    response = client.post('/api/v1/analyses/source-bound', headers=headers, json=payload)
    assert response.status_code == 422
    assert 'review' in response.text.lower()
    assert db_session.query(Task).count() == 0
