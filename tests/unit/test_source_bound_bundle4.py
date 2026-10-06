"""Synthetic Bundle 4 mechanics; scores/observations are NOT scientific evidence."""
import csv
import io
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import rasterio
from pydantic import ValidationError
from pyproj import Transformer

from app.schemas.source_bindings import SourceBoundAnalysisRequest
from app.schemas.source_data import SoilScoringPolicy
from app.schemas.source_data import ProximityPolicy
from app.services.source_data.bindings import BUNDLE4_MODULES, ResolvedBindings, resolve_bindings
from app.services.source_data.bundle4 import compute_bundle4, execute_bundle4
from app.services.source_data.readiness import ReadySource, SourceNotReady
from app.services.source_data.validators import SourceDataValidationError, validate_source_data
from tests.unit.test_firris_source_data import manifest
from tests.unit.test_source_bound_hazard import _fixture, _raster

SYNTHETIC_REF = 'fixture:synthetic-bundle4-policy-not-scientific'
WGS = Transformer.from_crs('EPSG:3857', 'EPSG:4326', always_xy=True)
INSTANT = '2020-06-01T00:00:00Z'


def source(category, data, **overrides):
    if category == 'soil_texture_classes':
        overrides.update(crs='EPSG:3857', spatial_resolution={'x': 100, 'y': 100, 'unit': 'm'})
    m = manifest(category, data, **overrides)
    profile_ext = '.tif' if category == 'soil_texture_classes' else '.geojson' if data.startswith(b'{') else '.csv'
    validate_source_data(m, data, 'synthetic'+profile_ext)
    return ReadySource(SimpleNamespace(id=uuid.uuid4(), created_at=None), m, data,
                       {'analysis_ready': True, 'evidence_refs': [SYNTHETIC_REF], 'checks': {
                           'coverage_complete_verified': True, 'annual_record_complete_verified': True,
                           'scoring_policy_verified': True, 'predictor_catalogue_verified': True}})


def csv_source(category, rows, **overrides):
    from app.services.source_data.catalogue import get_profile
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(get_profile(category)['required_fields']))
    writer.writeheader()
    writer.writerows(rows)
    return source(category, stream.getvalue().encode(), **overrides)


def feature(geometry, properties):
    return {'type': 'Feature', 'geometry': geometry, 'properties': properties}


def geo_source(category, features, **overrides):
    return source(category, json.dumps({'type': 'FeatureCollection', 'features': features}).encode(), **overrides)


