"""Safe private upload lifecycle; existing FIRRIS gates remain authoritative."""
import csv,hashlib,io,json,re,uuid,os
from pathlib import Path
from fastapi import HTTPException
from pydantic import ValidationError
from rasterio.io import MemoryFile
from shapely.geometry import shape
from app.core.artifact_storage import require_artifact_storage_ready, artifact_root
from app.models.management import ManagedDataset
from app.models.dataset import Dataset
from app.models.aoi import AOI
from app.schemas.source_data import SourceDatasetManifest
from app.services.source_data.catalogue import get_profile
from app.services.source_data.validators import validate_source_data, SourceDataValidationError

MAX_UPLOAD_BYTES=16*1024*1024
EXTENSIONS={'csv':'.csv','geojson':'.geojson','geotiff':'.tif'}
CREDENTIAL=re.compile(rb'-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----|"type"\s*:\s*"service_account"|["\'](?:client_secret|access_token|refresh_token|private_key|password)["\']\s*:',re.I)


def scan(data):
    if CREDENTIAL.search(data):raise HTTPException(422,'Credential material is prohibited in external datasets or metadata.')


def inspect_upload(category,data,filename):
    try:profile=get_profile(category)
    except ValueError:raise HTTPException(422,'Unknown dataset category.')
    fmt=profile['format']
    if not filename or '/' in filename or '\\' in filename or '\x00' in filename or not filename.lower().endswith(EXTENSIONS[fmt]):
        raise HTTPException(422,'Use the category’s supported CSV, GeoJSON or .tif format with a plain filename. Archives and executables are not accepted.')
    if not 0<len(data)<=MAX_UPLOAD_BYTES:raise HTTPException(413,'Dataset must be nonempty and at most 16 MiB.')
    scan(data)
    if data.startswith((b'MZ',b'\x7fELF',b'#!',b'PK\x03\x04',b'PK\x05\x06')):raise HTTPException(422,'Executable and archive content is prohibited.')
    try:
        if fmt=='csv':
            reader=csv.reader(io.StringIO(data.decode('utf-8-sig')),strict=True);header=next(reader)
            if not header or len(header)!=len(set(header)) or set(header)!=set(profile['required_fields']):raise ValueError()
            count=0;seen=set()
            for row in reader:
                count+=1
                if count>100000 or len(row)!=len(header) or any(not v.strip() for v in row) or tuple(row) in seen:raise ValueError()
                seen.add(tuple(row))
                if any(v.startswith(('=','+','@')) for v in row):raise ValueError()
            if not count:raise ValueError()
        elif fmt=='geojson':
            obj=json.loads(data)
            features=obj.get('features')
            if obj.get('type')!='FeatureCollection' or not isinstance(features,list) or not 0<len(features)<=100000:raise ValueError()
            for f in features:
                geom=shape(f['geometry'])
                if geom.is_empty or not geom.is_valid or geom.geom_type not in ['Point','MultiPoint','LineString','MultiLineString','Polygon','MultiPolygon']:raise ValueError()
        else:
            if data[:4] not in [b'II*\x00',b'MM\x00*',b'II+\x00',b'MM\x00+']:raise ValueError()
            with MemoryFile(data) as memory,memory.open() as src:
                if src.dtypes[0] not in ['uint8','int8','uint16','int16','uint32','int32','uint64','int64','float32','float64']:raise ValueError()
                if src.driver!='GTiff' or src.count!=1 or not src.crs or src.width*src.height>4_000_000 or src.width*src.height==0:raise ValueError()
                if src.transform.b or src.transform.d or src.transform.a<=0 or src.transform.e>=0:raise ValueError()
    except Exception as exc:
        if isinstance(exc,HTTPException):raise
        raise HTTPException(422,{'csv':'CSV must have the exact catalogue header, nonempty consistent rows, no duplicate records or executable cells, and at most 100,000 records.','geojson':'GeoJSON must be a nonempty FeatureCollection with valid supported geometry and at most 100,000 features.','geotiff':'GeoTIFF must be single-band GTiff with valid CRS, numeric dtype, north-up transform and at most 4,000,000 pixels.'}[fmt]) from exc
    return fmt


def path_for(record):
    root=artifact_root().resolve()
    try:
        path=(root/record.storage_key).resolve(strict=True);path.relative_to(root)
        if not path.is_file() or path.stat().st_size>MAX_UPLOAD_BYTES:raise ValueError()
    except (OSError,ValueError):raise HTTPException(409,'Protected dataset bytes are unavailable.')
    return path


