import json
import pytest
from test_access import environment, switch
from app.routers import syncro

@pytest.fixture
def source(monkeypatch):
    calls=[]
    def get(self,path,params=None):
        calls.append((path,params))
        if path=='/customers/42':return {'customer':{'id':42,'business_name':'Imported Clinic','address':'123 Test St','city':'Lethbridge','latitude':49.7,'longitude':-112.8,'online_profile_url':'SECRET','notes':'PASSWORD'}}
        if path=='/customers':return {'customers':[{'id':42,'business_name':'Imported Clinic'}],'meta':{'total_pages':1}}
        if (params or {}).get('page',1)>1:return {'assets':[],'meta':{'total_pages':2}}
        rows={
          '/contacts':('contacts',[{'id':1,'customer_id':42,'name':'Test Contact','email':'test@example.invalid','properties':{'password':'SECRET'}}]),
          '/customer_assets':('assets',[{'id':2,'customer_id':42,'name':'Test machine','asset_type':'server','asset_serial':'S123','properties':{'IPv4':'192.0.2.1/24','IPv6':'2001:db8::1/64','MAC':'00:11:22:33:44:55','password':'SECRET'}}]),
          '/tickets':('tickets',[{'id':3,'customer_id':42,'subject':'A ticket','status':'New','assets':[{'id':2}]}]),
          '/invoices':('invoices',[{'id':4,'customer_id':42,'number':'INV1','total':'25.00'},{'id':5,'customer_id':999,'number':'PRIVATE'}])}
        key,value=rows[path];return {key:value,'meta':{'total_pages':1}}
    monkeypatch.setattr(syncro.Client,'get',get)
    return calls

def setup(admin):
    assert admin.put('/api/syncro/settings',json={'subdomain':'example','api_key':'TEST-SECRET'}).status_code==200

def test_syncro_review_import_and_scope(environment,source):
    admin,staff,areas=environment;setup(admin)
    assert 'TEST-SECRET' not in admin.get('/api/syncro/settings').text
    assert staff.get('/api/syncro/customers').status_code==403
    preview=admin.post('/api/syncro/preview',json={'customer_id':42})
    assert preview.status_code==200,preview.text
    assert 'SECRET' not in preview.text and 'PRIVATE' not in preview.text
    draft=preview.json()
    assert len(draft['records']['assets'][0]['addresses'])==2
    result=admin.post('/api/syncro/import',json={'token':draft['token'],'name':'Reviewed clinic','area_id':areas['Lethbridge']})
    assert result.status_code==200,result.text
    cid=result.json()['clinic_id']
    clinic=admin.get(f'/api/clinics/{cid}').json()
    assert clinic['name']=='Reviewed clinic' and clinic['lat']==49.7
    assert len(clinic['contacts'])==1
    records=admin.get(f'/api/syncro/clinics/{cid}').json()['records']
    asset=next(r for r in records if r['kind']=='assets');did=asset['local_id']
    device=admin.get(f'/api/devices/{did}').json()
    assert device['uplink_id'] is None and len(device['tickets'])==1
    network=admin.get(f'/api/devices/{did}/network').json()
    assert {a['version'] for a in network['interfaces'][0]['addresses']}=={4,6}
    assert admin.post('/api/syncro/import',json={'token':draft['token'],'name':'again','area_id':areas['Lethbridge']}).status_code==409
    admin.put(f'/api/devices/{did}',json={'device_type':'server','name':'Local correction'})
    draft=admin.post('/api/syncro/preview',json={'customer_id':42}).json()
    repeat=admin.post('/api/syncro/import',json={'token':draft['token'],'name':'again','area_id':areas['Lethbridge']})
    assert repeat.json()['created']==0
    assert admin.get(f'/api/devices/{did}').json()['name']=='Local correction'
    switch(staff,'it')
    visible=staff.get(f'/api/syncro/clinics/{cid}')
    assert visible.status_code==200,visible.text
    assert 'invoices' not in visible.text
    switch(staff,'sales')
    assert 'assets' not in staff.get(f'/api/syncro/clinics/{cid}').text
    assert staff.get('/api/syncro/clinics/3').status_code==404

def test_missing_permission_is_not_empty_success(environment,source,monkeypatch):
    admin,_,areas=environment;setup(admin)
    original=syncro.Client.get
    def get(self,path,params=None):
        if path=='/invoices':raise syncro.HTTPException(502,'Syncro returned HTTP 403')
        return original(self,path,params)
    monkeypatch.setattr(syncro.Client,'get',get)
    data=admin.post('/api/syncro/preview',json={'customer_id':42}).json()
    assert data['warnings'] and 'invoices' not in data['records']
    assert admin.post('/api/syncro/import',json={'token':data['token'],'name':'test','area_id':9999}).status_code==422

def test_readonly_transport_rejects_unknown_paths(environment):
    admin,_,_=environment;setup(admin)
    from app.database import get_db
    with get_db() as conn:
        client=syncro.Client(conn)
        with pytest.raises(ValueError):client.get('/scripts/run')
    assert admin.put('/api/syncro/settings',json={'subdomain':'evil.example/path','api_key':'x'}).status_code==422

def test_transport_uses_get_header_auth_and_redacts_errors(environment,monkeypatch):
    admin,_,_=environment;setup(admin)
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,limit):return b'{"customers":[],"meta":{"total_pages":1}}'
    requests=[]
    class Opener:
        def open(self,request,timeout):
            requests.append(request)
            return Response()
    monkeypatch.setattr(syncro,'build_opener',lambda *args:Opener())
    response=admin.get('/api/syncro/customers')
    assert response.status_code==200,response.text
    assert requests[0].method=='GET'
    assert requests[0].headers['Authorization']=='Bearer TEST-SECRET'
    assert 'TEST-SECRET' not in requests[0].full_url
    class Broken:
        def open(self,*args,**kwargs):raise syncro.HTTPError('https://example',403,'TEST-SECRET',{},None)
    monkeypatch.setattr(syncro,'build_opener',lambda *args:Broken())
    response=admin.get('/api/syncro/customers')
    assert response.status_code==502 and 'TEST-SECRET' not in response.text