def fixture(module):
    base, aoi, old = _fixture()
    fields = base.model_dump(mode='json')
    fields.update(module=module, hazard_options=None)
    options = {}
    if module == 'rainfall_interpolation':
        sources = {'rainfall': old['rainfall']}
        options['rainfall_options'] = {'method': 'idw', 'power': 2}
    elif module == 'river_stage':
        rows, thresholds = [], []
        for row in csv.DictReader(io.StringIO(old['rainfall'].data.decode())):
            common = {key: row[key] for key in ('station_id', 'longitude', 'latitude', 'observed_at', 'quality_flag')}
            rows.append({**common, 'stage_m': float(row['rainfall_mm']) / 10})
            thresholds.append({**common, 'bankfull_stage_m': 2, 'threshold_reference': SYNTHETIC_REF})
        sources = {'gauges': csv_source('river_stage_stations', rows), 'thresholds': csv_source('river_stage_thresholds', thresholds)}
    elif module == 'feature_proximity':
        rivers = old['river_network']
        rivers.evidence.update(evidence_refs=[SYNTHETIC_REF], checks={'coverage_complete_verified': True, 'scoring_policy_verified': True})
        services = geo_source('critical_infrastructure', [feature({'type': 'Point', 'coordinates': list(WGS.transform(400, 450))},
            {'asset_id': 'synthetic-clinic', 'asset_type': 'clinic', 'observed_at': INSTANT, 'quality_flag': 'valid'})])
        sources = {'rivers': rivers, 'services': services}
        options['proximity_options'] = {'normalization': 'aoi_minmax_entropy', 'river_direction': 'cost', 'service_direction': 'benefit', 'policy_reference': SYNTHETIC_REF}
        for item in sources.values():
            item.manifest.proximity_scoring_policy = ProximityPolicy.model_validate(options['proximity_options'])
    elif module == 'watershed':
        outlets = geo_source('watershed_outlets', [feature({'type': 'Point', 'coordinates': list(WGS.transform(650, 350))},
            {'outlet_id': 'synthetic-outlet', 'observed_at': INSTANT, 'quality_flag': 'valid'})])
        sources = {'terrain': old['terrain'], 'outlets': outlets}
    elif module == 'soil_infiltration':
        classes = np.tile(np.arange(1, 6), (10, 2))
        soil = source('soil_texture_classes', _raster(classes))
        soil.manifest.soil_scoring_policy.specification_reference = SYNTHETIC_REF
        sources = {'soil': soil}
    elif module == 'historical_frequency':
        start = datetime(2010, 1, 1, tzinfo=timezone.utc)
        end = datetime(2019, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        fields.update(period={'start': start.isoformat(), 'end': end.isoformat()}, target_grid=None)
        period = fields['period']
        longitude, latitude = WGS.transform(500, 500)
        rows = [{'station_id': 'synthetic-discharge', 'longitude': longitude, 'latitude': latitude,
                 'observed_at': (start+timedelta(days=i)).isoformat(), 'discharge_m3_s': 10+(start+timedelta(days=i)).year-2010+i%7,
                 'quality_flag': 'valid'} for i in range((datetime(2020, 1, 1, tzinfo=timezone.utc)-start).days)]
        discharge = csv_source('river_discharge_stations', rows, temporal_coverage=period, observation_interval_hours=24,
                               historical_record_definition='Synthetic daily observed discharge; not instantaneous peak')
        event = feature(aoi, {'event_id': 'synthetic-event', 'source_record_id': 'fixture:synthetic-event',
                             'start_at': '2015-06-01T00:00:00Z', 'end_at': '2015-06-02T00:00:00Z', 'quality_flag': 'valid'})
        inventory = geo_source('historical_flood_events', [event], temporal_coverage=period,
                               historical_record_definition='Synthetic vetted event footprint above a fixed test threshold')
        sources = {'discharge': discharge, 'inventory': inventory}
    elif module == 'predictor_mlr':
        fields.update(period={'start': '2020-01-01T00:00:00Z', 'end': '2020-12-31T23:59:59Z'}, target_grid=None)
        definitions = {key: {'role': 'response' if key == 'flood' else 'predictor', 'family': family,
                            'unit': 'synthetic_unit', 'definition': 'Synthetic numerical observed '+key, 'evidence_ref': SYNTHETIC_REF}
                       for key, family in [('flood', 'hydrology'), ('rain', 'climate'), ('rain_duplicate', 'climate'), ('storage', 'buffering')]}
        rows = []
        for i in range(30):
            rain, storage = i+1, 3+(i*7)%11
            values = {'rain': rain, 'rain_duplicate': 2*rain, 'storage': storage, 'flood': 5+2*rain+3*storage+np.sin(i)}
            for key, value in values.items():
                longitude, latitude = WGS.transform(500, 500)
                rows.append({'sample_id': f'synthetic-{i}', 'variable': key, 'longitude': longitude, 'latitude': latitude,
                             'observed_at': f'2020-01-{i+1:02d}T00:00:00Z', 'value': value, 'unit': 'synthetic_unit', 'quality_flag': 'valid'})
        sources = {'observations': csv_source('flood_predictor_observations', rows, predictor_definitions=definitions, predictor_catalogue_reference=SYNTHETIC_REF)}
        options['predictor_options'] = {'response': 'flood', 'predictor_order': ['rain', 'rain_duplicate', 'storage'], 'vif_limit': 5, 'holdout_fraction': .2}
    else:
        raise AssertionError(module)
    fields.update(sources={role: str(item.dataset.id) for role, item in sources.items()}, **options)
    return SourceBoundAnalysisRequest.model_validate(fields), aoi, sources


@pytest.mark.parametrize('module', sorted(BUNDLE4_MODULES))
def test_each_source_workflow_preflights_and_preserves_products(module, tmp_path, monkeypatch):
    request, aoi, sources = fixture(module)
    by_id = {item.dataset.id: item for item in sources.values()}
    monkeypatch.setattr('app.services.source_data.bindings.load_registered_source', lambda _db, dataset_id, _project, **kw: by_id[dataset_id])
    bindings = resolve_bindings(None, request, aoi_geometry=aoi)
    output = execute_bundle4(bindings, aoi, tmp_path, 1, task_id='synthetic-test')
    assert output.result_type == 'source_bound_'+module
    assert output.summary['delivery']
    assert output.summary['interpretation']
    assert output.provenance['source_bindings']
    for entry in output.output_files.values():
        assert (tmp_path / entry['path']).is_file()
    assert 'report_package' in output.output_files
    json.dumps(output.summary, allow_nan=False)


def test_stage_preserves_raw_exceedance_and_shared_datum(tmp_path):
    request, aoi, sources = fixture('river_stage')
    output = execute_bundle4(ResolvedBindings(request, sources, {}), aoi, tmp_path, 1, task_id='synthetic')
    with rasterio.open(tmp_path/'river_stage.cog.tif') as stage, rasterio.open(tmp_path/'bankfull_exceedance.cog.tif') as exceed:
        np.testing.assert_allclose(exceed.read(1), stage.read(1)-2, atol=1e-6)
        assert exceed.read(1).min() < 0  # Existing signed bankfull difference is preserved.
        assert stage.crs.to_string() == 'EPSG:3857' and stage.nodata == -9999
    assert output.summary['processing']['vertical_datum'] == 'EGM2008'


@pytest.mark.parametrize('fault', ['missing', 'different_value', 'different_position', 'different_datum', 'aggregate'])
def test_stage_rejects_incompatible_thresholds(fault):
    request, aoi, sources = fixture('river_stage')
    threshold = sources['thresholds']
    rows = list(csv.DictReader(io.StringIO(threshold.data.decode())))
    if fault == 'missing': rows.pop()
    if fault == 'different_value': rows[0]['bankfull_stage_m'] = 999
    if fault == 'different_position': rows[0]['longitude'] = float(rows[0]['longitude'])+0.001
    if fault == 'different_datum': threshold.manifest.vertical_datum = 'NAVD88'
    if fault == 'aggregate': request.period.end += timedelta(hours=1)
    if fault in {'missing', 'different_value', 'different_position'}:
        sources['thresholds'] = csv_source('river_stage_thresholds', rows)
    with pytest.raises(SourceNotReady): compute_bundle4(request, sources, aoi)


def test_proximity_retains_raw_metric_distances_and_explicit_weights():
    request, aoi, sources = fixture('feature_proximity')
    products, _, _, _, processing, _ = compute_bundle4(request, sources, aoi)
    np.testing.assert_allclose(products['distance_to_rivers'][0][:4], [200, 300, 250, 150], atol=1e-6)
    assert processing['directions'] == {'rivers': 'cost', 'services': 'benefit'}
    assert sum(processing['weights'].values()) == pytest.approx(1)
    assert processing['policy']['policy_reference'] == SYNTHETIC_REF


@pytest.mark.parametrize('module', ['feature_proximity', 'soil_infiltration', 'predictor_mlr'])
@pytest.mark.parametrize('fault', ['review', 'reference'])
def test_scoring_and_catalogue_policies_must_be_explicitly_reviewed(module, fault):
    request, aoi, sources = fixture(module)
    for item in sources.values():
        if fault == 'review': item.evidence['checks'] = {}
        else: item.evidence['evidence_refs'] = ['different:review']
    with pytest.raises(SourceNotReady, match='review'): compute_bundle4(request, sources, aoi)


def test_soil_exact_five_class_lookup_no_default_score():
    request, aoi, sources = fixture('soil_infiltration')
    products, _, _, _, processing, _ = compute_bundle4(request, sources, aoi)
    np.testing.assert_equal(products['soil_infiltration_score'][0], products['soil_texture_class'][0])
    assert len(processing['class_cell_counts']) == 5
    assert processing['class_cell_counts']['1'] > 0
    invalid = _raster(np.full((10, 10), 6))
    with pytest.raises(SourceDataValidationError, match='Soil texture'): source('soil_texture_classes', invalid)
    with pytest.raises(SourceDataValidationError): source('soil_texture_classes', _raster(np.full((10, 10), 1.5)))


@pytest.mark.parametrize('fault', ['missing_class', 'nan_score', 'duplicate_label', 'unknown_metadata'])
def test_soil_policy_is_finite_exact_five_and_strict(fault):
    _, _, sources = fixture('soil_infiltration')
    data = sources['soil'].manifest.soil_scoring_policy.model_dump()
    if fault == 'missing_class': data['classes'].pop('1')
    if fault == 'nan_score': data['classes']['1']['score'] = float('nan')
    if fault == 'duplicate_label': data['classes']['1']['label'] = data['classes']['2']['label']
    if fault == 'unknown_metadata': data['invented_accuracy'] = .99
    with pytest.raises(ValidationError): SoilScoringPolicy.model_validate(data)


def test_watershed_keeps_full_upstream_native_basin(tmp_path):
    request, aoi, sources = fixture('watershed')
    output = execute_bundle4(ResolvedBindings(request, sources, {}), aoi, tmp_path, 1, task_id='synthetic')
    with rasterio.open(tmp_path/'watershed_1-native.cog.tif') as native, rasterio.open(tmp_path/'watershed_1.cog.tif') as clipped:
        assert native.shape == (10, 10) and clipped.shape == (4, 4)
        assert native.read(1).sum() > clipped.read(1).sum()
        assert native.read(1)[6, 6] == 1
    assert {'twi', 'flow_accumulation', 'flow_direction'} <= set(output.summary['products'])


@pytest.mark.parametrize('fault', ['unconditioned', 'upstream_unknown', 'outlet_outside', 'duplicate_outlet'])
def test_watershed_rejects_unsupported_routing(fault):
    request, aoi, sources = fixture('watershed')
    if fault == 'unconditioned': sources['terrain'].evidence['checks']['dem_conditioning_verified'] = False
    if fault == 'upstream_unknown': sources['terrain'].evidence['checks']['hydrologic_coverage_verified'] = False
    if fault in {'outlet_outside', 'duplicate_outlet'}:
        features = json.loads(sources['outlets'].data)['features']
        if fault == 'outlet_outside': features[0]['geometry']['coordinates'] = list(WGS.transform(1100, 1100))
        else: features.append(features[0])
        sources['outlets'] = geo_source('watershed_outlets', features)
    with pytest.raises(SourceNotReady): compute_bundle4(request, sources, aoi)


def test_frequency_preserves_observed_thresholds_and_zero_event_years():
    request, aoi, sources = fixture('historical_frequency')
    _, tables, vectors, _, record, _ = compute_bundle4(request, sources, aoi)
    assert len(tables['annual_discharge_maxima']) == 10
    assert len(tables['inventory_by_year']) == 10
    assert sum(row['distinct_observed_events'] for row in tables['inventory_by_year']) == 1
    assert record['inventory_annual_probability'] == .1
    assert record['inventory_empirical_recurrence_years'] == 10
    largest = tables['discharge_empirical_frequency'][-1]
    assert largest['annual_exceedance_count'] == 1 and largest['empirical_recurrence_years'] == 10
    assert vectors['historical_inventory']['features'][0]['properties']['event_id'] == 'synthetic-event'


@pytest.mark.parametrize('fault', ['gap', 'cadence', 'inventory_unreviewed', 'discharge_unreviewed', 'definition_missing', 'censored_period'])
def test_frequency_rejects_incomplete_or_unsupported_records(fault):
    request, aoi, sources = fixture('historical_frequency')
    if fault == 'gap': sources['discharge'] = sources['discharge'].__class__(sources['discharge'].dataset, sources['discharge'].manifest, b'\n'.join(sources['discharge'].data.splitlines()[:-1])+b'\n', sources['discharge'].evidence)
    if fault == 'cadence': sources['discharge'].manifest.observation_interval_hours = 12
    if fault == 'inventory_unreviewed': sources['inventory'].evidence['checks']['annual_record_complete_verified'] = False
    if fault == 'discharge_unreviewed': sources['discharge'].evidence['checks']['annual_record_complete_verified'] = False
    if fault == 'definition_missing': sources['discharge'].manifest.historical_record_definition = None
    if fault == 'censored_period': request.period.start += timedelta(days=1)
    with pytest.raises(SourceNotReady): compute_bundle4(request, sources, aoi)


def test_mlr_training_only_vif_selection_and_observed_holdout():
    request, aoi, sources = fixture('predictor_mlr')
    _, tables, _, _, record, _ = compute_bundle4(request, sources, aoi)
    assert record['selected_predictors'] == ['rain', 'storage']
    assert record['selection'][1]['accepted'] is False
    assert record['training_count'] == 24 and record['holdout_count'] == 6
    assert len(tables['raw_observations']) == 30 and len(tables['training_fit']) == 24
    coeffs = {item['variable']: item['coefficient'] for item in tables['coefficients']}
    assert coeffs['rain'] == pytest.approx(2, abs=.1)
    assert coeffs['storage'] == pytest.approx(3, abs=.1)
    assert record['holdout_metrics']['rmse'] < 1


@pytest.mark.parametrize('fault', ['incomplete', 'unit', 'identity', 'outside', 'duplicate', 'unknown_variable'])
def test_predictor_join_does_not_impute_or_silently_substitute(fault):
    request, aoi, sources = fixture('predictor_mlr')
    old = sources['observations']
    rows = list(csv.DictReader(io.StringIO(old.data.decode())))
    if fault == 'incomplete': rows.pop()
    if fault == 'unit': rows[0]['unit'] = 'wrong'
    if fault == 'identity': rows[0]['observed_at'] = '2020-02-01T00:00:00Z'
    if fault == 'outside': rows[0]['longitude'] = 50
    if fault == 'duplicate': rows.append(rows[0])
    if fault == 'unknown_variable': rows[0]['variable'] = 'unreviewed'
    with pytest.raises((SourceNotReady, SourceDataValidationError)):
        sources['observations'] = csv_source('flood_predictor_observations', rows, predictor_definitions=old.manifest.predictor_definitions, predictor_catalogue_reference=SYNTHETIC_REF)
        compute_bundle4(request, sources, aoi)


@pytest.mark.parametrize('module', sorted(BUNDLE4_MODULES-{'predictor_mlr', 'historical_frequency'}))
def test_raster_modules_require_grid(module, monkeypatch):
    request, aoi, _ = fixture(module)
    request.target_grid = None
    with pytest.raises(SourceNotReady, match='grid'): resolve_bindings(None, request, aoi_geometry=aoi)


@pytest.mark.parametrize('options', [{'method': 'idw', 'variogram_model': 'spherical'}, {'method': 'ordinary_kriging', 'power': 2}])
def test_unused_interpolation_configuration_is_rejected(options):
    request, _, _ = fixture('rainfall_interpolation')
    fields = request.model_dump()
    fields['rainfall_options'] = options
    with pytest.raises(ValidationError, match='only applicable'): SourceBoundAnalysisRequest.model_validate(fields)


def kriging_fixture():
    request, aoi, sources = fixture('rainfall_interpolation')
    coords = np.vstack(([[100, 100], [900, 100], [100, 900], [900, 900]], np.random.default_rng(100).uniform(150, 850, (12, 2))))
    distances = np.linalg.norm(coords[:, None, :] - coords[None, :, :], axis=-1)
    values = 50+np.random.default_rng(2).multivariate_normal(np.zeros(len(coords)), 25*np.exp(-distances/250))
    rows = []
    for index, ((x, y), value) in enumerate(zip(coords, values)):
        longitude, latitude = WGS.transform(x, y)
        rows.append({'station_id': f'synthetic-kriging-{index:02d}', 'longitude': longitude, 'latitude': latitude,
                     'observed_at': INSTANT, 'rainfall_mm': value, 'quality_flag': 'valid'})
    sources['rainfall'] = csv_source('rainfall_stations', rows, observation_interval_hours=1)
    fields = request.model_dump()
    fields.update(sources={'rainfall': sources['rainfall'].dataset.id}, rainfall_options={'method': 'ordinary_kriging', 'variogram_model': 'spherical'})
    return SourceBoundAnalysisRequest.model_validate(fields), aoi, sources


def test_kriging_real_fit_records_refitted_folds_and_uncertainty():
    request, aoi, sources = kriging_fixture()
    products, _, _, _, record, _ = compute_bundle4(request, sources, aoi)
    assert record['variogram']['fit_converged'] is True
    assert len(record['cross_validation_folds']) == 16
    assert all(fold['variogram']['fit_converged'] for fold in record['cross_validation_folds'])
    assert np.isfinite(products['rainfall_intensity'][0]).all()
    assert (products['rainfall_kriging_variance'][0] >= 0).all()
    assert record['cross_validation']['rmse'] >= 0  # Describes synthetic inputs only.


def test_kriging_does_not_publish_moment_fallback_as_fitted(monkeypatch):
    request, aoi, sources = kriging_fixture()
    def failed_fit(*args, **kwargs):
        raise RuntimeError('Synthetic optimizer nonconvergence')
    monkeypatch.setattr('app.services.hydrology.kriging.curve_fit', failed_fit)
    with pytest.raises(SourceNotReady, match='converge'): compute_bundle4(request, sources, aoi)


def test_kriging_insufficient_stations_and_negative_outputs_fail_closed(monkeypatch):
    request, aoi, sources = fixture('rainfall_interpolation')
    request.rainfall_options = SourceBoundAnalysisRequest.model_validate({**request.model_dump(), 'rainfall_options': {'method': 'ordinary_kriging'}}).rainfall_options
    with pytest.raises(SourceNotReady, match='six'): compute_bundle4(request, sources, aoi)
    request, aoi, sources = kriging_fixture()
    monkeypatch.setattr('app.services.source_data.bundle4.ordinary_kriging', lambda points, values, queries, params: (np.full(len(queries), -1.), np.ones(len(queries))))
    with pytest.raises(SourceNotReady, match='invalid'): compute_bundle4(request, sources, aoi)


@pytest.mark.parametrize('method', ['idw', 'ordinary_kriging'])
def test_interpolation_options_survive_task_and_worker_serialization(method):
    request, _, _ = fixture('rainfall_interpolation')
    fields = request.model_dump()
    fields['rainfall_options'] = {'method': method}
    request = SourceBoundAnalysisRequest.model_validate(fields)
    assert SourceBoundAnalysisRequest.model_validate_json(request.model_dump_json()) == request


@pytest.mark.parametrize('identifier', ['=1+1', '\t=1+1', '  =1+1', '@SUM(1)'])
def test_csv_export_protects_spreadsheet_identifiers(tmp_path, identifier):
    request, aoi, sources = fixture('predictor_mlr')
    old = sources['observations']
    # Use CSV quoting so a hostile identifier remains an identifier, not a new column.
    rows = list(csv.DictReader(io.StringIO(old.data.decode())))
    for row in rows:
        if row['sample_id'] == 'synthetic-0': row['sample_id'] = identifier
    sources['observations'] = csv_source('flood_predictor_observations', rows, predictor_definitions=old.manifest.predictor_definitions, predictor_catalogue_reference=SYNTHETIC_REF)
    execute_bundle4(ResolvedBindings(request, sources, {}), aoi, tmp_path, 1, task_id='synthetic')
    raw = pd.read_csv(tmp_path/'raw_observations.csv')
    assert raw.loc[0, 'sample_id'] == "'"+identifier
    assert identifier in sources['observations'].data.decode()  # Raw source remains untouched.


@pytest.mark.parametrize('fault', ['absent', 'opposite_direction', 'different_reference'])
def test_proximity_request_cannot_replace_a_reviewed_source_policy(fault):
    request, aoi, sources = fixture('feature_proximity')
    if fault == 'absent': sources['services'].manifest.proximity_scoring_policy = None
    if fault == 'opposite_direction': request.proximity_options.service_direction = 'cost'
    if fault == 'different_reference': sources['services'].manifest.proximity_scoring_policy.policy_reference = 'other:policy'
    with pytest.raises(SourceNotReady, match='source-reviewed'): compute_bundle4(request, sources, aoi)
