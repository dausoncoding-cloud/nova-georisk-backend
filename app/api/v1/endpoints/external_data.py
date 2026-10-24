import uuid,json,hashlib,os
from datetime import datetime,timezone
from fastapi import APIRouter,Depends,HTTPException,Query,Request,UploadFile,File,Form
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.core.security import verify_internal_secret,get_request_context,RequestContext
from app.db.session import get_db
from app.models.management import ManagedDataset
from app.models.dataset import Dataset
from app.models.project import Project
from app.models.aoi import AOI
from app.models.task import Task
from app.schemas.management import DatasetDraft,DatasetView,DatasetPage,DatasetMetadata,DatasetReview,DatasetEligibility,AuditPage
from app.schemas.source_data import SourceReadinessReview,TemporalCoverage
from app.services.access_management import audit,authorize
from app.api.v1.endpoints.source_data import _authorize
from app.services.external_data import MAX_UPLOAD_BYTES,EXTENSIONS,inspect_upload,scan,path_for,bytes_for,validate_record,view,metadata_bytes,is_source_checkout
from app.core.artifact_storage import require_artifact_storage_ready, artifact_root, ArtifactStorageError
from app.services.source_data.bindings import MODULE_SOURCE_ROLES,OPTIONAL_SOURCE_ROLES
from app.services.source_data.readiness import load_registered_source,SourceNotReady

router=APIRouter(prefix='/projects/{project_id}/external-datasets',tags=['External data management'],dependencies=[Depends(verify_internal_secret)])


def access(db,context,project_id,write=False):
    if context.is_service:raise HTTPException(403,'Organization user context required.')
    _authorize(db,context,project_id,read_only=not write)


def record_for(db,context,project_id,dataset_id,write=False,lock=False):
    access(db,context,project_id,write)
    query=db.query(ManagedDataset).filter(ManagedDataset.id==dataset_id,ManagedDataset.project_id==project_id,ManagedDataset.organization_id==context.organization_id)
    if lock:query=query.with_for_update()
    record=query.one_or_none()
    if record is None:raise HTTPException(404,'Dataset not found.')
    if write and context.role.value == "analyst" and record.uploader_id != context.user_id:
        raise HTTPException(403,"Analysts may modify their own upload versions only.")
    return record


def check_aoi(db,project_id,aoi_id):
    if aoi_id:
        aoi=db.get(AOI,aoi_id)
        if aoi is None or aoi.project_id!=project_id:raise HTTPException(404,'AOI not found in this project.')


@router.get('',response_model=DatasetPage)
def listing(project_id:uuid.UUID,q:str=Query('',max_length=100),category:str|None=None,status:str|None=None,offset:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=100),db:Session=Depends(get_db),context:RequestContext=Depends(get_request_context)):
    access(db,context,project_id)
    query=db.query(ManagedDataset).filter(ManagedDataset.project_id==project_id,ManagedDataset.organization_id==context.organization_id)
    if q:query=query.filter(ManagedDataset.title.ilike('%'+q+'%'))
    if category:query=query.filter(ManagedDataset.category==category)
    if status:query=query.filter(ManagedDataset.status==status)
    return {'total':query.count(),'items':[view(d) for d in query.order_by(ManagedDataset.created_at.desc(),ManagedDataset.id).offset(offset).limit(limit).all()]}


