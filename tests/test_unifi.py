"""Official-contract-shaped fixtures; never contacts a real UniFi account."""
import copy
import json
import pytest
from fastapi import HTTPException
from app import database
from app.routers import unifi
from app.unifi_client import Client
from app.unifi_mapping import device, network, match
from test_access import environment, switch

@pytest.fixture
def source(monkeypatch):
    records={
        '/v1/hosts':[{'id':'console:1','reportedState':{'name':'Office','secret':'NO-COPY'},'userData':{'email':'NO-COPY'}}],
        '/v1/sites':[{'id':'site-1','name':'Clinic network'}],
        '/v1/sites/site-1/devices':[{'id':'switch-1','name':'Switch','features':['switching'],'macAddress':'00:11:22:33:44:01','ipAddress':'10.0.0.2','model':'USW'}],
        '/v1/sites/site-1/clients':[{'id':'pc-1','type':'WIRED','name':'Syncro PC','macAddress':'00:11:22:33:44:02','ipAddress':'10.0.0.3','uplinkDeviceId':'switch-1'},
                                     {'id':'phone-1','type':'WIRELESS','name':'Phone','macAddress':'00:11:22:33:44:03','ipAddress':'10.0.0.4','uplinkDeviceId':'switch-1'}],
        '/v1/sites/site-1/networks':[{'id':'network-1','name':'LAN','vlanId':10,'management':'GATEWAY'}],
        '/v1/sites/site-1/vpn/site-to-site-tunnels':[{'id':'vpn-1','name':'Remote','type':'IPSEC','password':'NO-COPY'}],
    }
    details={
        '/v1/sites/site-1/devices/switch-1':records['/v1/sites/site-1/devices'][0]|{'interfaces':{'ports':[{'idx':1,'connector':'RJ45','maxSpeedMbps':1000,'speedMbps':100,'state':'UP'}]},'password':'NO-COPY'},
        '/v1/sites/site-1/networks/network-1':records['/v1/sites/site-1/networks'][0]|{'ipv4Configuration':{'hostIpAddress':'10.0.0.1','prefixLength':24},'ipv6Configuration':{'interfaceType':'STATIC','hostIpAddress':'fd00::1','prefixLength':64}},
    }
    def get(self,path,host=None,params=None):
        assert host in (None,'console:1')
        if path in details:return copy.deepcopy(details[path])
        rows=copy.deepcopy(records[path]);return {'data':rows,'totalCount':len(rows)}
    monkeypatch.setattr(Client,'get',get)
    return records,details

def setup(admin):
    assert admin.put('/api/unifi/settings',json={'api_key':'TEST-KEY'}).status_code==200

def preview(admin,cid=1,location=None):
    result=admin.post('/api/unifi/preview',json={'host_id':'console:1','site_id':'site-1','clinic_id':cid,'location_id':location})
    assert result.status_code==200,result.text
    return result.json()

def body(draft,**kwargs):
    return {'token':draft['token'],'decisions':[{'kind':r['kind'],'id':r['id'],'action':r['proposal']['action'],'device_id':r['proposal']['device_id']} for r in draft['records'] if 'proposal' in r],**kwargs}

def test_review_import_and_syncro_match(environment,source):
    admin,staff,_=environment;setup(admin)
    with database.get_db() as conn:
        conn.execute("UPDATE devices SET mac_address='00:11:22:33:44:02',ip_address=NULL WHERE id=1")
        conn.execute('DELETE FROM network_interfaces WHERE device_id=1')
    draft=preview(admin)
    assert draft['records'][1]['proposal']['action']=='match'
    assert 'NO-COPY' not in json.dumps(draft)
    assert admin.get('/api/unifi/settings').json()=={'configured':True}
    assert 'NO-COPY' not in admin.get('/api/unifi/hosts').text
    with database.get_db() as conn:assert conn.execute('SELECT COUNT(*) FROM devices').fetchone()[0]==1
    result=admin.post('/api/unifi/import',json=body(draft,import_uplinks=True))
    assert result.status_code==200,result.text
    assert result.json()['created']==2 and result.json()['matched']==1
    assert result.json()['uplinks_added']==2 and result.json()['vlans_added']==1
    assert admin.post('/api/unifi/import',json=body(draft)).status_code==409
    with database.get_db() as conn:
        pc=conn.execute('SELECT * FROM devices WHERE id=1').fetchone()
        assert pc['name']=='Secret device' and pc['ip_address']=='10.0.0.3' and pc['uplink_id']
        assert conn.execute('SELECT COUNT(*) FROM network_interfaces WHERE device_id=?',(pc['uplink_id'],)).fetchone()[0]==2
        assert json.loads(conn.execute('SELECT subnets FROM vlans').fetchone()[0])==['10.0.0.0/24','fd00::/64']
        assert conn.execute('SELECT COUNT(*) FROM vpn_links').fetchone()[0]==0
        assert conn.execute("SELECT COUNT(*) FROM topology_audit WHERE request_path='/api/unifi/import'").fetchone()[0]>0
    second=preview(admin)
    result=admin.post('/api/unifi/import',json=body(second,import_uplinks=True))
    assert result.status_code==200,result.text
    assert result.json()['created']==0 and result.json()['vlans_added']==0
    switch(staff,'it')
    assert staff.get('/api/unifi/clinics/1').status_code==200
    assert staff.get('/api/unifi/clinics/3').status_code==404
    assert staff.get('/api/unifi/hosts').status_code==403
    assert staff.post('/api/unifi/preview',json={}).status_code==403
    switch(staff,'manager')
    assert staff.get('/api/unifi/clinics/1').status_code==403

