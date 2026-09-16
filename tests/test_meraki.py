"""Synthetic official-contract-shaped fixtures; no production key or network calls."""
import copy
import json
import threading
from urllib.error import HTTPError
import pytest
from fastapi import HTTPException
from app import database, integration_sync as sync
from app.meraki_client import Client
from app.meraki_mapping import device
from test_access import environment, switch

@pytest.fixture(autouse=True)
def no_workers(monkeypatch):
    monkeypatch.setattr(sync,'start',lambda:(threading.Event(),[]))

@pytest.fixture
def source(monkeypatch):
    rows={
      '/organizations':[{'id':'org1','name':'Clinic org','secret':'DO-NOT-COPY'}],
      '/organizations/org1/networks':[{'id':'N_1','organizationId':'org1','name':'Clinic LAN'}],
      '/networks/N_1':{'id':'N_1','organizationId':'org1','name':'Clinic LAN','productTypes':['switch','appliance']},
      '/networks/N_1/devices':[{'serial':'Q123-ABCD-5678','networkId':'N_1','name':'Core switch','productType':'switch','model':'MS120','mac':'00:11:22:33:44:01','lanIp':'10.0.0.2'}],
      '/devices/Q123-ABCD-5678/switch/ports':[{'portId':'1','name':'Office','type':'access','vlan':10,'linkNegotiation':'Auto negotiate','secret':'DO-NOT-COPY'}],
      '/networks/N_1/clients':[{'id':'pc1','description':'PC','mac':'00:11:22:33:44:02','ip':'10.0.0.3','ip6':'fd00::3','status':'Online','recentDeviceSerial':'Q123-ABCD-5678','recentDeviceConnection':'Wired','switchport':'1','vlan':'10','user':'DO-NOT-COPY'},
                              {'id':'phone1','description':'Phone','mac':'00:11:22:33:44:03','ip':'169.254.1.2','status':'Offline','recentDeviceSerial':'Q123-ABCD-5678','recentDeviceConnection':'Wired'}],
      '/networks/N_1/appliance/vlans':[{'id':10,'name':'LAN','subnet':'10.0.0.0/24','applianceIp':'10.0.0.1','dhcpOptions':['DO-NOT-COPY']}],
      '/networks/N_1/appliance/vpn/siteToSiteVpn':{'mode':'spoke','hubs':[{'hubId':'N_2','useDefaultRoute':False}],'subnets':[{'localSubnet':'10.0.0.0/24','useVpn':True}],'secret':'DO-NOT-COPY'},
      '/networks/N_1/topology/linkLayer':{'nodes':[{'derivedId':'switch1','type':'device','device':{'serial':'Q123-ABCD-5678'}}],'links':[]},
    }
    calls=[]
    def page(self,path,params=None):
        calls.append((self.key,path,params));return copy.deepcopy(rows[path]),''
    monkeypatch.setattr(Client,'page',page)
    return rows,calls

def setup(admin,cid=1,key='CLINIC-ONE-KEY'):
    r=admin.put(f'/api/meraki/clinics/{cid}/settings',json={'api_key':key});assert r.status_code==200,r.text

def preview(admin,cid=1,**kwargs):
    r=admin.post('/api/meraki/preview',json={'clinic_id':cid,'organization_id':'org1','network_id':'N_1',**kwargs})
    assert r.status_code==200,r.text
    return r.json()

def body(draft,**kwargs):
    return {'token':draft['token'],'decisions':[{'kind':r['kind'],'id':r['id'],**{k:r['proposal'][k] for k in ('action','device_id')}} for r in draft['records'] if 'proposal' in r],**kwargs}

def test_clinic_credentials_are_isolated_and_not_exposed(environment,source):
    admin,staff,_=environment;setup(admin);setup(admin,2,'CLINIC-TWO-KEY')
    assert admin.get('/api/meraki/clinics/1/organizations').status_code==200
    assert source[1][-1][0]=='CLINIC-ONE-KEY'
    assert admin.get('/api/meraki/clinics/2/organizations').status_code==200
    assert source[1][-1][0]=='CLINIC-TWO-KEY'
    assert admin.get('/api/meraki/clinics/1/settings').json()=={'configured':True}
    assert 'CLINIC-ONE-KEY' not in admin.get('/api/meraki/clinics/1').text
    assert 'CLINIC-ONE-KEY' not in admin.get('/api/export/backup.json').text
    switch(staff,'it')
    assert staff.get('/api/meraki/clinics/1').status_code==200
    assert staff.get('/api/meraki/clinics/3').status_code==404
    for suffix in ('settings','organizations','networks'):
        assert staff.get('/api/meraki/clinics/1/'+suffix).status_code==403
    assert staff.put('/api/meraki/clinics/1/settings',json={'api_key':'NO'}).status_code==403
    switch(staff,'manager');assert staff.get('/api/meraki/clinics/1').status_code==403