@router.post('',response_model=DatasetView,status_code=201)
async def upload(project_id:uuid.UUID,request:Request,manifest:str=Form(...),file:UploadFile=File(...),db:Session=Depends(get_db),context:RequestContext=Depends(get_request_context)):
    access(db,context,project_id,True)
    if len(manifest)>65536:raise HTTPException(413,'Metadata exceeds 64 KiB.')
    scan(manifest.encode())
    try:body=DatasetDraft.model_validate_json(manifest)
    except ValidationError:raise HTTPException(422,'Invalid upload metadata.')
    metadata_bytes(body.metadata)
    check_aoi(db,project_id,body.aoi_id)
    data=await file.read(MAX_UPLOAD_BYTES+1)
    fmt=inspect_upload(body.category,data,file.filename or '')
    series=uuid.uuid4();version=1
    # Serialize additions to a version chain on the project; no replacement overwrites prior bytes.
    db.query(Project).filter(Project.id==project_id).with_for_update().one()
    if body.replaces:
        prior=record_for(db,context,project_id,body.replaces,True)
        series=prior.series_id
        version=max(x[0] for x in db.query(ManagedDataset.version).filter(ManagedDataset.series_id==series).all())+1
        if prior.category!=body.category:raise HTTPException(422,'Replacement versions must retain dataset type.')
    identifier=uuid.uuid4();key=f'external-datasets/{context.organization_id}/{project_id}/{identifier}{EXTENSIONS[fmt]}'
    root=artifact_root()
    # External bytes must never be stored anywhere in a source checkout/build context.
    repo=__import__('pathlib').Path(__file__).resolve().parents[4]
    if root==repo or any(is_source_checkout(p) for p in [root,*root.parents]) or (repo/'app')==root or (repo/'app') in root.parents:raise HTTPException(503,'Configure protected storage outside the source checkout.')
    try:root=require_artifact_storage_ready()
    except ArtifactStorageError:raise HTTPException(503,'Protected dataset storage is unavailable.')
    path=root/key
    try:path.resolve().relative_to(root)
    except ValueError:raise HTTPException(503,'Protected storage path is outside the configured root.')
    directory=root
    for component in key.split('/')[:-1]:
        directory=directory/component;directory.mkdir(mode=0o700,exist_ok=True);directory.chmod(0o700)
    record=ManagedDataset(id=identifier,series_id=series,version=version,organization_id=context.organization_id,project_id=project_id,aoi_id=body.aoi_id,uploader_id=context.user_id,title=body.title,category=body.category,format=fmt,status='Uploaded',sha256=hashlib.sha256(data).hexdigest(),size_bytes=len(data),storage_key=key,metadata_json=body.metadata,validation={})
    try:
        with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        db.add(record);audit(db,context,request,'dataset.upload',None,{'id':str(identifier),'version':version,'sha256':record.sha256,'status':'Uploaded'})
        db.commit();db.refresh(record)
    except Exception:
        db.rollback();path.unlink(missing_ok=True);raise
    return view(record)


@router.get('/contract')
def upload_contract(project_id:uuid.UUID,db:Session=Depends(get_db),context:RequestContext=Depends(get_request_context)) -> dict:
    access(db,context,project_id)
    from app.schemas.source_data import SourceDatasetManifest
    return {'upload_manifest':DatasetDraft.model_json_schema(),'scientific_manifest':SourceDatasetManifest.model_json_schema(),'max_file_bytes':MAX_UPLOAD_BYTES,'formats':['csv','geojson','geotiff'],'archives_supported':False}


@router.get('/{dataset_id}',response_model=DatasetView)
def detail(project_id:uuid.UUID,dataset_id:uuid.UUID,db:Session=Depends(get_db),context:RequestContext=Depends(get_request_context)):
    return view(record_for(db,context,project_id,dataset_id))


@router.patch('/{dataset_id}/metadata',response_model=DatasetView)
def metadata(project_id:uuid.UUID,dataset_id:uuid.UUID,body:DatasetMetadata,request:Request,db:Session=Depends(get_db),context:RequestContext=Depends(get_request_context)):
    record=record_for(db,context,project_id,dataset_id,True,True)
    if record.source_dataset_id or record.status=='Archived':raise HTTPException(409,'Create a new version to change frozen scientific metadata.')
    if "aoi_id" in body.model_fields_set:
        check_aoi(db,project_id,body.aoi_id);record.aoi_id=body.aoi_id
    metadata_bytes(body.metadata)
    previous={'metadata_sha256':hashlib.sha256(json.dumps(record.metadata_json,sort_keys=True).encode()).hexdigest(),'status':record.status}
    record.metadata_json=body.metadata;record.status='Uploaded';record.validation={}
    audit(db,context,request,'dataset.metadata',previous,{'id':str(record.id),'metadata_sha256':hashlib.sha256(json.dumps(body.metadata,sort_keys=True).encode()).hexdigest(),'status':record.status})
    db.commit();return view(record)