def bytes_for(record):
    data=path_for(record).read_bytes()
    if hashlib.sha256(data).hexdigest()!=record.sha256:raise HTTPException(409,'Dataset checksum mismatch; analysis is blocked.')
    return data


def validate_record(db,record):
    # A validated source registration is frozen; retries cannot mutate referenced scientific metadata.
    if record.source_dataset_id:return
    data=bytes_for(record)
    for field,expected in [('project_id',str(record.project_id)),('category',record.category),('sha256',record.sha256)]:
        if field in record.metadata_json and str(record.metadata_json[field])!=expected:
            record.status='Rejected';record.validation={'valid':False,'reason':'Supplied project, category or checksum does not match the stored version.'};return
    metadata=dict(record.metadata_json)
    notes=metadata.pop('management',{})
    band_identity=metadata.pop('band_identity',None)
    raster_details={}
    if record.format=='geotiff':
        with MemoryFile(data) as memory,memory.open() as src:
            if not band_identity or not src.descriptions[0]:
                record.status='Needs Metadata';record.validation={'valid':False,'reason':'Provide band_identity and a matching named TIFF band description.'};return
            if src.descriptions[0]!=band_identity:
                record.status='Rejected';record.validation={'valid':False,'reason':'Raster band identity differs from the declared metadata.'};return
            raster_details={'crs':src.crs.to_string(),'transform':list(src.transform),'resolution':list(src.res),'nodata':src.nodata,'band_count':src.count,'band_identity':src.descriptions[0],'dtype':src.dtypes[0],'pixel_count':src.width*src.height}
    try:
        manifest=SourceDatasetManifest.model_validate({**metadata,'project_id':record.project_id,'category':record.category,'sha256':record.sha256})
    except (ValidationError,ValueError) as exc:
        record.status='Needs Metadata'
        fields=[list(e['loc']) for e in exc.errors(include_input=False,include_url=False)] if isinstance(exc,ValidationError) else []
        record.validation={'valid':False,'reason':'Complete the scientific manifest using the catalogue requirements.','fields':fields,'errors':[{'field':list(e['loc']),'message':e['msg']} for e in exc.errors(include_input=False,include_url=False)] if isinstance(exc,ValidationError) else []};return
    try:report=validate_source_data(manifest,data,'dataset'+EXTENSIONS[record.format])
    except SourceDataValidationError as exc:
        record.status='Rejected';record.validation={'valid':False,'reason':str(exc)};return
    source=Dataset(project_id=record.project_id,source_collection=manifest.source_id,product_type=record.category,
        acquisition_start=manifest.temporal_coverage.start,acquisition_end=manifest.temporal_coverage.end,
        processed_asset_ref=str(path_for(record)),metadata_json={'source_manifest':manifest.model_dump(mode='json'),'validation':report.model_dump(mode='json'),'managed_version':{'id':str(record.id),'series_id':str(record.series_id),'version':record.version,'aoi_id':str(record.aoi_id) if record.aoi_id else None,'descriptive_metadata':notes}})
    db.add(source);db.flush();record.source_dataset_id=source.id
    record.status='Needs Scientific Review';record.validation={**report.model_dump(mode='json'),'structurally_valid':True,'analysis_ready':False,'raster':({**raster_details,'valid_pixel_fraction':report.record_count/raster_details['pixel_count']} if raster_details else None)}


def view(record):
    return {k:getattr(record,k) for k in ['id','series_id','version','project_id','aoi_id','uploader_id','source_dataset_id','title','category','format','status','sha256','size_bytes','validation','created_at']}|{'metadata':record.metadata_json}


def metadata_bytes(value):
    try:
        raw=json.dumps(value,allow_nan=False,ensure_ascii=False).encode('utf-8')
    except (ValueError,UnicodeError,TypeError):raise HTTPException(422,'Metadata must contain finite, valid JSON values.')
    if b'\\u0000' in raw:raise HTTPException(422,'Metadata cannot contain null characters.')
    if len(raw)>65536:raise HTTPException(413,'Metadata exceeds 64 KiB.')
    scan(raw)
    return raw


def is_source_checkout(directory):
    marker=directory/'.git'
    if marker.is_dir():return (marker/'HEAD').is_file()
    if marker.is_file():
        try:return marker.read_text()[:512].startswith('gitdir: ')
        except (OSError,UnicodeError):return True
    return False
