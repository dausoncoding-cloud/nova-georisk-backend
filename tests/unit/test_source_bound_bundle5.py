"""Synthetic mechanics only: no field observations, calibrated policies or forecast skill."""
import json
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from pydantic import ValidationError

from app.schemas.source_bindings import SourceBoundAnalysisRequest
from app.schemas.firris_evidence import LiveEventRequest, LiveFeedPolicy, ValidationDefinition, ImpactDefinition
from app.services.source_data.bindings import ResolvedBindings, EVIDENCE_MODULES, binding_contract
from app.services.source_data.readiness import ReadySource, SourceNotReady
from app.services.source_data.evidence_products import validation_arrays, domain_records, execute_evidence_products
from app.services.source_data.live import evaluate_event
from app.services.source_data.validators import validate_source_data, SourceDataValidationError
from app.services.validation.diagnostics import continuous_diagnostics, binary_diagnostics, write_diagnostic_artifacts
from app.services.validation.regression_metrics import compute_regression_metrics
from tests.unit.test_firris_source_data import manifest
from tests.unit.test_source_bound_hazard import _fixture

REF = 'fixture:synthetic-bundle5-not-scientific'
INSTANT = '2020-06-01T00:00:00Z'
PERIOD = {'start':INSTANT,'end':INSTANT}


def evidence_source(category,data,**overrides):
    m=manifest(category,data,**overrides)
    filename='synthetic.tif' if m.spatial_resolution else 'synthetic.geojson'
    validate_source_data(m,data,filename)
    checks={key:True for key in ('validation_definition_verified','independent_observations_verified','scoring_policy_verified','impact_definition_verified','dss_definitions_verified','live_policy_verified')}
    return ReadySource(SimpleNamespace(id=uuid.uuid4(),created_at=None),m,data,{'analysis_ready':True,'checks':checks,'evidence_refs':[REF]})


def raster(values):
    with MemoryFile() as memory:
        with memory.open(driver='GTiff',width=4,height=4,count=1,dtype='float64',crs='EPSG:3857',transform=from_origin(300,700,100,100),nodata=-9999) as dst:
            dst.write(np.asarray(values,dtype='float64').reshape(4,4),1)
        return memory.read()


def fixture(module, *, optional=False):
    original,aoi,_=_fixture()
    sources={}
    if module.endswith('_validation'):
        binary=module=='classification_validation'
        observed=np.arange(16,dtype=float)%2 if binary else np.arange(16,dtype=float)
        predicted=np.roll(observed,1) if binary else observed+np.linspace(-1,1,16)
        roles={'observed':observed,'predicted':predicted}
        if optional: roles.update(uncertainty=np.ones(16)*.2,folds=np.arange(16)%2,baseline=predicted.copy())
        if binary and optional: roles['score']=np.where(predicted==1,.8,.2)
        for role,values in roles.items():
            category = 'validation_'+('binary_' if binary else 'continuous_')+('observation' if role=='observed' else 'prediction') if role in {'observed','predicted','baseline'} else 'validation_'+('probability' if role=='score' else role)
            definition={'quantity_id':'synthetic_flood' if binary else 'synthetic_depth','definition':'Synthetic fixture comparison quantity','value_units':'binary_class_0_1' if binary else 'm',
                        'comparison_reference':REF,'evaluation_scope':'not_independent','model_reference':None if role in {'observed','folds'} else REF+'-model',
                        'class_labels':{'0':'Synthetic absent','1':'Synthetic present'} if binary else None,
                        'uncertainty_kind':'standard_deviation' if role=='uncertainty' else None,'fold_definitions':{'0':'Synthetic fold A','1':'Synthetic fold B'} if role=='folds' else None,
                        'decision_threshold':.5 if binary else None,'hotspot_absolute_error_threshold':2 if optional and role=='predicted' else None,'hotspot_policy_reference':REF if optional and role=='predicted' else None}
            if role=='uncertainty': definition['value_units']='binary_class_0_1' if binary else 'm'
            if role=='score': definition['value_units']='conditional_class_probability_0_1'
            if role=='folds': definition['value_units']='fold_code'
            period={'start':'2019-06-01T00:00:00Z','end':'2019-06-01T00:00:00Z'} if role=='baseline' else PERIOD
            sources[role]=evidence_source(category,raster(values),crs='EPSG:3857',spatial_resolution={'x':100,'y':100,'unit':'m'},validation_definition=definition,temporal_coverage=period)
    else:
        category='dss_records' if module=='decision_support' else 'flood_impact_records'
        definitions={domain:{'domain':domain,'units':'count','definition':'Synthetic supplied measurement','evidence_reference':REF} for domain in ('community','infrastructure','event','kpi')}
        rows=[{'record_id':'synthetic-'+domain,'metric_key':domain,'domain':domain,'value':i,'unit':'count','observed_at':INSTANT,'source_record_reference':REF,'quality_flag':'valid'} for i,domain in enumerate(definitions)] if module=='decision_support' else [{'record_id':'synthetic-impact','households':3,'loss_amount':12.5,'currency':'KES','observed_at':INSTANT,'source_record_reference':REF,'quality_flag':'valid'}]
        features=[{'type':'Feature','geometry':{'type':'Point','coordinates':[.0045,.0045]},'properties':row} for row in rows]
        data=json.dumps({'type':'FeatureCollection','features':features}).encode()
        kwargs={'dss_metric_definitions':definitions} if module=='decision_support' else {'impact_definition':{'basis':'observed','definition':'Synthetic household and loss records','evidence_reference':REF,'currency':'KES'}}
        sources['records' if module=='decision_support' else 'impacts']=evidence_source(category,data,temporal_coverage=PERIOD,**kwargs)
    request=SourceBoundAnalysisRequest(project_id=original.project_id,aoi_id=original.aoi_id,module=module,sources={role:source.dataset.id for role,source in sources.items()},
        upstream_results={role:uuid.uuid4() for role in ('hazard','exposure','vulnerability','insecurity','risk','resilience')} if module=='prediction_outputs' else {},period=PERIOD,target_grid=original.target_grid if module.endswith('_validation') else None)
    return request,aoi,sources


