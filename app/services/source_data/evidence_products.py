"""Source-bound validation, decision records and unchanged six-module map delivery."""
from pathlib import Path
from datetime import datetime
import json
import numpy as np
import pandas as pd
from pyproj import CRS
from rasterio.io import MemoryFile
from shapely.geometry import shape

from app.platform.engines.base import EngineExecutionOutput
from app.platform.result_exports import artifact_entry, build_result_exports
from app.services.maps.export import RasterSpec, write_cog
from app.services.source_data.bundle4 import grid_context, clean, reviewed_policy, LIMITATIONS
from app.services.source_data.readiness import SourceNotReady
from app.services.reporting.complete_report import _spreadsheet_safe
from app.services.validation.diagnostics import continuous_diagnostics, binary_diagnostics, write_diagnostic_artifacts


def validation_arrays(bindings, aoi):
    request, sources = bindings.request, bindings.sources
    transform, mask, _ = grid_context(request, aoi)
    grid = request.target_grid
    definitions = {role: source.manifest.validation_definition for role, source in sources.items()}
    expected = definitions['predicted']
    arrays = {}
    for role, source in sources.items():
        definition = definitions[role]
        reviewed_policy(source, definition.comparison_reference, 'validation_definition_verified')
        if any(getattr(definition, key) != getattr(expected, key) for key in ('quantity_id', 'definition', 'comparison_reference', 'class_labels', 'evaluation_scope')):
            raise SourceNotReady('Validation sources have incompatible quantity, class or evaluation semantics')
        if role == 'score' and definition.value_units != 'conditional_class_probability_0_1':
            raise SourceNotReady('Score units must explicitly identify conditional class probabilities, not AEP')
        if role == 'folds' and definition.value_units != 'fold_code':
            raise SourceNotReady('Fold assignment units must explicitly identify fold codes')
        if role == 'uncertainty':
            uncertainty_units = expected.value_units+' squared' if definition.uncertainty_kind == 'variance' else expected.value_units
            if definition.value_units != uncertainty_units:
                raise SourceNotReady('Uncertainty units are incompatible with the declared measure and predicted quantity')
        if role not in {'score', 'uncertainty', 'folds'} and definition.value_units != expected.value_units:
            raise SourceNotReady('Validation observed/predicted units differ')
        if role in {'score', 'uncertainty'} and definition.model_reference != expected.model_reference:
            raise SourceNotReady('Score/uncertainty model identity differs from prediction')
        if role == 'baseline':
            if source.manifest.temporal_coverage.end >= request.period.start:
                raise SourceNotReady('Change baseline must precede current prediction period')
        elif source.manifest.temporal_coverage != sources['predicted'].manifest.temporal_coverage:
            raise SourceNotReady('Validation temporal supports differ')
        with MemoryFile(source.data) as memory, memory.open() as raster:
            if (raster.crs != CRS.from_user_input(grid.crs) or raster.width != grid.width or raster.height != grid.height
                    or not raster.transform.almost_equals(transform)):
                raise SourceNotReady('Validation requires exact native grid matching; no scientific resampling')
            data = raster.read(1, masked=True)
            if np.ma.getmaskarray(data)[mask].any() or not np.isfinite(data.data[mask]).all():
                raise SourceNotReady('Validation input is incomplete over the AOI')
            arrays[role] = data.data.astype(float)
    if expected.evaluation_scope == 'reviewed_independent':
        observed = sources['observed']
        reviewed_policy(observed, expected.comparison_reference, 'independent_observations_verified')
        if observed.dataset.id in expected.training_dataset_ids:
            raise SourceNotReady('Independent observation dataset occurs in declared model training inputs')
    if 'score' in arrays and expected.decision_threshold is not None:
        if not np.array_equal(arrays['predicted'][mask], (arrays['score'][mask] >= expected.decision_threshold).astype(int)):
            raise SourceNotReady('Predicted labels contradict the declared score threshold')
    if expected.hotspot_policy_reference:
        reviewed_policy(sources['predicted'], expected.hotspot_policy_reference, 'scoring_policy_verified')
    observed, predicted = arrays['observed'][mask], arrays['predicted'][mask]
    kind = 'continuous' if request.module == 'continuous_validation' else 'binary'
    diagnostics = continuous_diagnostics(observed, predicted) if kind == 'continuous' else binary_diagnostics(observed, predicted, arrays['score'][mask] if 'score' in arrays else None)
    return arrays, mask, transform, expected, kind, diagnostics