@router.post('/{dataset_id}/validate',response_model=DatasetView)
def validate(project_id:uuid.UUID,dataset_id:uuid.UUID,request:Request,db:Session=Depends(get_db),context:RequestContext=Depends(get_request_context)):
    record=record_for(db,context,project_id,dataset_id,True,True)
    if record.status=='Archived':raise HTTPException(409,'Archived datasets cannot be validated.')
    previous=record.status;validate_record(db,record)
    audit(db,context,request,'dataset.validate',{'status':previous},{'id':str(record.id),'status':record.status})
    db.commit();return view(record)


@router.post('/{dataset_id}/review',response_model=DatasetView)
def review(project_id:uuid.UUID,dataset_id:uuid.UUID,body:DatasetReview,request:Request,db:Session=Depends(get_db),context:RequestContext=Depends(get_request_context)):
    record=record_for(db,context,project_id,dataset_id,True,True);authorize(db,context)
    if record.status=='Archived':raise HTTPException(409,'Archived datasets cannot be reviewed.')
    if body.decision=='approve' and record.uploader_id==context.user_id:raise HTTPException(403,'A different organization admin/owner must perform scientific review.')
    scan(body.reason.encode())
    previous=record.status
    source=db.get(Dataset,record.source_dataset_id) if record.source_dataset_id else None
    if body.decision=='approve':
        if source is None or record.status not in ['Needs Scientific Review','Rejected']:raise HTTPException(409,'Structural validation is required before approval.')
        try:checks=SourceReadinessReview.model_validate(body.review)
        except ValidationError:raise HTTPException(422,'Complete all scientific checks and provide evidence references.')
        metadata_bytes(checks.model_dump())
        try:load_registered_source(db,source.id,project_id,require_ready=False)
        except SourceNotReady as exc:raise HTTPException(422,str(exc))
        evidence={'analysis_ready':True,'sha256':record.sha256,'reviewed_by':str(context.user_id),'reviewed_at':datetime.now(timezone.utc).isoformat(),'evidence_refs':checks.evidence_refs,'checks_complete':True,'checks':checks.model_dump(exclude={'evidence_refs'})}
        source.metadata_json={**source.metadata_json,'readiness':evidence};record.status='Approved for Analysis'
    else:
        if source:source.metadata_json={**source.metadata_json,'readiness':{'analysis_ready':False}}
        record.status='Rejected' if body.decision=='reject' else 'Needs Scientific Review'
    record.validation={**record.validation,'review':{'decision':body.decision,'reason':body.reason,'reviewer_id':str(context.user_id),'reviewed_at':datetime.now(timezone.utc).isoformat()}}
    audit(db,context,request,'dataset.'+body.decision,{'status':previous},{'id':str(record.id),'status':record.status,'reason':body.reason})
    db.commit();return view(record)


@router.delete('/{dataset_id}',response_model=DatasetView)
def archive(project_id:uuid.UUID,dataset_id:uuid.UUID,request:Request,db:Session=Depends(get_db),context:RequestContext=Depends(get_request_context)):
    record=record_for(db,context,project_id,dataset_id,True,True);previous=record.status
    if record.source_dataset_id:
        source=db.get(Dataset,record.source_dataset_id);source.metadata_json={**source.metadata_json,'readiness':{'analysis_ready':False}}
    record.status='Archived';audit(db,context,request,'dataset.archive',{'status':previous},{'id':str(record.id),'status':record.status})
    db.commit();return view(record)