@pytest.mark.parametrize('module', sorted(EVIDENCE_MODULES))
def test_source_contract_is_explicit_and_executable(module):
    contract=binding_contract()[module]
    assert contract['executable'] and contract['source_roles']
    request,_,sources=fixture(module)
    assert set(request.sources)==set(contract['source_roles'])
    assert all(source.manifest.provenance.source_uri=='fixture:synthetic' for source in sources.values())


@pytest.mark.parametrize('module', ['continuous_validation','classification_validation'])
@pytest.mark.parametrize('optional', [False,True])
def test_validation_exports_actual_maps_plots_and_unavailable_states(tmp_path,module,optional):
    request,aoi,sources=fixture(module,optional=optional)
    result=execute_evidence_products(ResolvedBindings(request,sources,{}),aoi,tmp_path,2,task_id='synthetic')
    dashboard=result.summary['validation_dashboard']
    assert dashboard['kind']==('continuous' if module=='continuous_validation' else 'binary')
    assert dashboard['availability']['uncertainty']['available']==optional
    assert dashboard['availability']['hotspot']['available']==optional
    assert bool(dashboard['plots'])
    assert result.output_files['validation_report']['checksum_sha256']
    with rasterio.open(tmp_path/'observed.cog.tif') as src: np.testing.assert_array_equal(src.read(1),np.arange(16).reshape(4,4)%2 if module=='classification_validation' else np.arange(16).reshape(4,4))
    if optional:
        assert 'prediction_change' in result.output_files and 'hotspot' in result.output_files
        assert all(fold['count']==8 for fold in dashboard['metrics']['declared_folds'].values())
    else:
        assert 'uncertainty' not in result.output_files and 'hotspot' not in result.output_files
    if module=='continuous_validation':
        with rasterio.open(tmp_path/'relative_error.cog.tif') as src: assert src.read(1,masked=True).mask[0,0]
    else: assert dashboard['availability']['multiclass']['available'] is False


@pytest.mark.parametrize('field,value', [('quantity_id','different'),('definition','Different synthetic measurement'),('value_units','cm'),('comparison_reference','fixture:different'),('evaluation_scope','declared_holdout')])
def test_comparison_semantics_fail_closed(field,value):
    request,aoi,sources=fixture('continuous_validation')
    observed=sources['observed']
    definition=observed.manifest.validation_definition.model_copy(update={field:value})
    sources['observed']=replace(observed,manifest=observed.manifest.model_copy(update={'validation_definition':definition}))
    with pytest.raises(SourceNotReady): validation_arrays(ResolvedBindings(request,sources,{}),aoi)


