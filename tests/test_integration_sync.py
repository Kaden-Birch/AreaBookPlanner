import copy
import json
import threading
import time
import pytest
from fastapi import HTTPException
from app import database, integration_sync as sync
from app.routers import syncro
from test_access import environment, switch
from test_syncro import source as syncro_source, setup as syncro_setup
from test_unifi import source as unifi_source, setup as unifi_setup, preview as unifi_preview, body as unifi_body

@pytest.fixture(autouse=True)
def no_background_threads(monkeypatch):
    monkeypatch.setattr(sync,'start',lambda:(threading.Event(),[]))

@pytest.fixture
def imported(environment,syncro_source):
    admin,staff,areas=environment
    syncro_setup(admin)
    p=admin.post('/api/syncro/preview',json={'customer_id':42}).json()
    result=admin.post('/api/syncro/import',json={'token':p['token'],'name':'Imported clinic','area_id':areas['Lethbridge']})
    assert result.status_code==200,result.text
    cid=result.json()['clinic_id']
    with database.get_db() as c:
        did=c.execute("SELECT local_id FROM syncro_records WHERE clinic_id=? AND kind='assets'",(cid,)).fetchone()[0]
        jid=c.execute('SELECT id FROM integration_jobs WHERE clinic_id=?',(cid,)).fetchone()[0]
    return admin,staff,cid,did,jid

def queued(admin,jid):
    assert admin.put('/api/integration-sync/settings',json={'enabled':True}).status_code==200
    assert admin.post(f'/api/integration-sync/jobs/{jid}/now',json={}).status_code==200
    j=sync.claim('syncro');assert j
    return j

def change_ip(monkeypatch,value):
    original=syncro.Client.get
    def get(self,path,params=None):
        data=copy.deepcopy(original(self,path,params))
        if path=='/customer_assets/2':data['asset']['properties']['IPv4']=value+'/24'
        return data
    monkeypatch.setattr(syncro.Client,'get',get)

def test_owned_ip_updates_but_manual_overrides_stick(imported,monkeypatch):
    admin,_,cid,did,jid=imported
    change_ip(monkeypatch,'192.168.2.77')
    j=queued(admin,jid);result=sync.collect(j);assert sync.apply_result(j,result)
    with database.get_db() as c:
        assert c.execute('SELECT ip_address FROM devices WHERE id=?',(did,)).fetchone()[0]=='192.168.2.77'
        iid=c.execute('SELECT id FROM network_interfaces WHERE device_id=?',(did,)).fetchone()[0]
        assert c.execute('SELECT address FROM network_addresses WHERE interface_id=? AND version=4',(iid,)).fetchone()[0]=='192.168.2.77'
        c.execute("UPDATE devices SET ip_address='192.168.2.99' WHERE id=?",(did,))
        c.execute("UPDATE network_addresses SET address='192.168.2.99' WHERE interface_id=? AND version=4",(iid,))
    change_ip(monkeypatch,'192.168.2.88')
    j=queued(admin,jid);assert sync.apply_result(j,sync.collect(j))
    with database.get_db() as c:
        assert c.execute('SELECT ip_address FROM devices WHERE id=?',(did,)).fetchone()[0]=='192.168.2.99'
        assert c.execute('SELECT COUNT(*) FROM integration_fields WHERE overridden=1').fetchone()[0]>=1
        assert c.execute('SELECT last_success FROM integration_jobs WHERE id=?',(jid,)).fetchone()[0]
    assert admin.get(f'/api/integration-sync/clinics/{cid}').json()['changes']

def test_no_auto_creation_or_deletion_and_review_is_deduplicated(imported):
    admin,_,cid,did,jid=imported
    j=queued(admin,jid);r=sync.collect(j)
    r['records']=[x for x in r['records'] if x[0]!='assets']+[('assets','new',{'id':'new','name':'New machine'})]
    with database.get_db() as c:before=c.execute('SELECT COUNT(*) FROM devices').fetchone()[0]
    assert sync.apply_result(j,r)
    changes=admin.get(f'/api/integration-sync/clinics/{cid}').json()['changes']
    assert len(changes)==2
    for change in changes:assert admin.post(f"/api/integration-sync/changes/{change['id']}/acknowledge",json={}).status_code==200
    j=queued(admin,jid);assert sync.apply_result(j,r)
    with database.get_db() as c:assert c.execute('SELECT COUNT(*) FROM devices').fetchone()[0]==before
    assert admin.get(f'/api/integration-sync/clinics/{cid}').json()['changes']==[]

def test_queue_pause_permissions_and_provider_lease(imported):
    admin,staff,cid,did,jid=imported
    assert sync.claim('syncro') is None  # Upgrade is opt-in.
    j=queued(admin,jid)
    assert sync.claim('syncro') is None
    assert admin.put(f'/api/integration-sync/jobs/{jid}',json={'enabled':False,'interval_minutes':30}).status_code==200
    assert not sync.apply_result(j,sync.collect(j))
    assert admin.post(f'/api/integration-sync/jobs/{jid}/now',json={}).status_code==409
    switch(staff,'it')
    assert staff.get(f'/api/integration-sync/clinics/{cid}').status_code==200
    assert staff.get('/api/integration-sync/clinics/3').status_code==404
    assert staff.get('/api/integration-sync/settings').status_code==403
    assert staff.post(f'/api/integration-sync/jobs/{jid}/now',json={}).status_code==403
    switch(staff,'manager')
    assert staff.get(f'/api/integration-sync/clinics/{cid}').status_code==403

