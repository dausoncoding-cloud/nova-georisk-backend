"""Disposable PostGIS lifecycle with explicitly synthetic sources and policies."""
import hashlib
import uuid
from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path

import numpy as np
import pytest
from geoalchemy2.elements import WKTElement
from shapely.geometry import shape

from app.core.config import get_settings
from app.models.aoi import AOI
from app.models.task import Task, TaskStatus
from app.models.result import Result
from app.workers.celery_tasks import execute_engine_task, run_engine_analysis
from tests.integration.test_source_data_science import REVIEW, _tenant
from tests.unit.test_firris_final_engineering import susceptibility_fixture, policy_source, REF
from tests.unit.test_source_bound_hazard import _fixture
from tests.unit.test_source_bound_bundle5 import raster
from tests.unit.test_firris_source_data import manifest


def register(client,headers,project,source,*,ready=True):
    m=source.manifest.model_copy(update={'project_id':project.id})
    filename='synthetic.tif' if m.spatial_resolution else 'synthetic.csv'
    response=client.post('/api/v1/source-datasets',headers=headers,data={'manifest':m.model_dump_json()},files={'file':(filename,source.data)})
    assert response.status_code==201,response.text
    identifier=response.json()['dataset_id']
    if ready: approve(client,headers,identifier)
    return identifier


def approve(client,headers,identifier):
    response=client.post(f'/api/v1/source-datasets/{identifier}/approve',headers=headers,json={**REVIEW,'evidence_refs':[REF],
        'susceptibility_method_verified':True,'zonation_method_verified':True,'predictor_catalogue_verified':True,
        'independent_observations_verified':True,'hydraulic_model_verified':True})
    assert response.status_code==200,response.text


def run(client,headers,db,payload):
    response=client.post('/api/v1/analyses/source-bound',headers=headers,json=payload)
    assert response.status_code==202,response.text
    identifier=uuid.UUID(response.json()['task']['id']);execute_engine_task(db,identifier)
    task=db.get(Task,identifier);assert task.status==TaskStatus.COMPLETED,task.error_summary
    return db.query(Result).filter_by(task_id=identifier).one()


def setup(db,monkeypatch,tmp_path,suffix,aoi_geometry):
    monkeypatch.setattr(get_settings(),'output_storage_dir',str(tmp_path))
    monkeypatch.setattr(run_engine_analysis,'delay',lambda _:SimpleNamespace(id='synthetic-final'))
    project,_,headers=_tenant(db,'synthetic-final-'+suffix)
    _,_,foreign=_tenant(db,'synthetic-final-other-'+suffix)
    aoi=AOI(project_id=project.id,name='Synthetic final map AOI',source_type='drawn_polygon',geometry=WKTElement(shape(aoi_geometry).wkt,srid=4326))
    db.add(aoi);db.commit()
    return project,aoi,headers,foreign


def assert_exports(client,headers,foreign,result):
    detail=client.get(f'/api/v1/results/{result.id}',headers=headers)
    assert detail.status_code==200,detail.text
    layer=next(layer for layer in detail.json()['layers'] if layer['product_key']==result.provenance['module'])
    assert layer['crs']=='EPSG:3857' and layer['legend']
    assert client.get(f'/api/v1/results/{result.id}',headers=foreign).status_code==404
    for key,entry in result.output_files.items():
        response=client.get(f'/api/v1/results/{result.id}/products/{key}',headers=headers)
        assert response.status_code==200,(key,response.text)
        assert hashlib.sha256(response.content).hexdigest()==entry['checksum_sha256']
        assert client.get(f'/api/v1/results/{result.id}/products/{key}',headers=foreign).status_code==404


def test_distinct_susceptibility_review_registration_worker_delivery_and_revocation(client,db_session,monkeypatch,tmp_path):
    request,geometry,sources=susceptibility_fixture()
    project,aoi,headers,foreign=setup(db_session,monkeypatch,tmp_path,'susceptibility',geometry)
    identifiers={key:register(client,headers,project,source,ready=key!='observations') for key,source in sources.items()}
    payload=request.model_dump(mode='json');payload.update(project_id=str(project.id),aoi_id=str(aoi.id),sources=identifiers)
    assert client.post('/api/v1/analyses/source-bound',headers=headers,json=payload).status_code==422
    approve(client,headers,identifiers['observations'])
    wrong={**payload,'susceptibility_options':{'method_reference':'fixture:wrong'}}
    assert client.post('/api/v1/analyses/source-bound',headers=headers,json=wrong).status_code==422
    result=run(client,headers,db_session,payload)
    assert result.provenance['method_details']['holdout_count']==12
    assert result.provenance['source_bindings']['observations']['susceptibility_method']['method_reference']==REF
    assert_exports(client,headers,foreign,result)
    queued=client.post('/api/v1/analyses/source-bound',headers=headers,json=payload);assert queued.status_code==202,queued.text
    assert client.post(f'/api/v1/source-datasets/{identifiers["observations"]}/revoke',headers=headers).status_code==200
    identifier=uuid.UUID(queued.json()['task']['id']);execute_engine_task(db_session,identifier)
    assert db_session.get(Task,identifier).status==TaskStatus.FAILED
    assert db_session.query(Result).filter_by(task_id=identifier).count()==0