@pytest.mark.parametrize('role', ['observed','predicted','uncertainty','folds','baseline'])
def test_missing_explicit_source_review_fails(role):
    request,aoi,sources=fixture('continuous_validation',optional=True)
    sources[role]=replace(sources[role],evidence={'checks':{},'evidence_refs':[REF]})
    with pytest.raises(SourceNotReady): validation_arrays(ResolvedBindings(request,sources,{}),aoi)


def test_validation_grid_time_model_and_nodata_are_not_silently_repaired():
    request,aoi,sources=fixture('classification_validation',optional=True)
    for role,changed in [('score',{'model_reference':'fixture:other-model'}),('baseline',{'class_labels':{'0':'Other absent','1':'Other present'}})]:
        altered=dict(sources)
        source=altered[role]
        altered[role]=replace(source,manifest=source.manifest.model_copy(update={'validation_definition':source.manifest.validation_definition.model_copy(update=changed)}))
        with pytest.raises(SourceNotReady): validation_arrays(ResolvedBindings(request,altered,{}),aoi)
    altered=dict(sources)
    altered['score']=replace(sources['score'],data=raster(np.ones(16)*.9))
    with pytest.raises(SourceNotReady,match='threshold'): validation_arrays(ResolvedBindings(request,altered,{}),aoi)
    altered=dict(sources)
    values=np.ones(16);values[0]=-9999
    altered['observed']=replace(sources['observed'],data=raster(values))
    with pytest.raises(SourceNotReady,match='incomplete'): validation_arrays(ResolvedBindings(request,altered,{}),aoi)
    grid=request.target_grid.model_copy(update={'width':5})
    with pytest.raises(SourceNotReady,match='grid'): validation_arrays(ResolvedBindings(request.model_copy(update={'target_grid':grid}),sources,{}),aoi)


def test_independent_evidence_cannot_reuse_declared_training_dataset():
    request,aoi,sources=fixture('continuous_validation')
    for role,source in sources.items():
        d=source.manifest.validation_definition.model_copy(update={'evaluation_scope':'reviewed_independent','training_dataset_ids':[sources['observed'].dataset.id]})
        sources[role]=replace(source,manifest=source.manifest.model_copy(update={'validation_definition':d}))
    with pytest.raises(SourceNotReady,match='training'): validation_arrays(ResolvedBindings(request,sources,{}),aoi)


@pytest.mark.parametrize('bad', [np.nan,np.inf,-.1,1.1])
def test_probability_contract_rejects_invalid_scores(bad):
    with pytest.raises(ValueError): binary_diagnostics([0,1,0,1],[0,1,1,0],[.1,.9,bad,.8])


def test_full_regression_metrics_use_existing_approved_formulas():
    observed=np.array([0,1,2,3,4.]);predicted=np.array([.2,.5,2,4,3.])
    d=continuous_diagnostics(observed,predicted)
    approved=compute_regression_metrics(observed,predicted)
    for key,value in vars(approved).items(): assert d['metrics'][key]==pytest.approx(value)
    assert d['availability']['percentage_errors']['denominator']==4


def test_constant_truth_and_missing_class_remain_undefined():
    d=continuous_diagnostics([0,0,0],[1,1,1])
    assert d['availability']['percentage_errors']['available'] is False
    assert d['metrics']['mape'] is None
    b=binary_diagnostics([0,0,0],[0,1,0],[.1,.9,.2])
    assert b['metrics']['roc_auc'] is None and b['metrics']['recall'] is None
    assert b['availability']['roc_precision_recall_threshold_sweep']['available'] is False


def test_roc_pr_imbalance_and_actual_thresholds_preserve_binary_formulas():
    observed=np.array([0,0,0,1,1]);predicted=np.array([0,0,1,1,0]);scores=np.array([.1,.2,.8,.9,.4])
    d=binary_diagnostics(observed,predicted,scores)
    assert d['metrics']['class_support']=={'0':3,'1':2}
    assert d['metrics']['confusion']=={'tp':1,'tn':2,'fp':1,'fn':1}
    from app.services.validation.classification_metrics import compute_classification_metrics
    for record in d['curves']['thresholds']:
        expected=compute_classification_metrics(observed,(scores>=record['threshold']).astype(int))
        assert record['confusion']==vars(expected.confusion)
    assert [p['threshold'] for p in d['curves']['thresholds']]==list(np.unique(scores))


