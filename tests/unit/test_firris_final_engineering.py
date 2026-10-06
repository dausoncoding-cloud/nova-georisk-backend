"""Synthetic engineering mechanics only; no licensed data or scientific approval."""
import copy
import csv
import hashlib
import io
import json
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
import rasterio
from pydantic import ValidationError

from app.schemas.map_methods import SusceptibilityMethod, ZonationDefinition
from app.schemas.source_bindings import SourceBoundAnalysisRequest
from app.services.maps.export import RasterSpec, write_cog
from app.services.source_data.bindings import ResolvedBindings
from app.services.source_data.readiness import ReadySource, SourceNotReady
from app.services.source_data.reviewed_maps import susceptibility_inputs, zonation_inputs, execute_reviewed_map
from app.services.gee.scene_qa import inspect_collection, inspect_static_image
from tests.unit.test_source_bound_bundle5 import mlr_fixture, raster, REF
from tests.unit.test_source_bound_hazard import _fixture
from tests.unit.test_firris_source_data import manifest
from tests.unit.test_firris_bundle1 import scene, AOI

TARGET={'start':'2021-06-01T00:00:00Z','end':'2021-06-01T00:00:00Z'}


def susceptibility_fixture():
    _,aoi,sources=mlr_fixture()
    original,_,_=_fixture()
    source=sources['observations'];definitions=source.manifest.predictor_definitions
    keys=[key for key,value in definitions.items() if value.role=='predictor']
    response='synthetic_response'
    label='Synthetic historical absent/present observations, not field evidence'
    definitions={**definitions,response:definitions[response].model_copy(update={'unit':'binary_class_0_1','definition':label})}
    rows=list(csv.DictReader(io.StringIO(source.data.decode())))
    for row in rows:
        if row['variable']==response:
            row['value']=str(int(row['sample_id'].split('-')[-1])%2);row['unit']='binary_class_0_1'
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows);data=stream.getvalue().encode()
    method=SusceptibilityMethod(method_reference=REF,method_version='synthetic-v1',historical_observation_reference=REF,label_definition=label,class_labels={'0':'Synthetic absent','1':'Synthetic present'},response=response,predictor_order=keys,algorithm='random_forest',n_estimators=10,train_fraction=.8,random_seed=15,split_policy='chronological',display_legend=[{'label':'Synthetic score A','color':'#000000','min':0,'max':.5},{'label':'Synthetic score B','color':'#FFFFFF','min':.5,'max':1}])
    source=replace(source,data=data,manifest=source.manifest.model_copy(update={'predictor_definitions':definitions,'susceptibility_method':method,'sha256':hashlib.sha256(data).hexdigest()}),evidence={'analysis_ready':True,'evidence_refs':[REF],'checks':{'predictor_catalogue_verified':True,'susceptibility_method_verified':True,'independent_observations_verified':True}})
    sources={'observations':source}
    for key in keys:
        data=raster(np.linspace(-.5,.5,16))
        m=manifest('flood_predictor_raster',data,crs='EPSG:3857',spatial_resolution={'x':100,'y':100,'unit':'m'},temporal_coverage=TARGET,raster_predictor={'name':key,'catalogue_reference':REF,'variable':definitions[key].model_dump()})
        sources['predictor_'+key]=ReadySource(SimpleNamespace(id=uuid.uuid4(),created_at=None),m,data,{'analysis_ready':True,'evidence_refs':[REF],'checks':{'predictor_catalogue_verified':True}})
    request=SourceBoundAnalysisRequest(project_id=original.project_id,aoi_id=original.aoi_id,module='flood_susceptibility',sources={key:value.dataset.id for key,value in sources.items()},period=TARGET,target_grid=original.target_grid,susceptibility_options={'method_reference':REF})
    return request,aoi,sources