def test_reviewed_multifactor_zonation_rechecks_actual_depth_velocity_duration_and_policy(client,db_session,monkeypatch,tmp_path):
    original,geometry,_=_fixture();source=policy_source()
    project,aoi,headers,foreign=setup(db_session,monkeypatch,tmp_path,'zonation',geometry)
    period=source.manifest.temporal_coverage.model_dump(mode='json')
    # The interval is bounded by verified dry endpoints: exactly one hour of synthetic inundation.
    period={'start':'2021-06-01T00:00:00Z','end':'2021-06-01T02:00:00Z'}
    common={'project_id':str(project.id),'aoi_id':str(aoi.id),'period':period,'target_grid':original.target_grid.model_dump()}
    sources={}
    for role,category,values in [('terrain','terrain_dem',np.full(16,100)),('water_surface','water_surface_elevation',100+np.arange(16)/4),('velocity','hydraulic_model_velocity',np.full(16,2))]:
        data=raster(values)
        m=manifest(category,data,crs='EPSG:3857',spatial_resolution={'x':100,'y':100,'unit':'m'},temporal_coverage=period,
            vertical_datum='synthetic-MSL' if role!='velocity' else None,hydraulic_model_validation_reference=REF if role=='velocity' else None)
        sources[role]=register(client,headers,project,SimpleNamespace(manifest=m,data=data))
    depth=run(client,headers,db_session,{**common,'module':'flood_depth','sources':{key:sources[key] for key in ('terrain','water_surface')}})
    velocity=run(client,headers,db_session,{**common,'module':'flood_velocity','sources':{'model_velocity':sources['velocity']}})
    slices={}
    for i,values in enumerate([np.zeros(16),np.ones(16),np.zeros(16)]):
        data=raster(values);instant=f'2021-06-01T0{i}:00:00Z'
        m=manifest('inundation_time_slice',data,crs='EPSG:3857',spatial_resolution={'x':100,'y':100,'unit':'m'},temporal_coverage={'start':instant,'end':instant},observation_definition='Synthetic fixed-cadence binary snapshot')
        slices['slice_'+str(i)]=register(client,headers,project,SimpleNamespace(manifest=m,data=data))
    duration=run(client,headers,db_session,{**common,'module':'flood_duration','sources':slices,'duration_options':{'temporal_resolution_hours':1,'gap_policy':'reject'}})
    source=replace(source,manifest=source.manifest.model_copy(update={'temporal_coverage':original.period.model_validate(period)}))
    policy=register(client,headers,project,source)
    payload={**common,'module':'flood_hazard_zonation','sources':{'policy':policy},'upstream_results':{'depth':str(depth.id),'velocity':str(velocity.id),'duration':str(duration.id)},'zonation_options':{'method_reference':REF}}
    assert client.post('/api/v1/analyses/source-bound',headers=headers,json={**payload,'upstream_results':{'depth':str(depth.id),'velocity':str(velocity.id)}}).status_code==422
    result=run(client,headers,db_session,payload)
    assert set(result.provenance['upstream_results'])=={'depth','velocity','duration'}
    assert [row['cell_count'] for row in result.summary['class_statistics']]==[8,8]
    assert result.output_files['flood_hazard_zonation']['gis_metadata']['vertical_datum']=='synthetic-MSL'
    assert_exports(client,headers,foreign,result)
    queued=client.post('/api/v1/analyses/source-bound',headers=headers,json=payload);assert queued.status_code==202,queued.text
    assert client.post(f'/api/v1/source-datasets/{slices["slice_1"]}/revoke',headers=headers).status_code==200
    identifier=uuid.UUID(queued.json()['task']['id']);execute_engine_task(db_session,identifier)
    assert db_session.get(Task,identifier).status==TaskStatus.FAILED
    assert db_session.query(Result).filter_by(task_id=identifier).count()==0


