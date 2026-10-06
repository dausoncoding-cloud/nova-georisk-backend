"""Execute externally reviewed M11/M12 methods on exact protected source inputs.

Review attestations authorize a source; they do not establish scientific accuracy.
Legacy relative products remain separate and retain their existing interpretation.
"""
from pathlib import Path
import hashlib
from itertools import combinations

import joblib
import numpy as np
import pandas as pd
import rasterio
from PIL import Image
from rasterio.io import MemoryFile
from shapely.geometry import shape
from pyproj import CRS

from app.platform.engines.base import EngineExecutionOutput
from app.platform.result_exports import artifact_entry, build_result_exports
from app.services.maps.export import write_cog, RasterSpec
from app.services.maps.flood_products import compute_hazard_index
from app.services.ml.training import train_classifier_from_split, classifier_configuration
from app.services.reporting.report_builder import export_csv, generate_excel_report, generate_pdf_report, ReportContext, IndexSummary
from app.services.source_data.bundle4 import grid_context, predictor_observation_frame, records, reviewed_policy, stamp
from app.services.source_data.readiness import SourceNotReady
from app.services.validation.diagnostics import write_diagnostic_artifacts

NODATA = -9999.0
LIMITATIONS = [
    'Source-bound administrator review is not independent scientific validation',
    'Real licensed/reviewed observations, model/policy approval and independent validation remain external requirements',
    'No operational accuracy, calibration, annual probability or safety certification is asserted',
]


def exact_values(data, grid, mask, spec, *, nodata, nonnegative=False):
    """No reprojection, interpolation, missing-data filling or semantic substitution."""
    try:
        with MemoryFile(data) as memory, memory.open() as raster:
            if (raster.count != 1 or raster.crs is None or raster.crs.to_string() != grid.crs
                    or raster.width != grid.width or raster.height != grid.height
                    or not raster.transform.almost_equals(spec.transform) or raster.nodata != nodata):
                raise SourceNotReady('Reviewed map source grid/CRS/nodata differs; no resampling is allowed')
            values = raster.read(1, masked=True)
            observed = np.asarray(values.data, dtype=float)[mask]
            if (not (~np.ma.getmaskarray(values))[mask].all() or not np.isfinite(observed).all()
                    or (nonnegative and (observed < 0).any())):
                raise SourceNotReady('Reviewed map source contains incomplete or invalid AOI values')
            return observed
    except (rasterio.errors.RasterioError, OSError, ValueError) as exc:
        raise SourceNotReady('Reviewed map source raster cannot be read or is incompatible') from exc


def susceptibility_inputs(bindings, aoi):
    request = bindings.request
    source = bindings.sources.get('observations')
    if source is None or source.manifest.susceptibility_method is None or bindings.upstream:
        raise SourceNotReady('Distinct susceptibility requires sourced historical labels and a reviewed method')
    method = source.manifest.susceptibility_method
    if method.method_reference != request.susceptibility_options.method_reference:
        raise SourceNotReady('Susceptibility method reference differs from the bound reviewed source')
    reviewed_policy(source, method.method_reference, 'susceptibility_method_verified')
    reviewed_policy(source, method.historical_observation_reference, 'independent_observations_verified')
    if source.manifest.temporal_coverage.end >= request.period.start:
        raise SourceNotReady('Historical susceptibility observations must precede the target analysis period')
    historical = request.model_copy(update={'period': source.manifest.temporal_coverage})
    frame, identities, order, definitions = predictor_observation_frame(historical, source, aoi, options=method)
    response = definitions[method.response]
    if response.unit != 'binary_class_0_1' or response.definition != method.label_definition:
        raise SourceNotReady('Historical response units and meaning must match the reviewed binary label definition')
    split = int(len(frame)*method.train_fraction)
    if (split < 2 or len(frame)-split < 2 or identities[order[split-1]][0] >= identities[order[split]][0]
            or any(set(part[method.response].unique()) != {0, 1} for part in (frame.iloc[:split], frame.iloc[split:]))):
        raise SourceNotReady('Chronological train/test partitions need disjoint times and both binary classes')
    if method.algorithm == 'svm' and frame.iloc[:split][method.response].value_counts().min() < 5:
        raise SourceNotReady('Existing SVM probability path requires five historical training rows per class')
    required = {'observations', *('predictor_'+key for key in method.predictor_order)}
    if set(bindings.sources) != required:
        raise SourceNotReady('Susceptibility raster roles must exactly match the reviewed predictor catalogue')
    transform, mask, _ = grid_context(request, aoi)
    grid = request.target_grid
    spec = RasterSpec(transform, int(grid.crs.split(":")[1]))
    values = {}
    for key in method.predictor_order:
        raster = bindings.sources['predictor_'+key]
        definition = raster.manifest.raster_predictor
        if (definition is None or definition.name != key or definition.variable != definitions[key]
                or definition.catalogue_reference != source.manifest.predictor_catalogue_reference):
            raise SourceNotReady('Raster predictor identity, units, encoding or catalogue definition differs')
        reviewed_policy(raster, definition.catalogue_reference, 'predictor_catalogue_verified')
        values[key] = exact_values(raster.data, grid, mask, spec, nodata=raster.manifest.nodata)
        training = frame.iloc[:split][key]
        if training.nunique() < 2 or (values[key] < training.min()).any() or (values[key] > training.max()).any():
            raise SourceNotReady('Predictor raster lies outside historical training support; extrapolation is unsupported')
    return grid, mask, spec, method, frame, identities, order, split, pd.DataFrame(values, columns=method.predictor_order)