def policy_source(period=TARGET):
    fields=['rule_id','factor','lower_bound','upper_bound','class_code','observed_at','quality_flag']
    rows=[]
    for code,lower,upper in [(1,0,2),(2,2,100)]:
        for factor in ['depth','velocity','duration']:
            rows.append({'rule_id':'synthetic-'+str(code),'factor':factor,'lower_bound':lower if factor=='depth' else 0,'upper_bound':upper if factor=='depth' else 100,'class_code':code,'observed_at':period['start'],'quality_flag':'valid'})
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows);data=stream.getvalue().encode()
    m=manifest('flood_zonation_policy',data,temporal_coverage=period,zonation_policy={'method':'reviewed_interval_decision_table','method_reference':REF,'method_version':'synthetic-v1','definition':'Synthetic three-factor decision table; not calibrated or safety approved','factor_units':{'depth':'m','velocity':'m/s','duration':'hours'},'classes':{'1':{'label':'Synthetic A','color':'#000000'},'2':{'label':'Synthetic B','color':'#FFFFFF'}}})
    return ReadySource(SimpleNamespace(id=uuid.uuid4(),created_at=None),m,data,{'analysis_ready':True,'evidence_refs':[REF],'checks':{'zonation_method_verified':True}})


def zonation_fixture(tmp_path):
    original,aoi,_=_fixture();source=policy_source()
    upstream={}
    for factor,units,values in [('depth','m',np.arange(16)/4),('velocity','m/s',np.full(16,2)),('duration','hours',np.full(16,3))]:
        key='flood_'+factor;path=tmp_path/(key+'.tif');write_cog(str(path),values.reshape(4,4).astype(float),RasterSpec.from_bounds(300,700,100,3857),nodata=-9999)
        meta={'units':units,'target_period':TARGET,'result_version':1,'crs':'EPSG:3857','vertical_datum':'synthetic-MSL' if factor=='depth' else None}
        ready=SimpleNamespace(result=SimpleNamespace(id=uuid.uuid4(),version=1,output_files={key:{'gis_metadata':meta}}),raster_bytes=path.read_bytes(),lineage=lambda:{'source':'synthetic'})
        upstream[factor]=ready
    request=SourceBoundAnalysisRequest(project_id=original.project_id,aoi_id=original.aoi_id,module='flood_hazard_zonation',sources={'policy':source.dataset.id},upstream_results={key:value.result.id for key,value in upstream.items()},period=TARGET,target_grid=original.target_grid,zonation_options={'method_reference':REF})
    return ResolvedBindings(request,{'policy':source},{},upstream),aoi


def test_distinct_susceptibility_fits_historical_classifier_and_preserves_raw_inputs_and_scores(tmp_path):
    request,aoi,sources=susceptibility_fixture()
    output=execute_reviewed_map(ResolvedBindings(request,sources,{}),aoi,tmp_path,1,task_id='synthetic')
    assert output.provenance['method_details']['training_count']==48
    assert output.provenance['method_details']['holdout_count']==12
    assert output.provenance['method_details']['classifier_configuration']['estimator']=='RandomForestClassifier'
    assert 'not annual' in output.summary['method_interpretation']
    assert {'flood_susceptibility','raw_historical_class_prediction','fitted_classifier','report_package','flood_susceptibility_map_pdf'}<=set(output.output_files)
    assert sum(row['cell_count'] for row in output.summary['class_statistics'])==16
    assert (tmp_path/output.output_files['source_observations']['path']).read_bytes()==sources['observations'].data
    with rasterio.open(tmp_path/output.output_files['flood_susceptibility']['path']) as raster:
        assert raster.is_tiled and raster.crs.to_string()=='EPSG:3857'
        assert ((raster.read(1)>=0)&(raster.read(1)<=1)).all()


