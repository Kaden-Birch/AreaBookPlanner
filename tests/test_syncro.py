import json
import pytest
from test_access import environment, switch
from app.routers import syncro

@pytest.fixture
def source(monkeypatch):
    calls=[]
    def get(self,path,params=None):
        calls.append((path,params))
        if path=='/customer_assets/2':return {'asset':get(self,'/customer_assets',{'page':1})['assets'][0]}
        if path=='/customers/42':return {'customer':{'id':42,'business_name':'Imported Clinic','address':'123 Test St','city':'Lethbridge','latitude':49.7,'longitude':-112.8,'online_profile_url':'SECRET','notes':'PASSWORD'}}
        if path=='/customers':return {'customers':[{'id':42,'business_name':'Imported Clinic'}],'meta':{'total_pages':1}}
        if (params or {}).get('page',1)>1:return {'assets':[],'meta':{'total_pages':2}}
        rows={
          '/contacts':('contacts',[{'id':1,'customer_id':42,'name':'Test Contact','email':'test@example.invalid','properties':{'password':'SECRET'}}]),
          '/customer_assets':('assets',[{'id':2,'customer_id':42,'name':'Test machine','asset_type':'server','asset_serial':'S123','properties':{'IPv4':'192.168.2.1/24','IPv6':'2001:db8::1/64','MAC':'00:11:22:33:44:55','password':'SECRET'}}]),
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

def test_nested_adapters_and_safe_backfill(environment,source,monkeypatch):
    admin,_,areas=environment;setup(admin)
    original=syncro.Client.get
    detailed=False
    def get(self,path,params=None):
        if path=='/customer_assets/2':
            return {'asset':{'id':2,'customer_id':42,'rmm_store':{'network_adapters':[
                {'Name':'Ethernet','MACAddress':'0011.2233.4455','IPAddresses':['192.168.2.20/24','2001:db8::20/64']},
                {'Name':'Wi-Fi','MACAddress':'AA-BB-CC-DD-EE-FF','IPAddress':'192.168.2.21'}] if detailed else []},'properties':{}}}
        result=original(self,path,params)
        if path=='/customer_assets':result['assets'][0]['properties']={}
        return result
    monkeypatch.setattr(syncro.Client,'get',get)
    def run(fill=False):
        draft=admin.post('/api/syncro/preview',json={'customer_id':42,'categories':['assets']})
        assert draft.status_code==200,draft.text
        result=admin.post('/api/syncro/import',json={'token':draft.json()['token'],'name':'Network test','area_id':areas['Lethbridge'],'fill_missing_network':fill})
        assert result.status_code==200,result.text
        return result.json()
    result=run();cid=result['clinic_id']
    did=admin.get(f'/api/syncro/clinics/{cid}').json()['records'][0]['local_id']
    detailed=True
    assert run()['interfaces_added']==0
    assert run(True)['interfaces_added']==2
    network=admin.get(f'/api/devices/{did}/network').json()
    assert [i['mac_address'] for i in network['interfaces']]==['00:11:22:33:44:55','aa:bb:cc:dd:ee:ff']
    assert len(network['interfaces'][0]['addresses'])==2
    assert run(True)['interfaces_added']==0
    assert admin.get(f'/api/devices/{did}/network').json()['interfaces']==network['interfaces']

def test_network_extractor_ignores_public_ip_and_secrets():
    from app.syncro_network import adapters
    rows=adapters({'rmm_store':{'general':{'network_adapters':json.dumps([{'Name':'LAN','MAC':'001122334455','IPAddress':['10.0.0.1','::1','bad']}]),'public_ip':'198.51.100.1','password':'secret'}}})
    assert len(rows)==1 and rows[0]['mac_address']=='00:11:22:33:44:55'
    assert [a['address'] for a in rows[0]['addresses']]==['10.0.0.1']
    assert 'secret' not in json.dumps(rows)

def test_kabuto_adapter_mapping_and_lan_filter():
    from app.syncro_network import adapters
    detail={'general':{'ip':'8.8.8.8','mac':['001122334455','001122334466']},
            'network_adapters':[
                {'name':'Secondary','physical_address':'001122334466','ipv4':'169.254.2.3'},
                {'name':'Ethernet','physical_address':'001122334455','ipv4':'172.16.2.3','subnet':'255.255.255.0','ipv6':'fd00::3/64'}],
            'primary_adapter':{'ipv4':'172.16.2.3','subnet':'255.255.255.0'}}
    rows=adapters({'properties':{'mac':['001122334466','001122334455'],'kabuto_information':detail},'rmm_store':{'general':{'info':json.dumps(detail)}}})
    assert len(rows)==2
    assert rows[0]['name']=='Ethernet'
    assert rows[0]['addresses']==[{'address':'172.16.2.3','version':4,'prefix':24},{'address':'fd00::3','version':6,'prefix':64}]
    assert rows[1]['addresses']==[] and rows[1]['name']=='Secondary'
    addresses=adapters({'IPAddress':['10.0.0.1','192.168.1.1','172.31.255.254','172.32.0.1','169.254.1.1','8.8.8.8','100.64.0.1','127.0.0.1','fe80::1','ff02::1','::ffff:8.8.8.8','2001:db8::1']})[0]['addresses']
    assert [a['address'] for a in addresses]==['10.0.0.1','192.168.1.1','172.31.255.254','2001:db8::1']

def test_repair_mac_only_syncro_adapters(environment):
    from app.database import get_db
    from app.syncro_network import fill_missing,SOURCE_NOTE
    with get_db() as conn:
        did=conn.execute("INSERT INTO devices(clinic_id,device_type,name,mac_address) VALUES (1,'workstation','Imported','00:11:22:33:44:55')").lastrowid
        iid=conn.execute('INSERT INTO network_interfaces(device_id,name,mac_address,notes) VALUES (?,?,?,?)',(did,'Reported adapter','00:11:22:33:44:55',SOURCE_NOTE)).lastrowid
        rows=[{'name':'Ethernet','mac_address':'00:11:22:33:44:55','addresses':[{'address':'10.0.0.3','version':4,'prefix':24},{'address':'fd00::3','version':6,'prefix':64}]}]
        assert fill_missing(conn,did,rows)==1
        assert fill_missing(conn,did,rows)==0
        assert conn.execute('SELECT COUNT(*) FROM network_interfaces WHERE device_id=?',(did,)).fetchone()[0]==1
        assert conn.execute('SELECT COUNT(*) FROM network_addresses WHERE interface_id=?',(iid,)).fetchone()[0]==2
        assert conn.execute('SELECT ip_address FROM devices WHERE id=?',(did,)).fetchone()[0]=='10.0.0.3'

def test_detail_permission_failure_preserves_list_data(environment,source,monkeypatch):
    admin,_,_=environment;setup(admin);original=syncro.Client.get
    def get(self,path,params=None):
        if path=='/customer_assets/2':raise syncro.HTTPException(502,'Syncro returned HTTP 403')
        return original(self,path,params)
    monkeypatch.setattr(syncro.Client,'get',get)
    draft=admin.post('/api/syncro/preview',json={'customer_id':42,'categories':['assets']}).json()
    assert draft['warnings'] and len(draft['records']['assets'][0]['interfaces'])==1

def test_backfill_preserves_legacy_values_and_manual_interface(environment):
    from app.database import get_db
    from app.syncro_network import fill_missing
    _,_,_=environment
    reported=[{'name':'Ethernet','mac_address':'00:11:22:33:44:55','addresses':[{'address':'192.168.2.1','version':4,'prefix':24}]}]
    with get_db() as conn:
        assert fill_missing(conn,1,reported)==0  # fixture has a manually recorded IP
        did=conn.execute("INSERT INTO devices(clinic_id,device_type,name) VALUES (1,'workstation','Manual ports')").lastrowid
        conn.execute("INSERT INTO network_interfaces(device_id,name,notes) VALUES (?,'Port 1','Do not overwrite')",(did,))
        assert fill_missing(conn,did,reported)==0
        assert conn.execute('SELECT notes FROM network_interfaces WHERE device_id=?',(did,)).fetchone()[0]=='Do not overwrite'

def test_network_diagnostic_redaction():
    from app.syncro_diagnostics import network_diagnostics
    report=network_diagnostics({'customer':{'email':'private@example.invalid'},'rmm_store':{'unknown_network_section':json.dumps({'LAN Addresses':'192.168.2.5, 2001:db8::5','MAC Address':'00-11-22-33-44-55','Description':'PRIVATE MACHINE','password':'192.168.2.99','notes':'SECRET'})},'properties':{'API key':'SECRET'}})
    encoded=json.dumps(report)
    assert '192.168.2.5' in encoded and '2001:db8::5' in encoded
    assert '00:11:22:33:44:55' in encoded
    assert all(s not in encoded for s in ('PRIVATE MACHINE','SECRET','192.168.2.99','private@example.invalid'))
    assert any('unknownnetworksection' in r['path'] for r in report['fields'])

def test_network_diagnostic_preview_authorization(environment,source):
    admin,staff,_=environment;setup(admin)
    draft=admin.post('/api/syncro/preview',json={'customer_id':42,'categories':['assets']}).json()
    payload={'token':draft['token'],'asset_id':2}
    result=admin.post('/api/syncro/network-diagnostics',json=payload)
    assert result.status_code==200,result.text
    assert result.headers['cache-control']=='no-store'
    assert '192.168.2.1' in result.text and 'TEST-SECRET' not in result.text
    assert staff.post('/api/syncro/network-diagnostics',json=payload).status_code==403
    assert admin.post('/api/syncro/network-diagnostics',json={**payload,'asset_id':999}).status_code==404
    assert admin.post('/api/syncro/network-diagnostics',json={**payload,'token':'expired'}).status_code==409