def domain_records(bindings, aoi):
    role = 'records' if bindings.request.module == 'decision_support' else 'impacts'
    source = bindings.sources[role]
    if role == 'records':
        refs = {definition.evidence_reference for definition in source.manifest.dss_metric_definitions.values()}
        for reference in refs: reviewed_policy(source, reference, 'dss_definitions_verified')
    else:
        reviewed_policy(source, source.manifest.impact_definition.evidence_reference, 'impact_definition_verified')
    selected, identities = [], set()
    boundary = shape(aoi)
    for feature in json.loads(source.data)['features']:
        geometry, props = shape(feature['geometry']), feature['properties']
        if not geometry.intersects(boundary):
            continue
        if not boundary.covers(geometry):
            raise SourceNotReady('Domain record crosses AOI; no invented spatial apportionment')
        stamp = datetime.fromisoformat(props['observed_at'].replace('Z', '+00:00'))
        if not bindings.request.period.start <= stamp <= bindings.request.period.end:
            continue
        identity = (props['record_id'], props.get('metric_key'))
        if identity in identities:
            raise SourceNotReady('Duplicate domain record identity')
        identities.add(identity)
        selected.append(feature)
    if not selected or len(selected) > 25000:
        raise SourceNotReady('Requested AOI/period has no records or exceeds bounded capacity')
    return source, selected


def validate_evidence_products(bindings, aoi):
    try:
        if bindings.request.module.endswith('_validation'): validation_arrays(bindings, aoi)
        else: domain_records(bindings, aoi)
    except (ValueError, OSError, FloatingPointError) as exc:
        raise SourceNotReady(str(exc)) from exc