@router.get('/{dataset_id}/versions',response_model=list[DatasetView])
def versions(project_id:uuid.UUID,dataset_id:uuid.UUID,db:Session=Depends(get_db),context:RequestContext=Depends(get_request_context)):
    record=record_for(db,context,project_id,dataset_id)
    return [view(x) for x in db.query(ManagedDataset).filter(ManagedDataset.series_id==record.series_id,ManagedDataset.project_id==project_id).order_by(ManagedDataset.version.desc()).all()]


@router.get('/{dataset_id}/download', response_class=FileResponse, responses={200:{'content':{'application/octet-stream':{'schema':{'type':'string','format':'binary'}}}}})
def download(project_id:uuid.UUID,dataset_id:uuid.UUID,db:Session=Depends(get_db),context:RequestContext=Depends(get_request_context)):
    record=record_for(db,context,project_id,dataset_id);bytes_for(record)
    return FileResponse(path_for(record),filename=f'dataset-{record.id}-v{record.version}{EXTENSIONS[record.format]}',media_type='application/octet-stream',headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})


@router.get('/{dataset_id}/eligibility',response_model=DatasetEligibility)
def eligibility(project_id:uuid.UUID,dataset_id:uuid.UUID,aoi_id:uuid.UUID|None=None,start:datetime|None=None,end:datetime|None=None,db:Session=Depends(get_db),context:RequestContext=Depends(get_request_context)):
    record=record_for(db,context,project_id,dataset_id);reasons=[]
    approved=record.status=='Approved for Analysis'
    if not approved:reasons.append('Scientific approval is required.')
    if not aoi_id or not start or not end:reasons.append('Select a target AOI and timezone-aware analysis period.')
    else:
        check_aoi(db,project_id,aoi_id)
        try:period=TemporalCoverage(start=start,end=end)
        except ValidationError:raise HTTPException(422,'Invalid analysis period.')
        if record.aoi_id and record.aoi_id!=aoi_id:reasons.append('Dataset is attached to a different AOI.')
        if approved:
            try:
                src=load_registered_source(db,record.source_dataset_id,project_id)
                from geoalchemy2.shape import to_shape
                bounds=to_shape(db.get(AOI,aoi_id).geometry).bounds;c=src.manifest.geographic_coverage
                if not(c.west<=bounds[0] and c.south<=bounds[1] and c.east>=bounds[2] and c.north>=bounds[3]):reasons.append('Declared coverage does not contain the AOI.')
                if src.manifest.temporal_coverage.start>period.start or src.manifest.temporal_coverage.end<period.end:reasons.append('Dataset does not cover the analysis period.')
            except SourceNotReady as exc:reasons.append(str(exc))
    candidates=[module for module,roles in MODULE_SOURCE_ROLES.items() if record.category in roles.values() or record.category in OPTIONAL_SOURCE_ROLES.get(module,{}).values()]
    return {'dataset_id':record.id,'approved':approved,'compatible':not reasons,'reasons':reasons,'candidate_modules':candidates,'note':'Candidate input only. Complete bindings, upstream products, CRS/datum and scientific module checks remain mandatory; upload or approval alone does not unlock a product.'}


@router.get('/{dataset_id}/usage')
def usage(project_id:uuid.UUID,dataset_id:uuid.UUID,db:Session=Depends(get_db),context:RequestContext=Depends(get_request_context)) -> dict:
    record=record_for(db,context,project_id,dataset_id)
    tasks=[]
    if record.source_dataset_id:
        from sqlalchemy import cast,func
        from sqlalchemy.dialects.postgresql import JSONB,JSONPATH
        exact=func.jsonb_path_exists(Task.input_params,cast('$.source_binding.sources.* ? (@ == $id)',JSONPATH),cast({'id':str(record.source_dataset_id)},JSONB))
        tasks=db.query(Task).filter(Task.project_id==project_id,exact).order_by(Task.created_at.desc()).limit(100).all()
    return {'source_dataset_id':record.source_dataset_id,'tasks':[{'task_id':str(t.id),'created_at':t.created_at} for t in tasks],'history_note':'Exact registered source IDs and checksums remain pinned in task input lineage; replacing a version never updates historical tasks.'}