def zonation_inputs(bindings, aoi):
    request = bindings.request
    if set(bindings.sources) != {'policy'}:
        raise SourceNotReady('Reviewed zonation requires exactly one sourced decision table')
    source = bindings.sources['policy']
    policy = source.manifest.zonation_policy
    if policy is None or policy.method_reference != request.zonation_options.method_reference:
        raise SourceNotReady('Zonation method reference differs from the bound reviewed policy')
    reviewed_policy(source, policy.method_reference, 'zonation_method_verified')
    if set(bindings.upstream) != set(policy.factor_units):
        raise SourceNotReady('Every reviewed zonation factor must bind its actual protected Result')
    transform, mask, _ = grid_context(request, aoi)
    grid = request.target_grid
    spec = RasterSpec(transform, int(grid.crs.split(":")[1]))
    values, originals = {}, {}
    for factor, units in policy.factor_units.items():
        ready = bindings.upstream[factor]
        key = 'flood_'+factor if factor != 'exposure' else 'flood_exposure'
        if hasattr(ready, 'raster_bytes'):
            data = ready.raster_bytes
            entry = ready.result.output_files[key]
        else:
            if key not in ready.artifacts:
                raise SourceNotReady('Zonation factor has no compatible quantitative protected raster')
            entry, data = ready.artifacts[key]
        meta = entry.get('gis_metadata', {})
        period = policy.reference_periods['aep'] if factor == 'aep' else request.period
        if (meta.get('units') != units or meta.get('target_period') != period.model_dump(mode='json')
                or meta.get('result_version') != ready.result.version):
            raise SourceNotReady('Zonation factor units, temporal semantics or version differs')
        values[factor] = exact_values(data, grid, mask, spec, nodata=NODATA, nonnegative=True)
        if factor in {'aep', 'exposure'} and (values[factor] > 1).any():
            raise SourceNotReady('Zonation probability/index factor exceeds its canonical scale')
        originals[factor] = (data, meta)
    rules = {}
    for row in records(source):
        if not source.manifest.temporal_coverage.start <= stamp(row) <= source.manifest.temporal_coverage.end:
            raise SourceNotReady('Decision-table record is outside its requested policy validity period')
        key, factor, code = row['rule_id'], row['factor'], row['class_code']
        lower, upper = float(row['lower_bound']), float(row['upper_bound'])
        if (factor not in values or code not in policy.classes or not np.isfinite([lower, upper]).all()
                or lower >= upper):
            raise SourceNotReady('Decision-table interval or class is incompatible with the reviewed policy')
        if key not in rules and len(rules)>=512:
            raise SourceNotReady('Decision table exceeds bounded 512-rule execution capacity')
        rule = rules.setdefault(key, {'class_code': int(code), 'intervals': {}})
        if rule['class_code'] != int(code) or factor in rule['intervals']:
            raise SourceNotReady('Decision-table rule has contradictory class or duplicate factor')
        rule['intervals'][factor] = [lower, upper]
    if (not rules or any(set(rule['intervals']) != set(values) for rule in rules.values())
            or {str(rule['class_code']) for rule in rules.values()} != set(policy.classes)):
        raise SourceNotReady('Decision table must account for every factor and every declared class')
    for first, second in combinations(rules.values(), 2):
        if all(max(first['intervals'][factor][0], second['intervals'][factor][0]) < min(first['intervals'][factor][1], second['intervals'][factor][1]) for factor in values):
            raise SourceNotReady('Decision-table rules overlap in their declared factor domain')
    classes, hits = np.zeros(int(mask.sum()), dtype='int16'), np.zeros(int(mask.sum()), dtype='int32')
    for rule in rules.values():
        selected = np.ones(len(classes), dtype=bool)
        for factor, (lower, upper) in rule['intervals'].items():
            selected &= (values[factor] >= lower) & (values[factor] < upper)
        hits += selected
        classes[selected] = rule['class_code']
    if not (hits == 1).all():
        raise SourceNotReady('Decision-table rules overlap or leave AOI cells uncovered; no fallback zone is inferred')
    return grid, mask, spec, policy, values, originals, rules, classes


