import json
import sqlite3
import threading
import pytest
from fastapi import HTTPException
from app import database, integration_sync as sync
from app.routers import syncro
from test_access import environment, switch
from test_syncro import setup

@pytest.fixture(autouse=True)
def no_workers(monkeypatch):monkeypatch.setattr(sync,'start',lambda:(threading.Event(),[]))

@pytest.fixture
def source(monkeypatch):
    calls=[]
    def get(self,path,params=None):
        calls.append((self.tenant,self.key,path,params))
        if path.startswith('/customers/'):
            cid=int(path.split('/')[-1]);return {'customer':{'id':cid,'business_name':'Practice' if cid==42 else 'Pharmacy'}}
        if path=='/customers':return {'customers':[{'id':42,'business_name':'Practice'},{'id':43,'business_name':'Pharmacy'}]}
        if path.startswith('/customer_assets/'):
            cid=int(path.split('/')[-1])-100;return {'asset':asset(cid)}
        if path=='/customer_assets':return {'assets':[asset(params['customer_id'])],'meta':{'total_pages':1}}
        return {path.strip('/'):[],'meta':{'total_pages':1}}
    def asset(cid):return {'id':cid+100,'customer_id':cid,'name':'Machine '+str(cid),'properties':{'IPv4':f'192.168.1.{cid}','MAC':f'00:11:22:33:44:{cid}'}}
    monkeypatch.setattr(syncro.Client,'get',get)
    return calls

def draft(admin,customer=42,connection=None):
    response=admin.post('/api/syncro/preview',json={'customer_id':customer,'connection_id':connection,'categories':['assets']})
    assert response.status_code==200,response.text
    return response.json()

def imported(admin,areas,customer=42,connection=None,location=None):
    d=draft(admin,customer,connection)
    result=admin.post('/api/syncro/import',json={'token':d['token'],'name':'Do not rename clinic','area_id':areas['Lethbridge'],'clinic_id':1,'location_id':location})
    assert result.status_code==200,result.text
    return result.json()

def test_two_customers_share_site_refreshes_do_not_mark_each_other_missing(environment,source):
    admin,staff,areas=environment;setup(admin)
    imported(admin,areas,42);imported(admin,areas,43)
    assert len(admin.get('/api/syncro/clinics/1').json()['links'])==2
    assert admin.get('/api/clinics/1').json()['name']=='Local client'
    assert imported(admin,areas,43)['created']==0
    admin.put('/api/integration-sync/settings',json={'enabled':True})
    with database.get_db() as c:
        jobs=[dict(r) for r in c.execute("SELECT * FROM integration_jobs WHERE provider='syncro'")]
        assert len(jobs)==2
        assert {r[0] for r in c.execute('SELECT customer_id FROM syncro_records')}=={42,43}
    for job in jobs:
        admin.post(f"/api/integration-sync/jobs/{job['id']}/now",json={})
        j=sync.claim('syncro');assert j
        result=sync.collect(j);assert len(result['records'])==1
        assert sync.apply_result(j,result)
    assert admin.get('/api/integration-sync/clinics/1').json()['changes']==[]
    switch(staff,'it');assert len(staff.get('/api/syncro/clinics/1').json()['links'])==2
    assert staff.get('/api/syncro/connections').status_code==403

def test_multiple_keys_and_tenants_target_same_site_without_colliding_ids(environment,source):
    admin,_,areas=environment;setup(admin)
    rid=admin.post('/api/syncro/connections',json={'name':'Pharmacy','subdomain':'pharmacy','api_key':'SECOND-KEY'}).json()['id']
    imported(admin,areas,42);imported(admin,areas,42,rid)
    assert {r['tenant'] for r in admin.get('/api/syncro/clinics/1').json()['records']}=={'example','pharmacy'}
    assert 'SECOND-KEY' not in admin.get('/api/syncro/connections').text
    assert source[-1][0:2]==('pharmacy','SECOND-KEY')
    with database.get_db() as c:
        job=dict(c.execute("SELECT * FROM integration_jobs WHERE source_key='pharmacy:42'").fetchone())
    admin.put('/api/integration-sync/settings',json={'enabled':True})
    with database.get_db() as c:c.execute('UPDATE integration_jobs SET next_at=0 WHERE id=?',(job['id'],))
    j=sync.claim('syncro');result=sync.collect(j);assert source[-1][1]=='SECOND-KEY'
    admin.put(f'/api/syncro/connections/{rid}',json={'name':'Pharmacy','subdomain':'pharmacy','api_key':'ROTATED'})
    with pytest.raises(HTTPException):sync.apply_result(j,result)
    assert admin.put(f'/api/syncro/connections/{rid}',json={'name':'Pharmacy','subdomain':'different','api_key':'X'}).status_code==409

def test_site_mapping_and_preview_key_rotation(environment,source):
    admin,_,areas=environment;setup(admin)
    location=admin.post('/api/clinics/1/locations',json={'name':'Shared building'}).json()['id']
    imported(admin,areas,42,location=location);imported(admin,areas,43,location=location)
    with database.get_db() as c:
        assert {r[0] for r in c.execute('SELECT d.location_id FROM devices d JOIN syncro_records r ON r.local_id=d.id')}=={location}
    d=draft(admin,43)
    assert d['location_id']==location
    admin.put('/api/syncro/settings',json={'subdomain':'example','api_key':'ROTATED'})
    r=admin.post('/api/syncro/import',json={'token':d['token'],'clinic_id':1,'name':'x','area_id':areas['Lethbridge']})
    assert r.status_code==409

def test_legacy_migration_preserves_ids_and_backfills_source_customer():
    c=sqlite3.connect(':memory:')
    c.execute('CREATE TABLE clinics(id INTEGER PRIMARY KEY)')
    c.execute('CREATE TABLE clinic_locations(id INTEGER PRIMARY KEY)')
    c.execute('INSERT INTO clinics VALUES (1)')
    c.execute('''CREATE TABLE syncro_links(id INTEGER PRIMARY KEY,tenant TEXT NOT NULL,customer_id INTEGER NOT NULL,clinic_id INTEGER NOT NULL,
       updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,UNIQUE(tenant,customer_id),UNIQUE(clinic_id))''')
    c.executescript(syncro.SCHEMA)
    c.execute("INSERT INTO syncro_links(id,tenant,customer_id,clinic_id) VALUES (7,'example',42,1)")
    c.execute("INSERT INTO syncro_records(tenant,kind,external_id,clinic_id,local_id,data) VALUES ('example','assets',142,1,5,'{}')")
    syncro.initialize(c);syncro.initialize(c)
    assert c.execute('SELECT id,customer_id FROM syncro_links').fetchone()==(7,42)
    assert c.execute('SELECT customer_id,local_id FROM syncro_records').fetchone()==(42,5)
    c.execute("INSERT INTO syncro_links(tenant,customer_id,clinic_id) VALUES ('example',43,1)")
    assert c.execute('SELECT COUNT(*) FROM syncro_links').fetchone()[0]==2