def test_stale_preview_scope_and_key_rotation(environment,source):
    admin,_,_=environment;setup(admin)
    draft=preview(admin)
    with database.get_db() as conn:conn.execute("UPDATE devices SET notes='Manual change' WHERE id=1")
    assert admin.post('/api/unifi/import',json=body(draft)).status_code==409
    draft=preview(admin);payload=body(draft)
    payload['decisions'][0].update(action='match',device_id=999)
    assert admin.post('/api/unifi/import',json=payload).status_code==422
    with database.get_db() as conn:assert conn.execute('SELECT COUNT(*) FROM unifi_records').fetchone()[0]==0
    setup(admin)
    assert admin.post('/api/unifi/import',json=body(draft)).status_code==409
    assert admin.post('/api/unifi/preview',json={'host_id':'../secret','site_id':'site-1','clinic_id':1}).status_code==422

def test_preserve_manual_fields_and_optional_wiring(environment,source):
    admin,_,_=environment;setup(admin)
    with database.get_db() as conn:
        conn.execute("UPDATE devices SET mac_address='00:11:22:33:44:02',model='Manual model' WHERE id=1")
        iid=conn.execute("INSERT INTO network_interfaces(device_id,name,mac_address,notes) VALUES (1,'Manual NIC','00:11:22:33:44:02','Manual notes')").lastrowid
        conn.execute("INSERT INTO network_addresses(interface_id,address,version,is_primary) VALUES (?,'10.0.0.1',4,1)",(iid,))
        conn.execute("INSERT INTO vlans(clinic_id,tag,name,subnets) VALUES (1,10,'Manual VLAN','[\"10.5.0.0/24\"]')")
    draft=preview(admin);result=admin.post('/api/unifi/import',json=body(draft))
    assert result.status_code==200,result.text
    with database.get_db() as conn:
        pc=conn.execute('SELECT * FROM devices WHERE id=1').fetchone()
        assert pc['model']=='Manual model' and pc['ip_address']=='10.0.0.1' and pc['uplink_id'] is None
        assert conn.execute('SELECT COUNT(*) FROM network_addresses WHERE interface_id=?',(iid,)).fetchone()[0]==1
        assert conn.execute('SELECT name FROM vlans').fetchone()[0]=='Manual VLAN'
    assert preview_mapping_conflict(admin)==409

def preview_mapping_conflict(admin):
    return admin.post('/api/unifi/preview',json={'host_id':'console:1','site_id':'site-1','clinic_id':2}).status_code

def test_match_does_not_use_ip_alone_or_cross_sites():
    r=device('clients',{'id':'x','name':'PC','macAddress':'00:11:22:33:44:55','ipAddress':'10.0.0.1'})
    local=[{'id':1,'name':'Other','mac_address':'','ip_address':'10.0.0.1','interfaces':[]}]
    assert match(r,local)['action']=='skip'
    local[0]['mac_address']=r['mac']
    assert match(r,local)['device_id']==1
    assert match(r,local+[local[0]|{'id':2}])['action']=='skip'
    assert match(r,[],linked=1)['action']=='skip'
    assert match(r,[])['action']=='create'

def test_optional_categories_fail_visibly_and_inventory_failure_aborts(environment,source,monkeypatch):
    admin,_,_=environment;setup(admin);original=Client.get
    def get(self,path,host=None,params=None):
        if '/networks' in path:raise HTTPException(502,'Permission denied')
        return original(self,path,host,params)
    monkeypatch.setattr(Client,'get',get)
    assert preview(admin)['warnings']
    def broken(self,path,host=None,params=None):raise HTTPException(502,'Unavailable')
    monkeypatch.setattr(Client,'get',broken)
    assert admin.post('/api/unifi/preview',json={'host_id':'console:1','site_id':'site-1','clinic_id':1}).status_code==502

