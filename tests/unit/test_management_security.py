import io,zipfile
import pytest
from fastapi import HTTPException
from app.services.access_management import check_transition
from app.models.identity import MembershipRole as R
from app.services.external_data import inspect_upload,scan,MAX_UPLOAD_BYTES

@pytest.mark.parametrize('old,new',[(R.VIEWER,R.ANALYST),(R.ANALYST,R.VIEWER),(None,R.VIEWER)])
def test_admin_allowed_boundary(old,new):check_transition(R.ADMIN,old,new)

@pytest.mark.parametrize('old,new',[(R.OWNER,R.VIEWER),(R.ADMIN,R.ANALYST),(R.VIEWER,R.OWNER),(None,R.ADMIN)])
def test_admin_privilege_boundary(old,new):
    with pytest.raises(HTTPException):check_transition(R.ADMIN,old,new)

@pytest.mark.parametrize('role',list(R))
def test_self_mutations_forbidden(role):
    with pytest.raises(HTTPException):check_transition(R.OWNER,role,R.OWNER,self_change=True)

@pytest.mark.parametrize('name',['../file.csv','a/b.csv','a\\b.csv','file.exe','file.zip','file.kml','file.gpkg'])
def test_unsafe_names_and_unsupported_archives(name):
    with pytest.raises(HTTPException):inspect_upload('rainfall_stations',b'a,b\n1,2\n',name)

def test_archive_bomb_never_extracted():
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('../../unsafe',b'0'*1000000)
    with pytest.raises(HTTPException):inspect_upload('rainfall_stations',out.getvalue(),'bomb.zip')

@pytest.mark.parametrize('data',[b'-----BEGIN PRIVATE KEY-----',b'{"type":"service_account"}',b'{"client_secret":"redacted"}'])
def test_credentials_prohibited(data):
    with pytest.raises(HTTPException):scan(data)

@pytest.mark.parametrize('data',[b'',b'a,a\n1,2\n',b'a,b\n1\n',b'a,b\n=EXEC(),x\n',b'a,b\n'])
def test_malformed_csv(data):
    with pytest.raises(HTTPException):inspect_upload('rainfall_stations',data,'file.csv')

def test_upload_size():
    with pytest.raises(HTTPException) as e:inspect_upload('rainfall_stations',b'x'*(MAX_UPLOAD_BYTES+1),'file.csv')
    assert e.value.status_code==413

def test_generic_csv_inspection_is_not_scientific_approval():
    assert inspect_upload('rainfall_stations',b'station_id,longitude,latitude,observed_at,rainfall_mm,quality_flag\ns1,36,-1,2020-01-01T00:00:00Z,1,valid\n','file.csv')=='csv'

def test_invalid_geometry():
    raw=b'{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Polygon","coordinates":[[[0,0],[1,1],[1,0],[0,1],[0,0]]]},"properties":{}}]}'
    with pytest.raises(HTTPException):inspect_upload('administrative_boundaries',raw,'f.geojson')

def test_vrt_not_accepted_as_tiff():
    with pytest.raises(HTTPException):inspect_upload('terrain_dem',b'<VRTDataset/>','file.tif')

@pytest.mark.parametrize('value',[{'bad':float('nan')},{'bad':'\x00'},{'bad':'\ud800'}])
def test_non_json_metadata_rejected(value):
    from app.services.external_data import metadata_bytes
    with pytest.raises(HTTPException):metadata_bytes(value)

@pytest.mark.parametrize('signature',[b'#!/bin/sh\necho a\n',b'MZpayload',b'\x7fELFpayload'])
def test_executable_signatures_rejected(signature):
    with pytest.raises(HTTPException):inspect_upload('rainfall_stations',signature,'file.csv')