@pytest.mark.parametrize('mutation',['review','reference','labels','period','predictor_identity','grid','nodata','extrapolation','missing_predictor','catalogue_review','same_time_split'])
def test_susceptibility_rejects_incompatible_or_unsupported_sources(mutation):
    request,aoi,sources=susceptibility_fixture();source=sources['observations']
    key=next(key for key in sources if key.startswith('predictor_'));predictor=sources[key]
    if mutation=='review': sources['observations']=replace(source,evidence={'checks':{}})
    elif mutation=='reference': request=request.model_copy(update={'susceptibility_options':request.susceptibility_options.model_copy(update={'method_reference':'fixture:other'})})
    elif mutation=='labels': sources['observations']=replace(source,data=source.data.replace(b',1,binary_class',b',2,binary_class'))
    elif mutation=='period': sources['observations']=replace(source,manifest=source.manifest.model_copy(update={'temporal_coverage':request.period}))
    elif mutation=='predictor_identity': sources[key]=replace(predictor,manifest=predictor.manifest.model_copy(update={'raster_predictor':predictor.manifest.raster_predictor.model_copy(update={'name':'other'})}))
    elif mutation=='grid': request=request.model_copy(update={'target_grid':request.target_grid.model_copy(update={'width':5})})
    elif mutation=='nodata': data=np.zeros(16);data[0]=-9999;sources[key]=replace(predictor,data=raster(data))
    elif mutation=='extrapolation': sources[key]=replace(predictor,data=raster(np.full(16,10000)))
    elif mutation=='missing_predictor': sources.pop(key)
    elif mutation=='catalogue_review': sources[key]=replace(predictor,evidence={'checks':{}})
    else:
        rows=list(csv.DictReader(io.StringIO(source.data.decode())))
        for row in rows: row['observed_at']='2020-01-01T00:00:00Z'
        stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        sources['observations']=replace(source,data=stream.getvalue().encode())
    with pytest.raises(SourceNotReady): susceptibility_inputs(ResolvedBindings(request,sources,{}),aoi)


def test_reviewed_three_factor_zones_execute_supplied_intervals_and_preserve_physics(tmp_path):
    bindings,aoi=zonation_fixture(tmp_path)
    output=execute_reviewed_map(bindings,aoi,tmp_path/'maps',1,task_id='synthetic')
    assert set(output.provenance['upstream_results'])=={'depth','velocity','duration'}
    assert len(output.provenance['method_details']['decision_table'])==2
    assert [row['cell_count'] for row in output.summary['class_statistics']]==[8,8]
    with rasterio.open(tmp_path/'maps'/output.output_files['raw_depth_velocity_index']['path']) as raster:
        np.testing.assert_array_equal(raster.read(1).ravel(),np.arange(16)/2)
    for factor,ready in bindings.upstream.items(): assert (tmp_path/'maps'/output.output_files['raw_'+factor]['path']).read_bytes()==ready.raster_bytes
    assert 'flood_hazard_zonation_map_pdf' in output.output_files


@pytest.mark.parametrize('mutation',['overlap','uncovered','missing_factor','bad_unit','bad_period','unreviewed','missing_rule_factor','duplicate','other_method'])
def test_zonation_fails_closed_on_incomplete_or_unsupported_policy(tmp_path,mutation):
    bindings,aoi=zonation_fixture(tmp_path);sources=dict(bindings.sources);upstream=dict(bindings.upstream);source=sources['policy'];data=source.data
    if mutation=='overlap': data=data.replace(b'depth,2,100',b'depth,0,100')
    elif mutation=='uncovered': data=data.replace(b'depth,2,100',b'depth,3,100')
    elif mutation=='missing_rule_factor': data=b'\n'.join(line for line in data.split(b'\n') if not line.startswith(b'synthetic-1,duration'))
    elif mutation=='duplicate': data+=data.splitlines()[1]+b'\n'
    elif mutation=='missing_factor': upstream.pop('duration')
    elif mutation=='bad_unit': upstream['duration'].result.output_files['flood_duration']['gis_metadata']['units']='days'
    elif mutation=='bad_period': upstream['duration'].result.output_files['flood_duration']['gis_metadata']['target_period']={}
    elif mutation=='unreviewed': source=replace(source,evidence={'checks':{}})
    else: bindings=replace(bindings,request=bindings.request.model_copy(update={'zonation_options':bindings.request.zonation_options.model_copy(update={'method_reference':'fixture:other'})}))
    sources['policy']=replace(source,data=data)
    with pytest.raises(SourceNotReady): zonation_inputs(replace(bindings,sources=sources,upstream=upstream),aoi)