@pytest.mark.parametrize('module', ['decision_support','prediction_outputs'])
def test_domain_records_are_source_defined_and_not_spatially_apportioned(module):
    request,aoi,sources=fixture(module)
    source,features=domain_records(ResolvedBindings(request,sources,{}),aoi)
    assert source.manifest.provenance.acquisition_method=='synthetic unit fixture'
    data=json.loads(source.data);data['features'][0]['geometry']={'type':'Polygon','coordinates':[[[0,0],[.01,0],[.01,.01],[0,.01],[0,0]]]}
    role=next(iter(sources));sources[role]=replace(source,data=json.dumps(data).encode())
    with pytest.raises(SourceNotReady,match='apportionment'): domain_records(ResolvedBindings(request,sources,{}),aoi)


def test_dss_domain_tables_retain_units_zero_values_and_source_identity(tmp_path):
    request,aoi,sources=fixture('decision_support')
    output=execute_evidence_products(ResolvedBindings(request,sources,{}),aoi,tmp_path,1,task_id='synthetic')
    dashboard=output.summary['decision_support']
    assert dashboard['tables']['community'][0]['value']==0
    assert dashboard['tables']['kpi'][0]['unit']=='count'
    assert dashboard['source_identity']['sha256']==sources['records'].manifest.sha256
    assert dashboard['source_identity']['measurement_definitions']['kpi']['evidence_reference']==REF


@pytest.mark.parametrize('category', ['sensor_registry','dss_records','flood_impact_records'])
def test_duplicate_source_identities_rejected_at_registration(category):
    if category=='sensor_registry': source,_=live_fixture()
    else:
        _,_,sources=fixture('decision_support' if category=='dss_records' else 'prediction_outputs');source=next(iter(sources.values()))
    document=json.loads(source.data);document['features'].append(document['features'][0]);data=json.dumps(document).encode()
    import hashlib
    m=source.manifest.model_copy(update={'sha256':hashlib.sha256(data).hexdigest()})
    with pytest.raises(SourceDataValidationError,match='Duplicate'): validate_source_data(m,data,'synthetic.geojson')


def live_fixture(now=None):
    now=now or datetime(2020,6,1,tzinfo=timezone.utc)
    data=json.dumps({'type':'FeatureCollection','features':[{'type':'Feature','geometry':{'type':'Point','coordinates':[36.5,-1.5]},'properties':{'sensor_id':'synthetic-gauge','quantity_id':'synthetic_stage','unit':'m','observed_at':now.isoformat(),'quality_flag':'valid'}}]}).encode()
    policy={'policy_reference':REF,'max_lateness_seconds':60,'max_future_skew_seconds':5,'max_nowcast_horizon_seconds':300,'nowcast_model_references':[REF+'-model'],
            'alert_rules':{'synthetic-rule':{'sensor_id':'synthetic-gauge','operator':'ge','threshold':4,'units':'m','label':'Synthetic threshold; not an approved operational safety rule'}}}
    source=evidence_source('sensor_registry',data,temporal_coverage={'start':(now-timedelta(days=1)).isoformat(),'end':(now+timedelta(days=1)).isoformat()},live_feed_policy=policy)
    sensors={'synthetic-gauge':json.loads(data)['features'][0]['properties']}
    return source,sensors


def live_event(source,now=None,**changes):
    now=now or datetime(2020,6,1,tzinfo=timezone.utc)
    values={'policy_dataset_id':source.dataset.id,'event_id':'synthetic-event','sensor_id':'synthetic-gauge','kind':'observation','quality_flag':'valid','value':4,'units':'m','valid_at':now,'issued_at':now,'source_record_reference':REF}
    values.update(changes)
    return LiveEventRequest(**values)


@pytest.mark.parametrize('operator,value,expected', [('gt',4,False),('ge',4,True),('lt',3,True),('le',4,True)])
def test_alerts_use_only_the_supplied_reviewed_comparison(operator,value,expected):
    source,sensors=live_fixture();policy=source.manifest.live_feed_policy
    rule=policy.alert_rules['synthetic-rule'].model_copy(update={'operator':operator})
    source=replace(source,manifest=source.manifest.model_copy(update={'live_feed_policy':policy.model_copy(update={'alert_rules':{'synthetic-rule':rule}})}))
    alerts=evaluate_event(source,sensors,live_event(source,value=value),datetime(2020,6,1,tzinfo=timezone.utc))
    assert bool(alerts)==expected
    if alerts: assert alerts[0]['scientific_validation']=='not_asserted'