def test_transport_get_only_and_pagination(monkeypatch):
    import app.unifi_client as transport
    calls=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,*args):return b'{"data":[],"totalCount":0}'
    class Opener:
        def open(self,req,timeout):calls.append(req);return Response()
    monkeypatch.setattr(transport,'build_opener',lambda *args:Opener())
    monkeypatch.setattr(transport.time,'sleep',lambda *args:None)
    c=Client('PRIVATE-KEY');assert c.collection('/v1/sites','console:1')==[]
    req=calls[0]
    assert req.method=='GET' and req.get_header('X-api-key')=='PRIVATE-KEY'
    assert req.full_url.startswith('https://api.ui.com/v1/connector/consoles/console:1/proxy/network/integration/v1/sites?')
    assert 'PRIVATE-KEY' not in req.full_url
    for path in ('/v1/sites/site/actions','/v1/sites/site/devices/device/actions','/v1/sites/../hosts','https://evil.invalid'):
        with pytest.raises(ValueError):c.get(path,'console:1')
    with pytest.raises(ValueError):c.get('/v1/sites','console/evil')
    with pytest.raises(ValueError):c.get('/v1/devices')
    pages=[]
    def get(path,host=None,params=None):
        pages.append(params)
        return {'data':[{'id':'a'}],'totalCount':2} if params['offset']==0 else {'data':[{'id':'b'}],'totalCount':2}
    monkeypatch.setattr(c,'get',get)
    assert len(c.collection('/v1/sites','console:1'))==2 and pages[-1]['offset']==1

def test_network_mapping_does_not_copy_secrets():
    r=network({'id':'x','vlanId':2,'name':'LAN','ipv4Configuration':{'hostIpAddress':'192.168.1.1','prefixLength':24,'password':'secret'},'privateKey':'secret'})
    assert r['subnets']==['192.168.1.0/24'] and 'secret' not in json.dumps(r)

def test_secondary_site_match_scope_and_vm_host_preservation(environment,source):
    admin,_,_=environment;setup(admin)
    with database.get_db() as conn:
        location=conn.execute("INSERT INTO clinic_locations(clinic_id,name) VALUES (1,'Branch')").lastrowid
        conn.execute("UPDATE devices SET mac_address='00:11:22:33:44:02' WHERE id=1")
    draft=preview(admin,location=location)
    pc=next(r for r in draft['records'] if r['id']=='pc-1')
    assert pc['proposal']['action']=='create'  # Same MAC elsewhere cannot merge across sites.
    with database.get_db() as conn:
        host=conn.execute("INSERT INTO devices(clinic_id,location_id,name,device_type) VALUES (1,?,'Hypervisor','server')",(location,)).lastrowid
        vm=conn.execute("INSERT INTO devices(clinic_id,location_id,name,device_type,mac_address,uplink_id) VALUES (1,?,'VM','vm','00:11:22:33:44:02',?)",(location,host)).lastrowid
    draft=preview(admin,location=location)
    response=admin.post('/api/unifi/import',json=body(draft,import_uplinks=True))
    assert response.status_code==200,response.text
    with database.get_db() as conn:
        assert conn.execute('SELECT uplink_id FROM devices WHERE id=?',(vm,)).fetchone()[0]==host

def test_atomic_import_rollback_and_deleted_device_not_recreated(environment,source):
    admin,_,_=environment;setup(admin)
    draft=preview(admin);payload=body(draft)
    payload['decisions'][-1].update(action='match',device_id=999)
    assert admin.post('/api/unifi/import',json=payload).status_code==422
    with database.get_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM devices').fetchone()[0]==1
        assert conn.execute('SELECT COUNT(*) FROM unifi_sites').fetchone()[0]==0
    assert admin.post('/api/unifi/import',json=body(draft)).status_code==200
    with database.get_db() as conn:
        did=conn.execute("SELECT local_id FROM unifi_records WHERE external_id='switch-1'").fetchone()[0]
        conn.execute('DELETE FROM devices WHERE id=?',(did,))
    draft=preview(admin)
    assert next(r for r in draft['records'] if r['id']=='switch-1')['proposal']['action']=='skip'

def test_transport_errors_do_not_expose_key_or_body(monkeypatch):
    from urllib.error import HTTPError
    import app.unifi_client as transport
    class Opener:
        def open(self,*args,**kwargs):raise HTTPError('https://api.ui.com',403,'PRIVATE-KEY',{},None)
    monkeypatch.setattr(transport,'build_opener',lambda *args:Opener())
    monkeypatch.setattr(transport.time,'sleep',lambda *args:None)
    with pytest.raises(HTTPException) as err:Client('PRIVATE-KEY').get('/v1/hosts')
    assert '403' in err.value.detail and 'PRIVATE-KEY' not in err.value.detail
    c=Client('key')
    monkeypatch.setattr(c,'get',lambda *args,**kwargs:{'data':[{'id':'same'}],'totalCount':5})
    with pytest.raises(HTTPException):c.collection('/v1/sites','console:1')

def test_invalid_identity_macs_not_used():
    for value in ('00:00:00:00:00:00','ff:ff:ff:ff:ff:ff','01:00:5e:00:00:01'):
        assert device('clients',{'macAddress':value})['mac']==''