@pytest.mark.parametrize('change',[{'method':'unknown'},{'factor_units':{'depth':'m','velocity':'m/s'}},{'factor_units':{'depth':'m','velocity':'m/s','duration':'days'}}])
def test_zonation_contract_rejects_invented_or_insufficient_methods(change):
    definition=policy_source().manifest.zonation_policy.model_dump();definition.update(change)
    with pytest.raises(ValidationError): ZonationDefinition.model_validate({key:value for key,value in definition.items() if key!='reference_periods'})


def test_m01_scene_identity_hashes_actual_provider_metadata_and_checks_collection():
    metadata=scene('Sentinel-1');metadata['id']='COPERNICUS/S1_GRD/synthetic'
    collection=MagicMock();collection.size.return_value.getInfo.return_value=1;collection.toList.return_value.getInfo.return_value=[metadata]
    kwargs={'sensor':'Sentinel-1','period':{'start':'2024-03-01','end':'2024-04-01'},'aoi':AOI,'required_bands':['VV'],'collection_id':'COPERNICUS/S1_GRD'}
    result=inspect_collection(collection,**kwargs)['scenes'][0]
    assert result['metadata_sha256']==hashlib.sha256(json.dumps(metadata,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    assert result['provider_source_byte_sha256'] is None
    assert result['acquired_at_utc'].startswith('2024-03-05')
    metadata['id']='unreviewed/synthetic'
    with pytest.raises(ValueError,match='collection'): inspect_collection(collection,**kwargs)


@pytest.mark.parametrize('mutation',['asset','band','duplicate','grid'])
def test_static_provider_sources_require_actual_asset_band_and_grid(mutation):
    metadata={'id':'synthetic/DEM','bands':[{'id':'elevation','crs':'EPSG:3857','crs_transform':[30,0,0,0,-30,100]}]}
    image=MagicMock();image.getInfo.return_value=metadata
    assert inspect_static_image(image,asset_id='synthetic/DEM',required_band='elevation')['provider_source_byte_sha256'] is None
    if mutation=='asset': metadata['id']='other'
    elif mutation=='band': metadata['bands'][0]['id']='other'
    elif mutation=='duplicate': metadata['bands']*=2
    else: metadata['bands'][0]['crs_transform'][0]=0
    with pytest.raises(ValueError): inspect_static_image(image,asset_id='synthetic/DEM',required_band='elevation')


@pytest.mark.parametrize('factor,unit',[('aep','annual_probability_0_1'),('exposure','index_0_1')])
def test_zonation_additional_factors_retain_explicit_probability_and_index_semantics(tmp_path,factor,unit):
    bindings,aoi=zonation_fixture(tmp_path);source=bindings.sources['policy'];definition=source.manifest.zonation_policy.model_dump(mode='json')
    definition['factor_units'].pop('duration');definition['factor_units'][factor]=unit
    reference={'start':'2010-01-01T00:00:00Z','end':'2019-12-31T23:59:59Z'}
    definition['reference_periods']={'aep':reference} if factor=='aep' else {}
    policy=type(source.manifest.zonation_policy).model_validate(definition)
    source=replace(source,data=source.data.replace(b'duration',factor.encode()),manifest=source.manifest.model_copy(update={'zonation_policy':policy}))
    ready=bindings.upstream['duration'];key='flood_'+factor
    path=tmp_path/'factor.tif';write_cog(str(path),np.full((4,4),.25),RasterSpec.from_bounds(300,700,100,3857),nodata=-9999)
    meta={'units':unit,'target_period':policy.reference_periods['aep'].model_dump(mode='json') if factor=='aep' else TARGET,'result_version':1}
    ready=SimpleNamespace(result=SimpleNamespace(version=1,output_files={key:{'gis_metadata':meta}}),artifacts={key:({'gis_metadata':meta},path.read_bytes())})
    upstream={key:value for key,value in bindings.upstream.items() if key!='duration'};upstream[factor]=ready
    current=replace(bindings,sources={'policy':source},upstream=upstream)
    values=zonation_inputs(current,aoi)[4]
    assert values[factor].tolist()==[.25]*16
    assert policy.factor_units[factor]==unit
    meta['target_period']={}
    with pytest.raises(SourceNotReady,match='temporal'): zonation_inputs(current,aoi)


def test_reviewed_zonation_delivered_tables_preserve_sourced_labels_and_zero_classes(tmp_path):
    bindings,aoi=zonation_fixture(tmp_path);source=bindings.sources['policy']
    definition=source.manifest.zonation_policy.model_dump(mode='json')
    definition['classes']['3']={'label':'Synthetic unobserved class','color':'#008800'}
    policy=type(source.manifest.zonation_policy).model_validate(definition)
    data=source.data+b'synthetic-3,depth,100,200,3,2021-06-01T00:00:00Z,valid\nsynthetic-3,velocity,0,100,3,2021-06-01T00:00:00Z,valid\nsynthetic-3,duration,0,100,3,2021-06-01T00:00:00Z,valid\n'
    source=replace(source,data=data,manifest=source.manifest.model_copy(update={'zonation_policy':policy,'sha256':hashlib.sha256(data).hexdigest()}))
    output=execute_reviewed_map(replace(bindings,sources={'policy':source}),aoi,tmp_path/'zero',1,task_id='synthetic')
    assert output.summary['class_statistics'][2]['cell_count']==0
    assert output.summary['class_statistics'][2]['class']=='Synthetic unobserved class'
    rows=output.summary['delivery']['class_areas']
    assert next(row for row in rows if row['label']=='Synthetic unobserved class')['cells']==0


@pytest.mark.parametrize('bad_bands',[None,[None],[{'id':'elevation'},{'id':'elevation'}]])
def test_static_malformed_band_metadata_is_rejected(bad_bands):
    image=MagicMock();image.getInfo.return_value={'id':'synthetic/DEM','bands':bad_bands}
    with pytest.raises(ValueError): inspect_static_image(image,asset_id='synthetic/DEM',required_band='elevation')


@pytest.mark.parametrize('size,payload,expected',[(3,b'abc',True),(4,b'abc',False),(0,b'',False)])
def test_m01_received_download_length_and_stream_close_are_verified(tmp_path,monkeypatch,size,payload,expected):
    from app.services.gee import firris_pipeline as pipeline
    response=MagicMock();response.headers={'content-length':str(size)};response.iter_content.return_value=[payload]
    monkeypatch.setattr(pipeline.requests,'get',lambda *args,**kwargs:response)
    image=MagicMock();image.getDownloadURL.return_value='https://synthetic.invalid/export'
    if expected:
        assert pipeline._download_image(image,{},tmp_path/'received',scale=30,crs='EPSG:3857').read_bytes()==payload
    else:
        with pytest.raises(ValueError): pipeline._download_image(image,{},tmp_path/'received',scale=30,crs='EPSG:3857')
    response.close.assert_called_once()


def test_m01_metadata_hash_is_reproducible_from_persisted_provider_metadata():
    from app.services.gee.scene_qa import metadata_identity
    native=scene('Sentinel-1');record=metadata_identity(native)
    assert record['metadata_sha256']==hashlib.sha256(json.dumps(record['provider_metadata'],sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    assert record['provider_source_byte_sha256'] is None


def test_m01_unreadable_received_export_retains_fail_closed_quality_state(monkeypatch,tmp_path):
    from app.services.gee import firris_pipeline as pipeline
    def unreadable(*args,**kwargs): raise rasterio.errors.RasterioIOError('synthetic corrupt export')
    monkeypatch.setattr(pipeline,'_fetch_feature_stack',unreadable)
    with pytest.raises(pipeline.FIRRISQualityError) as caught: pipeline.fetch_feature_stack({},AOI,tmp_path)
    assert caught.value.quality_record['analysis_inputs_released'] is False


def test_m01_provider_metadata_is_snapshotted_without_claiming_pixel_checksums():
    from app.services.gee.scene_qa import metadata_identity
    native=scene('Sentinel-1');record=metadata_identity(native);native['id']='changed'
    assert record['provider_metadata']['id']!='changed'
    assert record['provider_source_byte_sha256'] is None