@pytest.mark.parametrize('changes', [{'sensor_id':'unknown'},{'units':'cm'},{'issued_at':datetime(2019,1,1,tzinfo=timezone.utc),'valid_at':datetime(2019,1,1,tzinfo=timezone.utc)},
    {'kind':'nowcast','valid_at':datetime(2020,6,1,0,6,tzinfo=timezone.utc),'model_reference':REF+'-model'},
    {'kind':'nowcast','valid_at':datetime(2020,6,1,0,1,tzinfo=timezone.utc),'model_reference':'fixture:unknown-model'}])
def test_unsupported_live_inputs_fail_closed(changes):
    source,sensors=live_fixture()
    with pytest.raises(SourceNotReady): evaluate_event(source,sensors,live_event(source,**changes),datetime(2020,6,1,tzinfo=timezone.utc))


@pytest.mark.parametrize('shift', [-61,6])
def test_live_lateness_and_future_skew_are_bound_policy_limits(shift):
    source,sensors=live_fixture();now=datetime(2020,6,1,tzinfo=timezone.utc)
    with pytest.raises(SourceNotReady): evaluate_event(source,sensors,live_event(source,now=now+timedelta(seconds=shift)),now)


def test_supported_nowcast_is_externally_supplied_not_a_claim_of_model_skill():
    source,sensors=live_fixture();now=datetime(2020,6,1,tzinfo=timezone.utc)
    event=live_event(source,kind='nowcast',valid_at=now+timedelta(seconds=120),model_reference=REF+'-model')
    assert evaluate_event(source,sensors,event,now)[0]['event_kind']=='nowcast'


@pytest.mark.parametrize('value', [np.nan,np.inf,-np.inf])
def test_nonfinite_live_values_and_policy_thresholds_rejected(value):
    source,_=live_fixture()
    with pytest.raises(ValidationError): live_event(source,value=value)
    policy=source.manifest.live_feed_policy.model_dump();policy['alert_rules']['synthetic-rule']['threshold']=value
    with pytest.raises(ValidationError): LiveFeedPolicy(**policy)


def test_evidence_contracts_do_not_allow_guessed_hotspots_multiclass_or_modelled_loss():
    with pytest.raises(ValidationError): ValidationDefinition(quantity_id='synthetic',definition='Synthetic quantity',value_units='m',comparison_reference=REF,evaluation_scope='not_independent',hotspot_absolute_error_threshold=2)
    with pytest.raises(ValueError): binary_diagnostics([0,1,2],[0,1,2])
    with pytest.raises(ValidationError): ImpactDefinition(basis='externally_modelled',definition='Synthetic impact record',currency='KES',evidence_reference=REF)


def mlr_fixture():
    import csv
    import io
    from app.services.source_data.catalogue import get_profile
    from app.services.source_data.bundle4 import reviewed_policy
    from tests.unit.test_source_bound_bundle4 import source as csv_ready_source
    from pyproj import Transformer
    original,aoi,_=_fixture()
    families=['climate','hydrology','remote_sensing','terrain','land_cover','buffering']
    keys=['synthetic_'+family for family in families]
    definitions={key:{'role':'predictor','family':family,'unit':'synthetic_unit','definition':'Synthetic measured '+family,'evidence_ref':REF} for key,family in zip(keys,families)}
    definitions['synthetic_response']={'role':'response','family':'hydrology','unit':'synthetic_unit','definition':'Synthetic supplied continuous response','evidence_ref':REF}
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(get_profile('flood_predictor_observations')['required_fields']));writer.writeheader()
    rng=np.random.default_rng(15);values=rng.normal(size=(60,6));responses=values@np.arange(1,7)+rng.normal(size=60)
    lon,lat=Transformer.from_crs('EPSG:3857','EPSG:4326',always_xy=True).transform(500,500)
    for i,row in enumerate(values):
        stamp=(datetime(2020,1,1,tzinfo=timezone.utc)+timedelta(days=i)).isoformat()
        for key,value in {**dict(zip(keys,row)), 'synthetic_response':responses[i]}.items():
            writer.writerow({'sample_id':'synthetic-'+str(i),'variable':key,'longitude':lon,'latitude':lat,'observed_at':stamp,'value':value,'unit':'synthetic_unit','quality_flag':'valid'})
    data=stream.getvalue().encode()
    m=manifest('flood_predictor_observations',data,predictor_definitions=definitions,predictor_catalogue_reference=REF)
    validate_source_data(m,data,'synthetic.csv')
    source=ReadySource(SimpleNamespace(id=uuid.uuid4(),created_at=None),m,data,{'analysis_ready':True,'evidence_refs':[REF],'checks':{'predictor_catalogue_verified':True}})
    request=SourceBoundAnalysisRequest(project_id=original.project_id,aoi_id=original.aoi_id,module='predictor_mlr',sources={'observations':source.dataset.id},period={'start':'2020-01-01T00:00:00Z','end':'2020-12-31T23:59:59Z'},
        predictor_options={'response':'synthetic_response','predictor_order':keys,'vif_limit':10,'holdout_fraction':.2})
    return request,aoi,{'observations':source}


