import uuid,json,hashlib
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from app.models.identity import Organization,User,OrganizationMembership,MembershipRole as R
from app.models.platform import OrganizationEngineEntitlement,EntitlementStatus
from app.models.project import Project
from app.models.management import AccessAudit,ManagedDataset
from app.core.config import get_settings
from app.bff.membership import resolve_membership,MembershipResolutionError
from app.bff.oidc import OIDCClaims
from tests.integration.test_source_data_ingestion import _manifest


def setup_org(db):
    org=Organization(name='Management test',slug=str(uuid.uuid4()));db.add(org);db.flush()
    people={}
    for role in R:
        u=User(issuer='https://issuer.test/',subject=str(uuid.uuid4()),email=role.value+'@example.test',display_name=role.value,is_active=True)
        db.add(u);db.flush();db.add(OrganizationMembership(organization_id=org.id,user_id=u.id,role=role));people[role.value]=u
    db.add(OrganizationEngineEntitlement(organization_id=org.id,engine_key='firris',status=EntitlementStatus.ACTIVE,source='test'))
    project=Project(name='Data management',organization_id=org.id,engine_key='firris');db.add(project);db.commit()
    def headers(role):return {'X-Nova-Organization-Id':str(org.id),'X-Nova-User-Id':str(people[role].id),'X-Nova-Role':role}
    return org,people,project,headers


@pytest.mark.parametrize('role',['viewer','analyst'])
def test_non_administrators_cannot_manage(client,db_session,role):
    org,people,project,h=setup_org(db_session);base=f'/api/v1/organizations/{org.id}/administration'
    assert client.get(base+'/memberships',headers=h(role)).status_code==403
    assert client.patch(base+'/memberships/'+str(people['viewer'].id),headers=h(role),json={'role':'owner','status':'active'}).status_code==403


def test_role_changes_tenant_and_audit(client,db_session):
    org,p,project,h=setup_org(db_session);base=f'/api/v1/organizations/{org.id}/administration'
    change=lambda target,role,status='active',actor='admin':client.patch(base+'/memberships/'+str(p[target].id),headers=h(actor),json={'role':role,'status':status})
    assert change('viewer','analyst').status_code==200
    assert change('viewer','owner').status_code==403
    assert change('owner','viewer').status_code==403
    assert change('admin','owner').status_code==403
    assert change('owner','viewer',actor='owner').status_code==403
    assert change('viewer','owner',actor='owner').status_code==200
    assert change('analyst','viewer','disabled').status_code==200
    assert client.get('/api/v1/organizations/current',headers=h('analyst')).status_code==403
    assert change('analyst','viewer','active').status_code==200
    assert change('analyst','viewer','removed').status_code==200
    assert db_session.query(User).filter(User.id==p['analyst'].id).one()
    assert client.get(f'/api/v1/organizations/{uuid.uuid4()}/administration/memberships',headers=h('owner')).status_code==404
    logs=client.get(base+'/audit',headers=h('owner')).json();assert logs['total']==5
    event=logs['items'][0];assert event['actor_user_id']==str(p['admin'].id) and event['previous'] and event['current']
    with pytest.raises(DBAPIError):
        db_session.execute(text('DELETE FROM access_audit'));db_session.flush()
    db_session.rollback()


def test_disabled_cannot_resolve_strict_login(client,db_session):
    org,p,project,h=setup_org(db_session)
    m=db_session.get(OrganizationMembership,(org.id,p['analyst'].id));m.status='disabled';db_session.commit()
    claims=OIDCClaims(issuer=p['analyst'].issuer,subject=p['analyst'].subject,email=p['analyst'].email,email_verified=True,display_name='Analyst')
    with pytest.raises(MembershipResolutionError):resolve_membership(db_session,claims=claims,policy='strict',invitation_token=None,organization_id=org.id)