def validate_reviewed_map(bindings, aoi):
    if bindings.request.susceptibility_options is not None:
        susceptibility_inputs(bindings, aoi)
    elif bindings.request.zonation_options is not None:
        zonation_inputs(bindings, aoi)
    else:
        raise SourceNotReady('A supported reviewed map method must be selected explicitly')


def execute_reviewed_map(bindings, aoi, directory: Path, result_version: int, *, task_id: str):
    request = bindings.request
    directory.mkdir(parents=True, exist_ok=True)
    reports = {}
    raw = {}
    details = {}
    module = request.module
    if request.susceptibility_options is not None:
        grid, mask, spec, method, frame, identities, order, split, predictors = susceptibility_inputs(bindings, aoi)
        try:
            trained = train_classifier_from_split(frame.iloc[:split][method.predictor_order], frame.iloc[:split][method.response],
                frame.iloc[split:][method.predictor_order], frame.iloc[split:][method.response],
                model_type=method.algorithm, random_seed=method.random_seed, n_estimators=method.n_estimators)
            values = trained.predict_proba(predictors)
            predicted = trained.predict(predictors)
        except ValueError as exc:
            raise SourceNotReady('Reviewed susceptibility classifier cannot produce supported finite outputs') from exc
        if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any() or not np.isin(predicted, [0, 1]).all():
            raise SourceNotReady('Susceptibility classifier returned invalid conditional scores/classes')
        legend = [band.model_dump() for band in method.display_legend]
        classes = np.searchsorted([band['max'] for band in legend[:-1]], values, side='left')+1
        units = 'conditional_class_probability_0_1'
        raw['historical_class_prediction'] = (predicted, 'binary_class_0_1')
        details = {'classifier_configuration': classifier_configuration(trained.model), 'feature_importances': trained.feature_importances,
                   'predictor_definitions': {k: v.model_dump() for k, v in bindings.sources['observations'].manifest.predictor_definitions.items()},
                   'training_count': split, 'holdout_count': len(frame)-split,
                   'split': [{'sample_id': key, 'observed_at': identities[key][0].isoformat(),
                              'longitude': identities[key][1], 'latitude': identities[key][2],
                              'partition': 'train' if index < split else 'holdout'} for index, key in enumerate(order)]}
        observed = frame.iloc[split:][method.response].to_numpy()
        heldout = frame.iloc[split:][method.predictor_order]
        details['holdout_diagnostics'], diagnostic_entries = write_diagnostic_artifacts(directory, observed, trained.predict(heldout),
            kind='binary', scores=trained.predict_proba(heldout), units='binary_class_0_1',
            scope='Chronological held-out historical source diagnostics; not independent geographical or operational validation', version=result_version)
        reports.update(diagnostic_entries)
        table = frame.copy(); table['partition'] = ['train']*split+['holdout']*(len(frame)-split)
        table['fitted_class'] = trained.predict(frame[method.predictor_order]); table['conditional_score'] = trained.predict_proba(frame[method.predictor_order])
        path = directory/'historical-model-samples.csv'
        export_csv(table.reset_index(names='sample_id'), str(path))
        reports['historical_model_samples'] = artifact_entry(path,label='Historical source model samples',media_type='text/csv',artifact_type='report',role='export',format_name='csv',result_version=result_version)
        path = directory/'historical-classifier.joblib';joblib.dump(trained.model,path)
        reports['fitted_classifier'] = artifact_entry(path,label='Actual fitted historical classifier',media_type='application/octet-stream',artifact_type='report',role='export',format_name='joblib',result_version=result_version)
        for key in method.predictor_order: raw['predictor_'+key] = (predictors[key].to_numpy(), bindings.sources['predictor_'+key].manifest.raster_predictor.variable.unit)
        interpretation = 'Conditional historical positive-class score from the explicitly selected classifier; not annual exceedance probability'
    else:
        grid, mask, spec, method, factors, originals, rules, classes = zonation_inputs(bindings, aoi)
        values = classes.astype(float)
        units = 'reviewed_zone_code'
        legend = [{'label': band.label, 'color': band.color, 'min': int(code)-.5, 'max': int(code)+.5, 'class_code': int(code), 'value': int(code)} for code, band in method.classes.items()]
        legend.sort(key=lambda band: band['class_code'])
        details = {'decision_table': rules, 'interval_semantics': 'lower inclusive, upper exclusive; AND across all factors; exactly one matching rule per cell'}
        raw['depth_velocity_index'] = (compute_hazard_index(factors['depth'],factors['velocity']), 'm2/s')
        for key, (data, metadata) in originals.items():
            path=directory/('raw-'+key+'.cog.tif');path.write_bytes(data)
            reports['raw_'+key]=artifact_entry(path,label='Unmodified upstream '+key,media_type='image/tiff',artifact_type='raster',role='export',format_name='cog',result_version=result_version,gis_metadata=metadata)
        interpretation = 'Externally reviewed multi-factor decision-table zones; policy classes are not independently validated safety standards'
    for role, source in bindings.sources.items():
        extension='.tif' if source.manifest.spatial_resolution else '.csv'
        path=directory/('source-'+role+extension);path.write_bytes(source.data)
        reports['source_'+role]=artifact_entry(path,label='Unmodified bound source '+role,media_type='application/octet-stream',artifact_type='report',role='export',format_name=extension[1:],result_version=result_version,
            gis_metadata={'source_identity':source.lineage(),'received_byte_sha256':hashlib.sha256(source.data).hexdigest()})
    period=request.period.model_dump(mode='json')
    bounds=[grid.west,grid.south,grid.east,grid.north]
    aw,south,east,north=shape(aoi).bounds
    metadata={'crs':grid.crs,'datum':CRS.from_user_input(grid.crs).datum.name,
        'vertical_datum':bindings.upstream['depth'].result.output_files['flood_depth']['gis_metadata'].get('vertical_datum') if request.zonation_options is not None else None,'bounds':bounds,'aoi_bounds_wgs84':{'west':aw,'south':south,'east':east,'north':north},
        'spatial_resolution':{'x':abs(spec.transform.a),'y':abs(spec.transform.e),'unit':'m'},'width':grid.width,'height':grid.height,
        'nodata':NODATA,'units':units,'target_period':period,'product_key':module,'result_version':result_version,
        'legend':legend,'methodology':interpretation,'method_reference':method.method_reference,'method_version':method.method_version,'producer':'NOVA GeoRisk'}
    counts=[{'class':band['label'],'class_code':index,'cell_count':int((classes==index).sum()),
             'fraction_of_valid_aoi':float((classes==index).sum()/len(classes)),
             'projected_area_m2':int((classes==index).sum())*abs(spec.transform.a*spec.transform.e)} for index,band in enumerate(legend,1)]
    entries={}
    def cog(key, observed, observed_units, *, product=False):
        array=np.full(mask.shape,NODATA,dtype='int16' if key in {'flood_hazard_zonation','raw_historical_class_prediction'} else 'float64');array[mask]=observed
        if not np.isfinite(observed).all() or (array[mask]==NODATA).any(): raise SourceNotReady('Raw map outputs collide with nodata or contain nonfinite values')
        path=directory/(key+'.cog.tif');write_cog(str(path),array,spec,nodata=NODATA)
        meta={**metadata,'units':observed_units,'product_key':key}
        if not product: meta.pop('legend',None)
        entries[key]=artifact_entry(path,label=key.replace('_',' '),media_type='image/tiff',artifact_type='raster',role='product' if product else 'export',
            product_key=key if product else None,delivery_type='raster',format_name='cog',result_version=result_version,gis_metadata=meta,
            layer={'layer_type':'raster','crs':grid.crs,'units':units,'nodata':NODATA,'bounding_box':dict(zip(('west','south','east','north'),bounds)),
                   'legend':legend,'renderable':True,'available_delivery_types':['raster','preview'],'planned_delivery_types':[]} if product else None)
    cog(module, values, units, product=True)
    for key,(observed,observed_units) in raw.items(): cog('raw_'+key, observed, observed_units)
    palette=np.asarray([(0,0,0,0)]+[(*bytes.fromhex(band['color'][1:]),255) for band in legend],dtype='uint8')
    codes=np.zeros(mask.shape,dtype='uint8');codes[mask]=classes
    path=directory/(module+'-preview.png');Image.fromarray(palette[codes]).save(path)
    entries[module+'_preview']=artifact_entry(path,label='Reviewed map preview',media_type='image/png',artifact_type='preview',role='product',
        product_key=module,delivery_type='preview',format_name='png',result_version=result_version,gis_metadata=metadata,layer=entries[module]['layer'])
    table=pd.DataFrame(counts)
    for key,path,media in [('csv',directory/'map-classes.csv','text/csv'),('excel',directory/'map-summary.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),('pdf',directory/'map-report.pdf','application/pdf')]:
        if key=='csv': export_csv(table,str(path))
        elif key=='excel': generate_excel_report({'Classes':table,'Summary':pd.DataFrame([{'interpretation':interpretation,'units':units,'method_reference':method.method_reference,'method_version':method.method_version}])},str(path))
        else: generate_pdf_report(ReportContext(project_name=str(request.project_id),aoi_name=str(request.aoi_id),index_summaries=[IndexSummary(name=module,mean=float(values.mean()),min=float(values.min()),max=float(values.max()),classification=interpretation)],notes=interpretation+'. '+'; '.join(LIMITATIONS)),str(path))
        reports[module+'_'+key]=artifact_entry(path,label='Reviewed map '+key,media_type=media,artifact_type='report',role='export',delivery_type=key,format_name=path.suffix[1:],result_version=result_version)
    summary={'status':'completed','module':module,'product':module,'units':units,'minimum':float(values.min()),'maximum':float(values.max()),
             'class_statistics':counts,'valid_aoi_cell_count':len(classes),'method_interpretation':interpretation,'independent_validation':'not supplied'}
    provenance={'engine_key':'firris','module':module,'methodology':interpretation,'reviewed_method':method.model_dump(mode='json'),'method_details':details,
        'source_bindings':bindings.lineage(),'upstream_results':{key:ready.lineage() for key,ready in bindings.upstream.items()},
        'formula_implementation':'app.services.ml.training.train_classifier_from_split' if request.susceptibility_options is not None else 'source-bound reviewed interval decision table',
        'raw_depth_velocity_formula':'app.services.maps.flood_products.compute_hazard_index' if request.zonation_options is not None else None,
        'processing':{'alignment':'exact native protected grid; no resampling','target_period':period,'raw_outputs_preserved':True},
        'analysis_readiness_rechecked_at_execution':True,'validation_limitations':LIMITATIONS}
    exports=build_result_exports(directory,task_id=task_id,project_id=str(request.project_id),aoi_id=str(request.aoi_id),engine_key='firris',
        engine_version='source-bound-reviewed-map-v1',result_type='source_bound_'+module,result_version=result_version,summary=summary,provenance=provenance,
        gis_metadata=metadata,product_entries=entries,supplemental_entries=reports)
    return EngineExecutionOutput(result_type='source_bound_'+module,summary=summary,provenance=provenance,output_files={**entries,**reports,**exports})