def test_full_six_family_mlr_is_existing_executable_path_and_exports_observed_holdout_diagnostics(tmp_path):
    from app.services.source_data.bundle4 import execute_bundle4
    request,aoi,sources=mlr_fixture()
    output=execute_bundle4(ResolvedBindings(request,sources,{}),aoi,tmp_path,1,task_id='synthetic')
    processing=output.summary['processing']
    assert set(d['family'] for d in processing['predictor_definitions'].values())=={'climate','hydrology','remote_sensing','terrain','land_cover','buffering'}
    assert processing['holdout_count']==12 and processing['training_count']==48
    assert len(processing['selected_predictors'])==6
    assert output.summary['validation_dashboard']['units']=='synthetic_unit'
    assert len(output.summary['validation_dashboard']['plots'])>=5
    assert 'validation_report' in output.output_files
    assert 'raw_observations' in output.output_files and 'holdout_predictions' in output.output_files


def test_two_pair_mlr_holdout_preserves_existing_contract_and_marks_full_metrics_unavailable(tmp_path):
    from tests.unit.test_source_bound_bundle4 import fixture as bundle4_fixture
    from app.services.source_data.bundle4 import execute_bundle4
    request,aoi,sources=bundle4_fixture('predictor_mlr')
    options=request.predictor_options.model_copy(update={'holdout_fraction':.04})
    output=execute_bundle4(ResolvedBindings(request.model_copy(update={'predictor_options':options}),sources,{}),aoi,tmp_path,1,task_id='synthetic')
    assert output.summary['processing']['holdout_count']==2
    assert output.summary['validation_dashboard']['availability']['full_regression_metrics']['available'] is False


def test_legacy_source_fingerprints_remain_compatible_but_supplied_definitions_are_pinned():
    import hashlib
    from app.services.source_data.change import comparison_source_fingerprint
    _,_,legacy=_fixture()
    source=legacy['terrain']
    historical=source.manifest.model_dump(mode='json')
    for field in ('validation_definition','impact_definition','dss_metric_definitions','live_feed_policy','susceptibility_method','raster_predictor','zonation_policy'): historical.pop(field)
    expected=hashlib.sha256(json.dumps(historical,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    assert comparison_source_fingerprint(source)==expected
    _,_,sources=fixture('continuous_validation')
    current=sources['predicted']
    original=comparison_source_fingerprint(current)
    updated=current.manifest.validation_definition.model_copy(update={'model_reference':'fixture:changed-model'})
    assert comparison_source_fingerprint(replace(current,manifest=current.manifest.model_copy(update={'validation_definition':updated})))!=original


@pytest.mark.parametrize('flag', ['suspect','rejected','missing'])
def test_live_observations_require_explicit_producer_valid_quality(flag):
    source,_=live_fixture()
    with pytest.raises(ValidationError): live_event(source,quality_flag=flag)


@pytest.mark.parametrize('field,value', [('households',-1),('households',.5),('households','3'),('loss_amount',True),('currency','USD')])
def test_impact_counts_currency_and_numeric_types_fail_closed(field,value):
    import hashlib
    _,_,sources=fixture('prediction_outputs');source=sources['impacts']
    document=json.loads(source.data);document['features'][0]['properties'][field]=value
    data=json.dumps(document).encode();m=source.manifest.model_copy(update={'sha256':hashlib.sha256(data).hexdigest()})
    with pytest.raises(SourceDataValidationError): validate_source_data(m,data,'synthetic.geojson')


@pytest.mark.parametrize('role,units', [('score','annual_probability'),('uncertainty','cm'),('folds','index')])
def test_optional_validation_units_are_measure_specific(role,units):
    request,aoi,sources=fixture('classification_validation',optional=True)
    source=sources[role]
    definition=source.manifest.validation_definition.model_copy(update={'value_units':units})
    sources[role]=replace(source,manifest=source.manifest.model_copy(update={'validation_definition':definition}))
    with pytest.raises(SourceNotReady): validation_arrays(ResolvedBindings(request,sources,{}),aoi)