def execute_evidence_products(bindings, aoi, output_directory, result_version, *, task_id):
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    request = bindings.request
    entries, summary, metadata = {}, {'status': 'completed', 'module': request.module, 'limitations': LIMITATIONS}, {'target_period': request.period.model_dump(mode='json')}
    if request.module.endswith('_validation'):
        arrays, mask, transform, definition, kind, diagnostics = validation_arrays(bindings, aoi)
        observed, predicted = arrays['observed'][mask], arrays['predicted'][mask]
        dashboard, plots = write_diagnostic_artifacts(directory, observed, predicted, kind=kind, units=definition.value_units,
                    scope=definition.evaluation_scope, version=result_version, scores=arrays['score'][mask] if 'score' in arrays else None)
        entries.update(plots)
        if kind == 'binary': dashboard['metrics']['class_labels'] = definition.class_labels
        products = {role: (values, bindings.sources[role].manifest.validation_definition.value_units) for role, values in arrays.items()}
        residual = arrays['observed']-arrays['predicted']
        products.update(residual=(residual, definition.value_units), absolute_error=(np.abs(residual), definition.value_units), squared_error=(residual**2, definition.value_units+' squared'))
        if kind == 'continuous':
            relative = np.full(mask.shape, np.nan)
            nonzero = mask & (arrays['observed'] != 0)
            relative[nonzero] = residual[nonzero]/arrays['observed'][nonzero]*100
            products['relative_error'] = (relative, 'percent')
        else:
            o, p = arrays['observed'], arrays['predicted']
            products['confusion'] = (np.where((o==1)&(p==1),1,np.where((o==0)&(p==0),2,np.where((o==0)&(p==1),3,4))), 'TP=1 TN=2 FP=3 FN=4')
            products['agreement'] = ((o==p).astype(int), 'binary_agreement_0_1')
        availability = dashboard['availability']
        for role in ('uncertainty', 'folds', 'baseline'):
            availability[role] = {'available': role in arrays, 'reason': None if role in arrays else 'No explicitly bound reviewed source; values are not inferred'}
        availability['hotspot'] = {'available': definition.hotspot_absolute_error_threshold is not None, 'reason': 'Requires a bound reviewed absolute-error policy'}
        if definition.hotspot_absolute_error_threshold is not None:
            products['hotspot'] = ((np.abs(residual) >= definition.hotspot_absolute_error_threshold).astype(int), 'reviewed_policy_membership_0_1')
            dashboard['metrics']['hotspot_policy'] = {'threshold': definition.hotspot_absolute_error_threshold, 'reference': definition.hotspot_policy_reference, 'units': definition.value_units}
        if 'baseline' in arrays: products['prediction_change'] = (arrays['predicted']-arrays['baseline'], definition.value_units)
        if 'folds' in arrays:
            folds = {}
            for code, label in bindings.sources['folds'].manifest.validation_definition.fold_definitions.items():
                selected = mask & (arrays['folds'] == int(code))
                n = int(selected.sum())
                folds[code] = {'label': label, 'count': n, 'available': n >= (3 if kind == 'continuous' else 1)}
                if folds[code]['available']:
                    folds[code]['diagnostics'] = continuous_diagnostics(arrays['observed'][selected], arrays['predicted'][selected]) if kind == 'continuous' else binary_diagnostics(arrays['observed'][selected], arrays['predicted'][selected], arrays['score'][selected] if 'score' in arrays else None)
            dashboard['metrics']['declared_folds'] = folds
        spec = RasterSpec(transform, CRS.from_user_input(request.target_grid.crs).to_epsg())
        grid = request.target_grid
        metadata.update(crs=grid.crs, bounds=[grid.west, grid.south, grid.east, grid.north], width=grid.width, height=grid.height, transform=list(transform)[:6], nodata=-9999,
                        spatial_resolution={'x': transform.a, 'y': -transform.e, 'unit': 'm'})
        for key, (values, units) in products.items():
            selected = mask & np.isfinite(values)
            if np.isinf(values[mask]).any(): raise SourceNotReady('Derived validation product overflow')
            # Raw sources retain their original registered bytes; raster delivery must not silently round scientific values.
            raster = np.full(mask.shape, -9999, dtype='float64')
            raster[selected] = values[selected]
            if (raster[selected] == -9999).any(): raise SourceNotReady('Value collides with export nodata')
            path = directory/(key+'.cog.tif')
            write_cog(str(path), raster, spec, nodata=-9999)
            gis = {**metadata, 'units': units, 'evaluation_definition': definition.model_dump(mode='json'), 'source_temporal_support': bindings.sources[key].manifest.temporal_coverage.model_dump(mode='json') if key in bindings.sources else None, 'baseline_temporal_support': bindings.sources['baseline'].manifest.temporal_coverage.model_dump(mode='json') if key == 'prediction_change' else None, 'defined_aoi_cells': int(selected.sum()), 'undefined_aoi_cells': int((mask & ~selected).sum())}
            if key == 'baseline': gis['target_period'] = bindings.sources['baseline'].manifest.temporal_coverage.model_dump(mode='json')
            if key in bindings.sources: gis['evaluation_definition'] = bindings.sources[key].manifest.validation_definition.model_dump(mode='json')
            entries[key] = artifact_entry(path, label=key.replace('_',' '), media_type='image/tiff', artifact_type='raster', role='product', product_key=key, format_name='cog', delivery_type='cog', result_version=result_version,
                gis_metadata=gis, layer={'layer_type': 'raster', 'crs': grid.crs, 'units': units, 'bounding_box': {'west': grid.west, 'south': grid.south, 'east': grid.east, 'north': grid.north}, 'nodata': -9999, 'renderable': True, 'available_delivery_types': ['cog'], 'planned_delivery_types': []})
        pairs = [{'row': int(row), 'column': int(col), **{role: float(values[row,col]) for role, values in arrays.items()}} for row, col in zip(*np.where(mask))]
        path = directory/'validation-pairs.csv'
        _spreadsheet_safe(pd.DataFrame(pairs)).to_csv(path,index=False)
        entries['validation_pairs'] = artifact_entry(path,label='Actual paired source cells',media_type='text/csv',artifact_type='metadata',role='product',format_name='csv',result_version=result_version)
        summary['validation_dashboard'] = dashboard
    else:
        source, features = domain_records(bindings, aoi)
        path = directory/'sourced-records.geojson'
        path.write_text(json.dumps({'type':'FeatureCollection','features':features},allow_nan=False))
        entries['sourced_records'] = artifact_entry(path,label='Unchanged sourced domain records',media_type='application/geo+json',artifact_type='vector',role='product',product_key='sourced_records',format_name='geojson',result_version=result_version,gis_metadata={**metadata,'crs':'EPSG:4326','units':source.manifest.units})
        rows = [feature['properties'] for feature in features]
        path = directory/'sourced-records.csv'
        _spreadsheet_safe(pd.DataFrame(rows)).to_csv(path,index=False)
        entries['sourced_records_table'] = artifact_entry(path,label='Sourced measurements',media_type='text/csv',artifact_type='metadata',role='product',format_name='csv',result_version=result_version)
        if request.module == 'decision_support':
            summary['decision_support'] = {'tables': {domain:[row for row in rows if row['domain']==domain] for domain in ('community','infrastructure','event','kpi')},
                'source_identity': {**source.lineage(), 'measurement_definitions': {key: d.model_dump() for key,d in source.manifest.dss_metric_definitions.items()}},
                'limitations': ['Only explicitly sourced measurements; absent records are unavailable, not zero or fabricated indicators.']}
        else:
            definition = source.manifest.impact_definition
            summary['impact'] = {'households': sum(row['households'] for row in rows), 'loss_amount': sum(row['loss_amount'] for row in rows), 'currency': definition.currency, 'record_count': len(rows), 'definition': definition.model_dump(), 'aggregation': 'Sum of supplied records only; not a calibrated loss model or population-wide total'}
            for role, ready in bindings.upstream.items():
                for key, (entry, data) in ready.artifacts.items():
                    path = directory/(role+'-'+Path(entry['path']).name)
                    path.write_bytes(data)
                    kwargs = {name: entry[name] for name in ('label','media_type','artifact_type','role','product_key','format','delivery_type') if name in entry}
                    kwargs['format_name'] = kwargs.pop('format', None)
                    entries[role+'_'+key] = artifact_entry(path, **kwargs, result_version=result_version,
                        gis_metadata={**entry['gis_metadata'], 'source_result_id': str(ready.result.id), 'source_result_version': ready.result.version, 'source_artifact_sha256': entry['checksum_sha256'], 'processing': 'Byte-identical assembly; no resampling, derivation or substitution'}, layer=entry.get('layer'))
            if not np.isfinite(summary['impact']['loss_amount']): raise SourceNotReady('Supplied loss record aggregation overflows supported numeric delivery')
            summary['module_maps'] = {role: ready.lineage() for role, ready in bindings.upstream.items()}
    provenance = {'engine_key':'firris','module':request.module,'source_bindings':bindings.lineage(),'upstream_results':{role: ready.lineage() for role,ready in bindings.upstream.items()}, 'analysis_readiness_rechecked_at_execution':True, 'raw_source_policy':'Immutable registered source bytes retained; supplied scientific observations are not altered', 'validation_limitations':LIMITATIONS}
    summary = clean(summary)
    path = directory/'evidence-dashboard.json'
    path.write_text(json.dumps(summary,allow_nan=False))
    entries['evidence_dashboard'] = artifact_entry(path,label='Evidence dashboard',media_type='application/json',artifact_type='metadata',role='export',format_name='json',result_version=result_version)
    exports = build_result_exports(directory,task_id=task_id,project_id=str(request.project_id),aoi_id=str(request.aoi_id),engine_key='firris',engine_version='source-bound-evidence-v1',result_type='source_bound_'+request.module,result_version=result_version,summary=summary,provenance=provenance,gis_metadata=metadata,product_entries=entries)
    return EngineExecutionOutput('source_bound_'+request.module,summary,provenance,{**entries,**exports})