def test_dataset_lifecycle_and_isolation(client,db_session,monkeypatch,tmp_path):
    org,p,project,h=setup_org(db_session);settings=get_settings();monkeypatch.setattr(settings,'output_storage_dir',str(tmp_path))
    base=f'/api/v1/projects/{project.id}/external-datasets'
    data=b'station_id,longitude,latitude,observed_at,rainfall_mm,quality_flag\ng1,36,-1,2020-06-01T00:00:00Z,12,valid\n'
    def upload(metadata=None,replaces=None,actor='analyst'):
        return client.post(base,headers=h(actor),data={'manifest':json.dumps({'title':'Rain gauges','category':'rainfall_stations','metadata':metadata or {},'replaces':replaces})},files={'file':('rain.csv',data,'text/csv')})
    assert upload(actor='viewer').status_code==403
    response=upload();assert response.status_code==201,response.text
    d=response.json();key=d['id'];assert d['status']=='Uploaded' and d['sha256']==hashlib.sha256(data).hexdigest() and 'storage_key' not in d
    assert client.post(base+'/'+key+'/validate',headers=h('analyst')).json()['status']=='Needs Metadata'
    metadata=json.loads(_manifest(project.id,data));metadata.pop('project_id');metadata.pop('category');metadata.pop('sha256')
    assert client.patch(base+'/'+key+'/metadata',headers=h('analyst'),json={'metadata':metadata}).status_code==200
    valid=client.post(base+'/'+key+'/validate',headers=h('analyst'));assert valid.status_code==200,valid.text
    assert valid.json()['status']=='Needs Scientific Review'
    assert not client.get(base+'/'+key+'/eligibility',headers=h('viewer')).json()['compatible']
    assert client.patch(base+'/'+key+'/metadata',headers=h('analyst'),json={'metadata':metadata}).status_code==409
    checks={'evidence_refs':['fixture:independent-review'],**{x:True for x in ['qa_verified','licence_verified','provenance_verified','crs_datum_verified','temporal_coverage_verified','uncertainty_reviewed']}}
    body={'decision':'approve','reason':'Scientific checks reviewed','review':checks}
    assert client.post(base+'/'+key+'/review',headers=h('analyst'),json=body).status_code==403
    review=client.post(base+'/'+key+'/review',headers=h('owner'),json=body);assert review.status_code==200,review.text
    assert review.json()['status']=='Approved for Analysis'
    source_id=review.json()['source_dataset_id']
    assert client.post('/api/v1/source-datasets/'+source_id+'/approve',headers=h('owner'),json=checks).status_code==409
    replacement=upload(metadata,key).json();assert replacement['version']==2 and replacement['sha256']==d['sha256'] and replacement['id']!=key
    assert len(client.get(base+'/'+key+'/versions',headers=h('viewer')).json())==2
    assert client.get(base+'/'+key+'/download',headers=h('viewer')).content==data
    assert client.delete(base+'/'+key,headers=h('analyst')).json()['status']=='Archived'
    from app.services.source_data.readiness import load_registered_source,SourceNotReady
    with pytest.raises(SourceNotReady):load_registered_source(db_session,uuid.UUID(source_id),project.id)
    foreign=client.get(f'/api/v1/projects/{uuid.uuid4()}/external-datasets/{key}',headers=h('owner'));assert foreign.status_code==404
    assert db_session.query(ManagedDataset).count()==2


def test_provision_scoped_existing_identity(client,db_session,monkeypatch):
    org,p,project,h=setup_org(db_session);monkeypatch.setattr(get_settings(),'oidc_issuer_url','https://issuer.test/')
    base=f'/api/v1/organizations/{org.id}/administration'
    body={'issuer':'https://issuer.test/','subject':'verified-provider-subject','role':'analyst','evidence_reference':'identity-ticket-123'}
    response=client.post(base+'/memberships',headers=h('admin'),json=body);assert response.status_code==201,response.text
    body['role']='owner';assert client.post(base+'/memberships',headers=h('admin'),json=body).status_code==403
    assert client.get(base+'/invitations',headers=h('owner')).json()==[]


def test_concurrent_owner_changes_keep_one_owner(db_session):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy.orm import sessionmaker
    from fastapi import Request,HTTPException
    from app.core.security import RequestContext,OrganizationRole
    from app.services.access_management import mutate
    org,p,project,h=setup_org(db_session)
    second=User(issuer='https://issuer.test/',subject=str(uuid.uuid4()),is_active=True)
    db_session.add(second);db_session.flush();db_session.add(OrganizationMembership(organization_id=org.id,user_id=second.id,role=R.OWNER));db_session.commit()
    first_id=p['owner'].id;second_id=second.id;org_id=org.id
    factory=sessionmaker(bind=db_session.get_bind());barrier=Barrier(2)
    def demote(actor,target):
        with factory() as db:
            context=RequestContext(user_id=actor,organization_id=org_id,role=OrganizationRole.OWNER)
            request=Request({'type':'http','state':{'request_id':str(uuid.uuid4())}})
            user=db.get(User,target);barrier.wait(timeout=20)
            try:mutate(db,context,request,user,R.VIEWER,'active');return 200
            except HTTPException as e:db.rollback();return e.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(demote,first_id,second_id);b=pool.submit(demote,second_id,first_id)
        outcomes=sorted([a.result(timeout=60),b.result(timeout=60)])
    assert outcomes==[200,403]
    db_session.expire_all()
    assert db_session.query(OrganizationMembership).filter_by(organization_id=org_id,role=R.OWNER,status='active').count()==1
    assert db_session.query(AccessAudit).count()==1


def test_real_cross_org_resource_is_hidden(client,db_session):
    first,_,_,h=setup_org(db_session);other,_,foreign,_=setup_org(db_session)
    assert client.get(f'/api/v1/projects/{foreign.id}/external-datasets',headers=h('owner')).status_code==404
    assert client.get(f'/api/v1/organizations/{other.id}/administration/memberships',headers=h('owner')).status_code==404