def test_m01_acquired_bytes_and_before_target_sar_are_persisted_and_protected(client,db_session,monkeypatch,tmp_path):
    from tests.integration.test_firris_execution import _tenant as tenant, _project_aoi
    from app.services.gee.firris_pipeline import GEEFeatureStack
    from app.services.maps.export import RasterSpec
    from rasterio.io import MemoryFile
    monkeypatch.setattr(get_settings(),'output_storage_dir',str(tmp_path))
    organization,headers=tenant(db_session,'synthetic-final-gee');_,foreign=tenant(db_session,'synthetic-final-gee-foreign')
    project,aoi=_project_aoi(db_session,organization);db_session.commit()
    rows,cols=np.indices((16,16));labels=((rows>6)&(cols<10)).astype('uint8')
    spec=RasterSpec.from_bbox(36,-2,37,-1,16,16)
    source_arrays={'source_sar_baseline':rows.astype('float32')-20,'source_sar_target':cols.astype('float32')-20}
    with MemoryFile() as memory:
        with memory.open(driver='GTiff',width=16,height=16,count=2,dtype='float32',crs='EPSG:4326',transform=spec.transform,nodata=-9999) as dst:
            dst.write(np.stack(list(source_arrays.values())));dst.descriptions=tuple(source_arrays)
        original=memory.read()
    def acquired(config,geometry,workspace):
        workspace.mkdir(parents=True,exist_ok=True);path=workspace/'synthetic-received-export.tif';path.write_bytes(original)
        return GEEFeatureStack(feature_layers={'rainfall':rows.astype(float),'elevation':cols.astype(float)},label_layer=labels,valid_mask=np.ones((16,16),dtype=bool),transform=spec.transform,crs='EPSG:4326',quality={'status':'passed','fixture_scope':'synthetic engineering only'},source_artifacts={'acquired_feature_stack':path},source_rasters=source_arrays,
            provenance={'source':'synthetic GEE boundary fixture; not real observations','label_source':'synthetic SAR pseudo-label','independent_ground_truth':False,
                'baseline_period':config['baseline_period'],'target_period':config['target_period'],'per_scene_lineage':{'scope':'synthetic, no live scenes'},
                'acquisition_artifacts':{'acquired_feature_stack':{'sha256':hashlib.sha256(original).hexdigest(),'size_bytes':len(original),'filename':path.name}},
                'source_fidelity_scope':'received synthetic bytes only; provider source-byte checksum unavailable'})
    monkeypatch.setattr('app.services.gee.firris_pipeline.fetch_feature_stack',acquired)
    monkeypatch.setattr(run_engine_analysis,'delay',lambda _:SimpleNamespace(id='synthetic-final-gee'))
    payload={'project_id':str(project.id),'aoi_id':str(aoi.id),'products':['flood_extent','flood_probability'],
        'gis_metadata':{'crs':'EPSG:4326','bounding_box':{'west':36,'south':-2,'east':37,'north':-1},'spatial_resolution':{'x':.0625,'y':.0625,'unit':'degree'}},
        'parameters':{'workflow':{'source':{'provider':'gee','target_period':{'start':'2024-03-01','end':'2024-03-10'},'baseline_period':{'start':'2024-02-01','end':'2024-02-10'}},
            'sampling':{'sample_size':160,'min_per_class':20,'train_fraction':.7,'random_seed':9},'model':{'algorithm':'random_forest','version':'synthetic','n_estimators':10}}}}
    response=client.post('/api/v1/analyses',headers=headers,json=payload);assert response.status_code==202,response.text
    task_id=uuid.UUID(response.json()['task']['id']);execute_engine_task(db_session,task_id)
    task=db_session.get(Task,task_id);assert task.status==TaskStatus.COMPLETED,task.error_summary
    result=db_session.query(Result).filter_by(task_id=task_id).one()
    for key in ['acquired_feature_stack',*source_arrays]:
        response=client.get(f'/api/v1/results/{result.id}/products/{key}',headers=headers)
        assert response.status_code==200,response.text
        assert hashlib.sha256(response.content).hexdigest()==result.output_files[key]['checksum_sha256']
        assert client.get(f'/api/v1/results/{result.id}/products/{key}',headers=foreign).status_code==404
        if key=='acquired_feature_stack': assert response.content==original
    assert result.provenance['validation']['independent_ground_truth'] is False