def test_review_import_matches_mac_preserves_manual_fields_and_ipv6(environment,source):
    admin,_,_=environment;setup(admin)
    with database.get_db() as c:
        c.execute("UPDATE devices SET mac_address='00:11:22:33:44:02',ip_address=NULL,device_type='vm',model='Manual model' WHERE id=1")
        c.execute('DELETE FROM network_interfaces WHERE device_id=1')
    draft=preview(admin)
    assert 'DO-NOT-COPY' not in json.dumps(draft)
    assert next(r for r in draft['records'] if r['id']=='pc1')['proposal']['device_id']==1
    result=admin.post('/api/meraki/import',json=body(draft,import_uplinks=True));assert result.status_code==200,result.text
    assert result.json()['created']==2 and result.json()['matched']==1 and result.json()['vlans_added']==1
    with database.get_db() as c:
        d=c.execute('SELECT * FROM devices WHERE id=1').fetchone()
        assert d['name']=='Secret device' and d['model']=='Manual model' and d['device_type']=='vm' and d['uplink_id'] is None
        addresses=[r[0] for r in c.execute('SELECT a.address FROM network_addresses a JOIN network_interfaces i ON i.id=a.interface_id WHERE i.device_id=1')]
        assert set(addresses)=={'10.0.0.3','fd00::3'}
        assert c.execute("SELECT COUNT(*) FROM network_interfaces WHERE port_group='Meraki ports'").fetchone()[0]==1
        assert c.execute("SELECT COUNT(*) FROM topology_audit WHERE request_path='/api/meraki/import'").fetchone()[0]>0
        assert c.execute('SELECT COUNT(*) FROM vpn_links').fetchone()[0]==0
    assert admin.post('/api/meraki/import',json=body(draft)).status_code==409
    result=admin.post('/api/meraki/import',json=body(preview(admin)))
    assert result.status_code==200 and result.json()['created']==0

def test_preview_rejects_stale_topology_rotated_keys_wrong_site_and_network(environment,source):
    admin,_,_=environment;setup(admin)
    draft=preview(admin);setup(admin)
    assert admin.post('/api/meraki/import',json=body(draft)).status_code==409
    draft=preview(admin)
    with database.get_db() as c:c.execute("UPDATE devices SET notes='Changed' WHERE id=1")
    assert admin.post('/api/meraki/import',json=body(draft)).status_code==409
    draft=preview(admin);payload=body(draft);payload['decisions'][0].update(action='match',device_id=999)
    assert admin.post('/api/meraki/import',json=payload).status_code==422
    assert admin.post('/api/meraki/import',json=body(draft)).status_code==200
    setup(admin,2,'CLINIC-TWO-KEY')
    assert admin.post('/api/meraki/preview',json={'clinic_id':2,'organization_id':'org1','network_id':'N_1'}).status_code==409
    assert admin.post('/api/meraki/preview',json={'clinic_id':1,'organization_id':'wrong','network_id':'N_1'}).status_code==409
    assert admin.post('/api/meraki/preview',json={'clinic_id':1,'organization_id':'org1','network_id':'../bad'}).status_code==422

def test_sync_uses_clinic_key_updates_owned_ip_preserves_manual_and_reviews_new(environment,source):
    admin,_,_=environment;setup(admin)
    assert admin.post('/api/meraki/import',json=body(preview(admin))).status_code==200
    with database.get_db() as c:
        jid=c.execute("SELECT id FROM integration_jobs WHERE provider='meraki'").fetchone()[0]
        did=c.execute("SELECT local_id FROM meraki_records WHERE external_id='Q123-ABCD-5678'").fetchone()[0]
    def queued():
        admin.put('/api/integration-sync/settings',json={'enabled':True});admin.post(f'/api/integration-sync/jobs/{jid}/now',json={})
        j=sync.claim('meraki');assert j;return j
    source[0]['/networks/N_1/devices'][0]['lanIp']='10.0.0.22'
    source[0]['/networks/N_1/clients'].append({'id':'new1','description':'New client','mac':'00:11:22:33:44:04','ip':'10.0.0.4'})
    j=queued();assert sync.apply_result(j,sync.collect(j))
    assert all(key=='CLINIC-ONE-KEY' for key,_,_ in source[1])
    with database.get_db() as c:
        assert c.execute('SELECT ip_address FROM devices WHERE id=?',(did,)).fetchone()[0]=='10.0.0.22'
        assert not c.execute("SELECT id FROM devices WHERE name='New client'").fetchone()
        assert c.execute("SELECT id FROM integration_changes WHERE title LIKE 'New source record:%'").fetchone()
        c.execute("UPDATE network_addresses SET address='10.0.0.99' WHERE interface_id IN (SELECT id FROM network_interfaces WHERE device_id=?)",(did,))
        c.execute("UPDATE devices SET ip_address='10.0.0.99' WHERE id=?",(did,))
    source[0]['/networks/N_1/devices'][0]['lanIp']='10.0.0.23'
    j=queued();assert sync.apply_result(j,sync.collect(j))
    with database.get_db() as c:assert c.execute('SELECT ip_address FROM devices WHERE id=?',(did,)).fetchone()[0]=='10.0.0.99'
    j=queued();result=sync.collect(j);setup(admin,key='ROTATED')
    with pytest.raises(HTTPException):sync.apply_result(j,result)