def test_upload_metadata_and_byte_integrity(client,db_session,monkeypatch,tmp_path):
    org,p,project,h=setup_org(db_session);monkeypatch.setattr(get_settings(),'output_storage_dir',str(tmp_path))
    base=f'/api/v1/projects/{project.id}/external-datasets'
    data=b'station_id,longitude,latitude,observed_at,rainfall_mm,quality_flag\ng1,36,-1,2020-06-01T00:00:00Z,12,valid\n'
    response=client.post(base,headers=h('analyst'),data={'manifest':json.dumps({'title':'Gauge','category':'rainfall_stations'})},files={'file':('rain.csv',data)})
    assert response.status_code==201
    identifier=response.json()['id'];record=db_session.get(ManagedDataset,uuid.UUID(identifier))
    bad=client.patch(base+'/'+identifier+'/metadata',headers=h('analyst'),json={'metadata':{'client_secret':'synthetic-prohibited'}})
    assert bad.status_code==422 and 'synthetic-prohibited' not in bad.text
    (tmp_path/record.storage_key).write_bytes(b'changed')
    assert client.get(base+'/'+identifier+'/download',headers=h('viewer')).status_code==409
    assert client.post(base+'/'+identifier+'/validate',headers=h('analyst')).status_code==409
    assert client.get(base+'/'+identifier+'/eligibility',headers=h('viewer')).json()['compatible'] is False


def test_private_storage_and_exact_usage(client,db_session,monkeypatch,tmp_path):
    import stat
    from app.models.task import Task,TaskType
    org,p,project,h=setup_org(db_session);monkeypatch.setattr(get_settings(),'output_storage_dir',str(tmp_path))
    base=f'/api/v1/projects/{project.id}/external-datasets'
    data=b'station_id,longitude,latitude,observed_at,rainfall_mm,quality_flag\ng1,36,-1,2020-06-01T00:00:00Z,12,valid\n'
    metadata=json.loads(_manifest(project.id,data));[metadata.pop(k) for k in ['project_id','category','sha256']]
    response=client.post(base,headers=h('analyst'),data={'manifest':json.dumps({'title':'Gauge','category':'rainfall_stations','metadata':metadata})},files={'file':('rain.csv',data)})
    assert response.status_code==201,response.text
    identifier=response.json()['id'];record=db_session.get(ManagedDataset,uuid.UUID(identifier))
    assert stat.S_IMODE((tmp_path/record.storage_key).stat().st_mode)==0o600
    assert stat.S_IMODE((tmp_path/record.storage_key).parent.stat().st_mode)==0o700
    registered=client.post(base+'/'+identifier+'/validate',headers=h('analyst')).json();source_id=registered['source_dataset_id']
    actual=Task(project_id=project.id,task_type=TaskType.ANALYSIS,input_params={'source_binding':{'sources':{'rainfall':source_id}}})
    unrelated=Task(project_id=project.id,task_type=TaskType.ANALYSIS,input_params={'unrelated_note':source_id})
    db_session.add_all([actual,unrelated]);db_session.commit()
    result=client.get(base+'/'+identifier+'/usage',headers=h('viewer')).json()
    assert [t['task_id'] for t in result['tasks']]==[str(actual.id)]


def test_audit_truncate_is_rejected(client,db_session):
    org,p,project,h=setup_org(db_session)
    path=f'/api/v1/organizations/{org.id}/administration/memberships/{p["viewer"].id}'
    assert client.patch(path,headers=h('admin'),json={'role':'analyst','status':'active'}).status_code==200
    with pytest.raises(DBAPIError):
        db_session.execute(text('TRUNCATE access_audit'));db_session.flush()
    db_session.rollback();assert db_session.query(AccessAudit).count()==1


def test_scientific_self_review_and_rejected_source(client,db_session,monkeypatch,tmp_path):
    org,p,project,h=setup_org(db_session);monkeypatch.setattr(get_settings(),'output_storage_dir',str(tmp_path))
    base=f'/api/v1/projects/{project.id}/external-datasets'
    data=b'station_id,longitude,latitude,observed_at,rainfall_mm,quality_flag\ng1,36,-1,2020-06-01T00:00:00Z,12,valid\n'
    metadata=json.loads(_manifest(project.id,data));[metadata.pop(k) for k in ['project_id','category','sha256']]
    response=client.post(base,headers=h('admin'),data={'manifest':json.dumps({'title':'Gauge','category':'rainfall_stations','metadata':metadata})},files={'file':('rain.csv',data)})
    assert response.status_code==201
    key=response.json()['id'];registered=client.post(base+'/'+key+'/validate',headers=h('admin')).json()
    checks={'evidence_refs':['fixture:independent-review'],**{x:True for x in ['qa_verified','licence_verified','provenance_verified','crs_datum_verified','temporal_coverage_verified','uncertainty_reviewed']}}
    body={'decision':'approve','reason':'Scientific checks reviewed','review':checks}
    assert client.post(base+'/'+key+'/review',headers=h('admin'),json=body).status_code==403
    assert client.post(base+'/'+key+'/review',headers=h('owner'),json=body).status_code==200
    assert client.post(base+'/'+key+'/review',headers=h('owner'),json={'decision':'reject','reason':'Source evidence withdrawn'}).json()['status']=='Rejected'
    from app.services.source_data.readiness import load_registered_source,SourceNotReady
    with pytest.raises(SourceNotReady):load_registered_source(db_session,uuid.UUID(registered['source_dataset_id']),project.id)