def test_failures_preserve_last_success_and_honor_retry_after(imported):
    admin,_,cid,did,jid=imported
    j=queued(admin,jid);assert sync.apply_result(j,sync.collect(j))
    with database.get_db() as c:last=c.execute('SELECT last_success FROM integration_jobs WHERE id=?',(jid,)).fetchone()[0]
    j=queued(admin,jid);start=time.time()
    sync.finish_error(j,HTTPException(429,'Provider rate limit',headers={'Retry-After':'3600'}))
    with database.get_db() as c:
        row=c.execute('SELECT * FROM integration_jobs WHERE id=?',(jid,)).fetchone()
        assert row['next_at']>=start+3600 and row['last_success']==last and row['failures']==1
    j=dict(j,lease='not-owner');sync.finish_error(j,RuntimeError('SECRET'))
    assert 'SECRET' not in admin.get('/api/integration-sync/settings').text

def test_key_rotation_discards_inflight_result(imported):
    admin,_,_,_,jid=imported
    j=queued(admin,jid);r=sync.collect(j)
    admin.put('/api/syncro/settings',json={'subdomain':'test','api_key':'ROTATED'})
    with pytest.raises(HTTPException):sync.apply_result(j,r)

def test_staggering_and_restart_lease_recovery(imported):
    admin,_,cid,_,jid=imported
    with database.get_db() as c:
        c.execute('INSERT INTO syncro_links(tenant,customer_id,clinic_id) VALUES (?,?,?)',('test',99,1))
    response=admin.put('/api/integration-sync/settings',json={'enabled':True})
    assert response.status_code==200,response.text
    jobs=response.json()['jobs'];assert len(jobs)==2 and abs(jobs[1]['next_at']-jobs[0]['next_at'])>=899
    first=sync.claim('syncro');assert first
    with database.get_db() as c:c.execute('UPDATE integration_jobs SET lease_until=? WHERE id=?',(time.time()-1,first['id']))
    second=sync.claim('syncro');assert second and second['lease']!=first['lease']
    assert not sync.apply_result(first,sync.collect(first))

def test_rate_gate_is_durable_and_shared(tmp_path,monkeypatch):
    from app import integration_rate as rate
    monkeypatch.setattr(database,'DATABASE_PATH',str(tmp_path/'pacing.db'))
    sleeps=[]
    monkeypatch.setattr(rate.time,'sleep',lambda value:sleeps.append(value))
    rate.wait_turn('unifi',.7);rate.wait_turn('unifi',.7)
    assert sleeps[-1]>.5
    seconds=rate.backoff('unifi','120')
    with pytest.raises(HTTPException) as exc:rate.wait_turn('unifi',.7)
    assert exc.value.status_code==429 and float(exc.value.headers['Retry-After'])>=119
    rate.wait_turn('syncro',.7)  # Other provider is not blocked.

def test_unifi_refresh_updates_owned_ip_and_reviews_uplink(environment,unifi_source):
    admin,_,_=environment;unifi_setup(admin)
    draft=unifi_preview(admin)
    assert admin.post('/api/unifi/import',json=unifi_body(draft)).status_code==200
    with database.get_db() as c:
        jid=c.execute("SELECT id FROM integration_jobs WHERE provider='unifi'").fetchone()[0]
        did=c.execute("SELECT local_id FROM unifi_records WHERE external_id='switch-1'").fetchone()[0]
    unifi_source[1]['/v1/sites/site-1/devices/switch-1']['ipAddress']='10.0.0.22'
    unifi_source[1]['/v1/sites/site-1/devices/switch-1']['uplink']={'deviceId':'other-switch'}
    admin.put('/api/integration-sync/settings',json={'enabled':True})
    admin.post(f'/api/integration-sync/jobs/{jid}/now',json={})
    j=sync.claim('unifi');assert sync.apply_result(j,sync.collect(j))
    with database.get_db() as c:
        row=c.execute('SELECT * FROM devices WHERE id=?',(did,)).fetchone()
        assert row['ip_address']=='10.0.0.22' and row['uplink_id'] is None
        assert c.execute("SELECT id FROM integration_changes WHERE change_key=?",(f'{did}:uplink',)).fetchone()

def test_financial_changes_not_visible_in_it(imported):
    admin,staff,cid,_,jid=imported
    j=queued(admin,jid);result=sync.collect(j)
    result['records'].append(('invoices','999',{'id':999,'total':'FINANCE-SECRET'}))
    sync.apply_result(j,result)
    assert 'FINANCE-SECRET' in admin.get(f'/api/integration-sync/clinics/{cid}').text
    switch(staff,'it')
    assert 'FINANCE-SECRET' not in staff.get(f'/api/integration-sync/clinics/{cid}').text