def test_network_address_filtering():
    for value in ('169.254.1.2','8.8.8.8','127.0.0.1'):
        r=device('clients',{'id':'a','ip':value,'ip6':'fe80::1'});assert r['addresses']==[]
    r=device('clients',{'id':'a','ip':'192.168.1.2','ip6':'2001:db8::1'})
    assert {a['version'] for a in r['addresses']}=={4,6}

def test_optional_uplinks_only_use_online_explicit_client_reports(environment,source):
    admin,_,_=environment;setup(admin)
    result=admin.post('/api/meraki/import',json=body(preview(admin),import_uplinks=True))
    assert result.status_code==200,result.text
    assert result.json()['uplinks_added']==1
    with database.get_db() as c:
        pc=c.execute("SELECT d.* FROM devices d JOIN meraki_records r ON r.local_id=d.id WHERE r.external_id='pc1'").fetchone()
        phone=c.execute("SELECT d.* FROM devices d JOIN meraki_records r ON r.local_id=d.id WHERE r.external_id='phone1'").fetchone()
        assert pc['uplink_id'] and pc['link_type']=='ethernet'
        assert phone['uplink_id'] is None
    setup(admin,key='')
    assert admin.get('/api/meraki/clinics/1/settings').json()=={'configured':False}
    assert admin.get('/api/meraki/clinics/1/organizations').status_code==409
    assert admin.get('/api/meraki/clinics/1').json()['records']

def test_transport_is_get_only_no_redirects_and_rate_limits_are_sanitized(monkeypatch):
    import app.meraki_client as transport
    monkeypatch.setattr(transport,'wait_turn',lambda *args:None)
    seen=[]
    class Response:
        headers={}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,size):return b'[]'
    class Opener:
        def open(self,request,timeout):seen.append(request);return Response()
    monkeypatch.setattr(transport,'build_opener',lambda handler:Opener())
    client=Client('SECRET')
    assert client.collection('/organizations')==[]
    assert seen[0].get_method()=='GET' and 'SECRET' not in seen[0].full_url
    assert transport.NoRedirect().redirect_request(None,None,None,None,None,None) is None
    with pytest.raises(ValueError):client.get('/devices/x/reboot')
    class Failed:
        def open(self,*args,**kwargs):raise HTTPError('https://example.invalid/SECRET',429,'SECRET',{'Retry-After':'120'},None)
    monkeypatch.setattr(transport,'build_opener',lambda handler:Failed())
    monkeypatch.setattr(transport,'backoff',lambda provider,value:value)
    with pytest.raises(HTTPException) as exc:client.collection('/organizations')
    assert exc.value.status_code==429 and exc.value.headers['Retry-After']=='120' and 'SECRET' not in exc.value.detail

def test_pagination_preserves_filters_and_rejects_external_next_link(monkeypatch):
    calls=[]
    def page(self,path,params=None):
        calls.append(dict(params or {}))
        return ([{'id':'a'}],'<https://api.meraki.com/api/v1/networks/N_1/clients?startingAfter=a>; rel="next"') if len(calls)==1 else ([{'id':'b'}],'')
    monkeypatch.setattr(Client,'page',page)
    assert len(Client('key').collection('/networks/N_1/clients',{'timespan':86400}))==2
    assert calls[1]=={'timespan':86400,'startingAfter':'a'}
    monkeypatch.setattr(Client,'page',lambda *args:([{'id':'a'}],'<https://evil.invalid/api/v1/organizations?startingAfter=a>; rel="next"'))
    with pytest.raises(HTTPException):Client('key').collection('/organizations')

def test_core_failure_aborts_and_optional_failure_is_warning(environment,source,monkeypatch):
    admin,_,_=environment;setup(admin);original=Client.page
    def failed(self,path,params=None):
        if path.endswith('topology/linkLayer'):raise HTTPException(502,'Unavailable')
        return original(self,path,params)
    monkeypatch.setattr(Client,'page',failed)
    assert preview(admin)['warnings']
    def core_failed(self,path,params=None):
        if path.endswith('/clients'):raise HTTPException(502,'Unavailable')
        return original(self,path,params)
    monkeypatch.setattr(Client,'page',core_failed)
    assert admin.post('/api/meraki/preview',json={'clinic_id':1,'organization_id':'org1','network_id':'N_1'}).status_code==502
    with database.get_db() as c:assert c.execute('SELECT COUNT(*) FROM meraki_records').fetchone()[0]==0
