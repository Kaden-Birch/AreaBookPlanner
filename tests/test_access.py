"""Authentication and scope regressions use real HTTP sessions, no auth bypass."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import database

PASSWORD = 'correct horse battery staple'


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DATABASE_PATH', str(tmp_path / 'access.db'))
    with TestClient(app) as admin:
        assert admin.post('/api/auth/setup', json={'username':'admin','password':PASSWORD}).status_code == 200
        for name, lat, lng in [('Lethbridge',49.69,-112.83),('Calgary',51.04,-114.07)]:
            assert admin.post('/api/admin/areas',json={'name':name,'latitude':lat,'longitude':lng}).status_code==200
        areas=admin.get('/api/admin/areas').json()
        aid={a['name']:a['id'] for a in areas}
        assignments=[{'role':r,'area_ids':[aid['Lethbridge']],'default_area_id':aid['Lethbridge']} for r in ['sales','it','manager','client_success']]
        r=admin.post('/api/admin/users',json={'username':'staff','display_name':'Staff','password':PASSWORD,'must_change_password':False,'assignments':assignments})
        assert r.status_code==200,r.text
        with database.get_db() as conn:
            for name, area, rel in [('Local client',aid['Lethbridge'],'current_client'),('Local prospect',aid['Lethbridge'],'prospect'),('Remote secret',aid['Calgary'],'current_client')]:
                conn.execute('INSERT INTO clinics(name,area_id,relationship) VALUES (?,?,?)',(name,area,rel))
            conn.execute("INSERT INTO devices(clinic_id,device_type,name,ip_address,serial) VALUES (1,'workstation','Secret device','10.0.0.1','SECRET-SERIAL')")
            conn.execute("INSERT INTO clinic_notes(clinic_id,body,visibility) VALUES (1,'TECH-SECRET','technical')")
            conn.execute("INSERT INTO clinic_notes(clinic_id,body,visibility) VALUES (3,'REMOTE-SECRET','general')")
        with TestClient(app) as staff:
            assert staff.post('/api/auth/login',json={'username':'staff','password':PASSWORD}).status_code==200
            yield admin,staff,aid


def switch(staff, role):
    r=staff.post('/api/auth/workspace',json={'role':role})
    assert r.status_code==200,r.text


def test_device_open_work_is_explicit_and_scoped(environment):
    _,staff,_=environment
    switch(staff,'it')
    ticket=staff.post('/api/devices/1/tickets',json={'title':'Legacy-like link'}).json()
    assert ticket['status']=='unknown'
    assert staff.patch(f"/api/devices/1/tickets/{ticket['id']}",json={'status':'open'}).status_code==200
    task=staff.post('/api/tasks',json={'title':'Fix device','clinic_id':1,'device_id':1})
    assert task.status_code==201,task.text
    assert task.json()['visibility']=='technical'
    assert staff.post('/api/tasks',json={'title':'Wrong clinic','clinic_id':2,'device_id':1}).status_code==422
    node=staff.get('/api/clinics/1/topology').json()['nodes'][0]
    assert node['open_ticket_count']==1 and node['open_task_count']==1
    assert staff.patch(f"/api/tasks/{task.json()['id']}",json={'done':True}).status_code==200
    assert staff.patch(f"/api/devices/1/tickets/{ticket['id']}",json={'status':'closed'}).status_code==200
    node=staff.get('/api/clinics/1/topology').json()['nodes'][0]
    assert node['open_ticket_count']==0 and node['open_task_count']==0
    switch(staff,'sales')
    assert staff.post('/api/tasks',json={'title':'Not allowed','clinic_id':1,'device_id':1}).status_code==403


def test_cross_site_trace_requires_explicit_transit_and_scope(environment):
    _,staff,areas=environment
    with database.get_db() as conn:
        dest=conn.execute("INSERT INTO clinics(name,area_id,relationship) VALUES ('Destination',?,'current_client')",(areas['Lethbridge'],)).lastrowid
        middle_device=conn.execute("INSERT INTO devices(clinic_id,name,device_type) VALUES (2,'Middle router','router')").lastrowid
        dest_device=conn.execute("INSERT INTO devices(clinic_id,name,device_type) VALUES (?,'Destination router','router')",(dest,)).lastrowid
        first=conn.execute("INSERT INTO vpn_links(name,a_clinic_id,b_clinic_id,a_device_id,b_device_id,status) VALUES ('First',1,2,1,?,'up')",(middle_device,)).lastrowid
        second=conn.execute("INSERT INTO vpn_links(name,a_clinic_id,b_clinic_id,a_device_id,b_device_id,status) VALUES ('Second',2,?,?,?,'unknown')",(dest,middle_device,dest_device)).lastrowid
    switch(staff,'it')
    base='/api/clinics/1/topology/trace'
    query={'source_device_id':1,'destination_clinic_id':dest,'destination_device_id':dest_device}
    assert staff.get(base,params=query).json()['routes']==[]
    with database.get_db() as conn:
        conn.execute('''INSERT INTO vpn_transit_routes(source_clinic_id,entry_vpn_link_id,via_clinic_id,exit_vpn_link_id,dest_clinic_id,rationale)
          VALUES (1,?,2,?,?,'Approved route')''',(first,second,dest))
    response=staff.get(base,params=query)
    assert response.status_code==200,response.text
    route=response.json()['routes'][0]
    assert route['relationship']=='via' and route['documentation_complete']
    assert [s['status'] for s in route['segments'] if s['kind']=='vpn']==['up','unknown']
    assert staff.get(base,params=query|{'destination_clinic_id':3}).status_code==404
    reverse=staff.get(f'/api/clinics/{dest}/topology/trace',params={'source_device_id':dest_device,'destination_clinic_id':1,'destination_device_id':1})
    assert reverse.json()['routes']==[]
    with database.get_db() as conn:conn.execute("UPDATE vpn_links SET status='disabled' WHERE id=?",(second,))
    assert staff.get(base,params=query).json()['routes']==[]
    switch(staff,'sales')
    assert staff.get(base,params=query).status_code==403


def test_logical_groups_scoped_audited_and_non_destructive(environment):
    _,staff,_=environment
    switch(staff,'it')
    path='/api/clinics/1/topology/groups'
    payload={'name':'Core','color':'#123456','device_ids':[1]}
    created=staff.put(path+'/0',json=payload)
    assert created.status_code==200,created.text
    gid=created.json()['id']
    topo=staff.get('/api/clinics/1/topology').json()
    assert topo['groups'][0]['device_ids']==[1]
    assert staff.put(path+f'/{gid}',json=payload|{'device_ids':[999999]}).status_code==422
    assert staff.put(path+f'/{gid}',json=payload|{'name':'  '}).status_code==422
    assert staff.put('/api/clinics/3/topology/groups/0',json=payload).status_code in (403,404)
    with database.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM topology_audit WHERE changes LIKE '%groups%'").fetchone()[0]>0
    switch(staff,'sales')
    assert staff.put(path+f'/{gid}',json=payload).status_code==403
    switch(staff,'it')
    assert staff.delete(path+f'/{gid}').status_code==200
    assert staff.get('/api/devices/1').status_code==200
    assert staff.get('/api/clinics/1/topology').json()['groups']==[]


def test_topology_subnet_membership_ipv4_ipv6(environment):
    _,staff,_=environment
    switch(staff,'it')
    network={'interfaces':[{'name':'LAN','addresses':[{'address':'10.20.1.3','prefix_length':24},{'address':'2001:db8:20::1','prefix_length':64}]}]}
    assert staff.put('/api/devices/1/network',json=network).status_code==200
    nodes=staff.get('/api/clinics/1/topology').json()['nodes']
    assert nodes[0]['subnets']==['10.20.1.0/24','2001:db8:20::/64']


def test_ipv6_documentation_flag_is_explicit_and_preserved(environment):
    _,staff,_=environment
    switch(staff,'it')
    assert staff.put('/api/devices/1/network',json={'ipv6_enabled':True,'interfaces':[]}).status_code==200
    assert staff.get('/api/devices/1/network').json()['ipv6_enabled'] is True
    assert any(i['code']=='ipv6' for i in staff.get('/api/clinics/1/topology').json()['documentation'])
    assert staff.put('/api/devices/1/network',json={'interfaces':[{'name':'LAN','addresses':[{'address':'2001:db8::1'}]}]}).status_code==200
    assert staff.get('/api/devices/1/network').json()['ipv6_enabled'] is True
    assert not any(i['code']=='ipv6' for i in staff.get('/api/clinics/1/topology').json()['documentation'])


def test_login_and_setup(environment):
    admin,staff,areas=environment
    with TestClient(app) as anonymous:
        assert anonymous.get('/api/clinics').status_code==401
        assert anonymous.get('/api/search?q=secret').status_code==401
        assert anonymous.post('/api/auth/setup',json={'username':'other','password':PASSWORD}).status_code==409
    assert admin.get('/api/clinics').status_code==403
    assert staff.get('/api/admin/users').status_code==403
    assert staff.post('/api/auth/workspace',json={'role':'admin'}).status_code==403
    assert staff.post('/api/auth/workspace',json={'role':'sales','area_id':areas['Calgary']}).status_code==403


def test_client_scope_lists_search_and_direct_ids(environment):
    _,staff,_=environment
    switch(staff,'client_success')
    result=staff.get('/api/clinics')
    assert result.status_code==200,result.text
    assert [c['name'] for c in result.json()]==['Local client']
    for cid in [2,3]:
        assert staff.get(f'/api/clinics/{cid}').status_code==404
    assert 'Remote secret' not in staff.get('/api/search?q=secret').text
    assert 'TECH-SECRET' not in staff.get('/api/clinics/1').text
    assert staff.get('/api/meta').json()['map_default']['lat']==49.69
    assert staff.get('/api/clinics/1/topology').status_code==403


def test_role_switch_and_note_scope(environment):
    _,staff,_=environment
    switch(staff,'it')
    r=staff.get('/api/clinics/1/topology')
    assert r.status_code==200,r.text
    assert 'TECH-SECRET' in staff.get('/api/clinics/1/notes').text
    assert staff.post('/api/clinics',json={'name':'Forbidden'}).status_code==403
    switch(staff,'sales')
    assert staff.get('/api/clinics/1/topology').status_code==403
    assert 'TECH-SECRET' not in staff.get('/api/clinics/1/notes').text
    assert staff.delete('/api/clinics/1/notes/1').status_code==403
    assert staff.post('/api/clinics/1/notes',json={'body':'bad','visibility':'technical'}).status_code==403
    r=staff.get('/api/clinics/1/quote-defaults')
    assert r.status_code==200,r.text
    assert 'SECRET-SERIAL' not in r.text


def test_sales_create_scope_and_cross_area_writes(environment):
    _,staff,areas=environment
    switch(staff,'sales')
    r=staff.post('/api/clinics',json={'name':'New lead','area_id':areas['Calgary']})
    assert r.status_code==201,r.text
    assert r.json()['area_id']==areas['Lethbridge']
    r=staff.post('/api/tasks',json={'title':'Cross area','clinic_id':3})
    assert r.status_code in (403,404,422)
    assert staff.delete('/api/clinics/3').status_code==404
    r=staff.post('/api/clinics/1/notes',json={'body':'Shared note','author':'Spoof'})
    assert r.status_code==201,r.text
    assert r.json()['author']=='Staff'


def test_scoped_aggregates_and_exports(environment):
    _,staff,_=environment
    switch(staff,'sales')
    for endpoint in ['/api/dashboard','/api/revenue','/api/contacts','/api/tasks','/api/appointments','/api/invoices','/api/orders','/api/export/clinics.csv','/api/export/contacts.csv']:
        r=staff.get(endpoint)
        assert r.status_code==200,(endpoint,r.text)
        assert 'Remote secret' not in r.text
    assert staff.get('/api/export/backup.json').status_code==403


def test_deactivation_and_last_admin(environment):
    admin,staff,_=environment
    u=next(u for u in admin.get('/api/admin/users').json() if u['username']=='staff')
    u['is_active']=False
    assert admin.put(f"/api/admin/users/{u['id']}",json=u).status_code==200
    assert staff.get('/api/clinics').status_code==401
    a=next(u for u in admin.get('/api/admin/users').json() if u['username']=='admin')
    a['is_active']=False
    assert admin.put(f"/api/admin/users/{a['id']}",json=a).status_code==422


def test_password_change_and_csrf(environment):
    admin,staff,_=environment
    assert staff.post('/api/auth/workspace',json={'role':'it'},headers={'Origin':'https://evil.example'}).status_code==403
    r=staff.post('/api/auth/password',json={'current_password':PASSWORD,'password':'a new sufficiently long password'})
    assert r.status_code==200,r.text
    staff.post('/api/auth/logout',json={})
    assert staff.get('/api/clinics').status_code==401


def test_real_technical_and_business_workflows(environment):
    _,staff,_=environment
    switch(staff,'it')
    r=staff.post('/api/clinics/1/devices',json={'device_type':'server','name':'Test server'})
    assert r.status_code==201,r.text
    did=r.json()['id']
    r=staff.post(f'/api/devices/{did}/services',json={'name':'Test service','notes':'TECHNICAL-SERVICE'})
    assert r.status_code==201,r.text
    for path in ['/api/clinics/1/devices','/api/clinics/1/sites','/api/clinics/1/topology','/api/clinics/1/racks']:
        r=staff.get(path)
        assert r.status_code==200,(path,r.text)
    switch(staff,'sales')
    profile=staff.get('/api/clinics/1')
    assert profile.status_code==200,profile.text
    assert profile.json()['equipment']['total']==2
    assert 'TECHNICAL-SERVICE' not in profile.text
    r=staff.post('/api/clinics/1/quotes',json={'title':'Proposal','lines':[]})
    assert r.status_code==201,r.text
    qid=r.json()['id']
    switch(staff,'client_success')
    assert staff.get(f'/api/quotes/{qid}').status_code==200
    assert staff.delete(f'/api/quotes/{qid}').status_code==403
    r=staff.post('/api/clinics/1/invoices',json={'title':'Client invoice','lines':[{'description':'Support','quantity':1,'unit_price':100}]})
    assert r.status_code==201,r.text
    switch(staff,'it')
    assert staff.get('/api/invoices').status_code==403
    assert staff.get(f'/api/quotes/{qid}').status_code==200
    assert staff.post('/api/clinics/1/quotes',json={'title':'Denied'}).status_code==403


def test_area_defaults_and_manager_transfer(environment):
    admin,staff,areas=environment
    u=next(u for u in admin.get('/api/admin/users').json() if u['username']=='staff')
    for a in u['assignments']:
        if a['role']=='manager':
            a['area_ids']=list(areas.values())
            a['default_area_id']=areas['Calgary']
    assert admin.put(f"/api/admin/users/{u['id']}",json=u).status_code==200
    staff.post('/api/auth/login',json={'username':'staff','password':PASSWORD})
    switch(staff,'manager')
    assert staff.get('/api/meta').json()['map_default']['lat']==51.04
    assert staff.get('/api/clinics/1').status_code==404
    r=staff.patch('/api/clinics/3/area',json={'area_id':areas['Lethbridge']})
    assert r.status_code==200,r.text
    assert staff.get('/api/clinics/3').status_code==404
    assert staff.post('/api/auth/workspace',json={'role':'manager','area_id':areas['Lethbridge']}).status_code==200
    assert staff.get('/api/clinics/3').status_code==200
    switch(staff,'it')
    assert staff.get('/api/meta').json()['map_default']['lat']==49.69
    assert staff.patch('/api/clinics/3/area',json={'area_id':areas['Calgary']}).status_code==403


def test_unlinked_records_owned_by_area(environment):
    _,staff,areas=environment
    switch(staff,'sales')
    for path,data in [('/api/tasks',{'title':'Area-only task'}),('/api/contacts',{'first_name':'Area-only contact'}),('/api/orders',{'name':'Area-only order','quantity':1})]:
        r=staff.post(path,json=data)
        assert r.status_code==201,(path,r.text)
        assert r.json()['area_id']==areas['Lethbridge']
    with database.get_db() as conn:
        conn.execute('INSERT INTO tasks(title,area_id) VALUES (?,?)',('Remote task',areas['Calgary']))
    assert 'Remote task' not in staff.get('/api/tasks').text


def test_attachments_follow_note_scope(environment,tmp_path,monkeypatch):
    from app.routers import extras
    monkeypatch.setattr(extras,'ATTACHMENTS_DIR',str(tmp_path/'uploads'))
    _,staff,_=environment
    switch(staff,'it')
    r=staff.post('/api/clinics/1/attachments',files={'file':('tech.txt',b'TECH-FILE','text/plain')},data={'note_id':'1'})
    assert r.status_code==201,r.text
    aid=r.json()['id']
    assert staff.get(f'/api/attachments/{aid}/file').status_code==200
    switch(staff,'sales')
    assert staff.get(f'/api/attachments/{aid}/file').status_code==404
    assert staff.delete(f'/api/attachments/{aid}').status_code==404
    assert 'tech.txt' not in staff.get('/api/clinics/1').text


def test_admin_validation_reset_and_inactive_area(environment):
    admin,staff,areas=environment
    assert admin.post('/api/admin/areas',json={'name':'Lethbridge','latitude':0,'longitude':0}).status_code==409
    u=next(u for u in admin.get('/api/admin/users').json() if u['username']=='staff')
    assert admin.post('/api/admin/users',json={**u,'password':PASSWORD}).status_code==409
    u['password']='temporary reset password'
    u['must_change_password']=True
    assert admin.put(f"/api/admin/users/{u['id']}",json=u).status_code==200
    assert staff.get('/api/clinics').status_code==401
    assert staff.post('/api/auth/login',json={'username':'staff','password':u['password']}).status_code==200
    assert staff.get('/api/clinics').status_code==403
    assert staff.post('/api/auth/workspace',json={'role':'it'}).status_code==403
    assert staff.post('/api/auth/password',json={'current_password':u['password'],'password':PASSWORD}).status_code==200
    switch(staff,'sales')
    a=next(a for a in admin.get('/api/admin/areas').json() if a['id']==areas['Lethbridge'])
    a['is_active']=False
    assert admin.put(f"/api/admin/areas/{a['id']}",json=a).status_code==200
    assert staff.get('/api/clinics').status_code==403


def test_login_throttling_and_cookie(environment):
    _,staff,_=environment
    for _ in range(10):
        assert staff.post('/api/auth/login',json={'username':' Staff ','password':'wrong'}).status_code==401
    assert staff.post('/api/auth/login',json={'username':'staff','password':'wrong'}).status_code==429
    with TestClient(app,base_url='https://example.test') as secure:
        r=secure.post('/api/auth/login',json={'username':'admin','password':PASSWORD})
        assert r.status_code==200
        cookie=r.headers['set-cookie'].lower()
        assert all(v in cookie for v in ['httponly','secure','samesite=strict'])


@pytest.mark.parametrize('origin,target,allowed', [
    ('https://areabook.kadenbirch.com','http://areabook.kadenbirch.com/',True),
    ('https://areabook.kadenbirch.com:443','http://areabook.kadenbirch.com/',True),
    ('https://areabook.kadenbirch.com','https://areabook.kadenbirch.com/',True),
    ('http://localhost:8080','http://localhost:8080/',True),
    ('https://example.test:8443','http://example.test:8443/',True),
    ('https://evil.example','http://areabook.kadenbirch.com/',False),
    ('https://areabook.kadenbirch.com.evil.example','http://areabook.kadenbirch.com/',False),
    ('https://areabook.kadenbirch.com:8443','http://areabook.kadenbirch.com/',False),
    ('http://areabook.kadenbirch.com','https://areabook.kadenbirch.com/',False),
    ('null','http://areabook.kadenbirch.com/',False),
    ('','http://areabook.kadenbirch.com/',False),
    ('https://user@areabook.kadenbirch.com','http://areabook.kadenbirch.com/',False),
    ('https://areabook.kadenbirch.com/path','http://areabook.kadenbirch.com/',False),
    ('https://areabook.kadenbirch.com:invalid','http://areabook.kadenbirch.com/',False),
])
def test_proxy_origin_validation(origin,target,allowed):
    from app.main import allowed_write_origin
    assert allowed_write_origin(origin,target) is allowed


def test_first_run_behind_tls_proxy(tmp_path,monkeypatch):
    monkeypatch.setattr(database,'DATABASE_PATH',str(tmp_path/'proxy.db'))
    # NPM connects over HTTP, preserving the public Host and browser Origin.
    with TestClient(app,base_url='http://areabook.kadenbirch.com') as proxy:
        headers={'Origin':'https://areabook.kadenbirch.com'}
        r=proxy.post('/api/auth/setup',headers=headers,json={'username':'admin','password':PASSWORD})
        assert r.status_code==200,r.text
        assert 'Secure' in r.headers['set-cookie']
        # Emulate the browser sending its Secure cookie over HTTPS to NPM,
        # which forwards it to the HTTP upstream unchanged.
        headers['Cookie']='areabook_session='+proxy.cookies.get('areabook_session')
        assert proxy.get('/api/auth/me',headers=headers).status_code==200
        r=proxy.post('/api/admin/areas',headers=headers,json={'name':'Lethbridge','latitude':49.69,'longitude':-112.83})
        assert r.status_code==200,r.text
        assert proxy.post('/api/auth/logout',headers=headers).status_code==200
        assert proxy.get('/api/auth/me',headers=headers).status_code==401
        r=proxy.post('/api/auth/login',headers={'Origin':headers['Origin']},json={'username':'admin','password':PASSWORD})
        assert r.status_code==200,r.text
        assert 'Secure' in r.headers['set-cookie']
        # Spoofed forwarded metadata must not authorize an unrelated website.
        assert proxy.post('/api/auth/login',headers={'Origin':'https://evil.example','X-Forwarded-Host':'evil.example','X-Forwarded-Proto':'https'},json={'username':'admin','password':PASSWORD}).status_code==403


def test_it_dashboard_scope_and_attention(environment):
    from datetime import date, timedelta
    _,staff,areas=environment
    today=date.today()
    yesterday=(today-timedelta(days=1)).isoformat()
    with database.get_db() as conn:
        for cid,name in [(1,'Local server'),(2,'Prospect server'),(3,'Remote server')]:
            did=conn.execute("INSERT INTO devices(clinic_id,device_type,name) VALUES (?,'server',?)",(cid,name)).lastrowid
            conn.execute('INSERT INTO device_services(device_id,name) VALUES (?,?)',(did,name+' service'))
            conn.execute("INSERT INTO tasks(clinic_id,title,due_date,visibility) VALUES (?,?,?,'technical')",(cid,name+' task',yesterday))
            conn.execute("INSERT INTO appointments(clinic_id,title,start_time) VALUES (?,?,?)",(cid,name+' visit',today.isoformat()+'T12:00:00'))
        conn.execute("INSERT INTO tasks(clinic_id,title,due_date,visibility) VALUES (1,'Hidden sales task',?,'sales')",(yesterday,))
        conn.execute("INSERT INTO tasks(clinic_id,title,due_date,done) VALUES (1,'Done task',?,1)",(yesterday,))
        conn.execute("INSERT INTO tasks(area_id,title,due_date) VALUES (?,'Unlinked local task',?)",(areas['Lethbridge'],today.isoformat()))
        conn.execute("INSERT INTO clinics(name,area_id,relationship) VALUES ('Missing equipment',?,'current_client')",(areas['Lethbridge'],))
        conn.execute("INSERT INTO vpn_links(name,status,a_clinic_id,b_clinic_id) VALUES ('Cross Area VPN','down',1,3)")
        conn.execute("INSERT INTO vpn_links(name,status,a_clinic_id,b_clinic_id) VALUES ('Local VPN','down',1,2)")
    switch(staff,'it')
    r=staff.get('/api/it/dashboard')
    assert r.status_code==200,r.text
    d=r.json()
    assert d['summary']=={'current_clients':2,'devices':2,'servers':1,'overdue_tasks':1,'open_tasks':2,'services':1}
    assert {c['name'] for c in d['clinics']}=={'Local client','Missing equipment'}
    assert {a['kind'] for a in d['attention']}=={'task','vpn','documentation','service'}
    device_alerts=[a for a in d['attention'] if a.get('device_id')]
    assert {a['title'] for a in device_alerts}=={'Secret device','Local server'}
    assert all(a['clinic_id']==1 for a in device_alerts)
    assert len(d['upcoming'])==2
    assert all(secret not in r.text for secret in ['Remote','Cross Area VPN','Prospect server','Hidden sales task','Done task'])
    all_data=staff.get('/api/it/dashboard?include_prospects=true').json()
    assert all_data['summary']['devices']==3
    assert all_data['summary']['overdue_tasks']==2
    assert len(all_data['clinics'])==3
    for role in ['sales','manager','client_success']:
        switch(staff,role)
        assert staff.get('/api/it/dashboard').status_code==403


def test_it_dashboard_empty_area(environment):
    _,staff,_=environment
    switch(staff,'it')
    with database.get_db() as conn:
        conn.execute('UPDATE clinics SET area_id=NULL')
    d=staff.get('/api/it/dashboard').json()
    assert all(v==0 for v in d['summary'].values())
    assert d['clinics']==d['attention']==d['upcoming']==[]


def test_structured_service_fields_tickets_and_permissions(environment):
    _,staff,_=environment
    switch(staff,'it')
    service_ids=[]
    for kind in ('server','vm'):
        d=staff.post('/api/clinics/1/devices',json={'device_type':kind,'name':kind+' host'}).json()
        payload={'name':'Database','protocols':'TCP, HTTPS','ports':'443, 1433','vendor_or_service_url':'https://vendor.example',
                 'internal_url':'https://db.local','public_url':'https://db.example','support_email':'support@example.com'}
        r=staff.post(f"/api/devices/{d['id']}/services",json=payload)
        assert r.status_code==201,r.text
        s=r.json();service_ids.append(s['id'])
        assert all(s[k]==v for k,v in payload.items())
        r=staff.post(f"/api/services/{s['id']}/tickets",json={'title':'Database case','url':'https://support.example/123','notes':'Intermittent failures'})
        assert r.status_code==201,r.text
        tid=r.json()['id']
        detail=staff.get(f"/api/services/{s['id']}").json()
        assert detail['tickets'][0]['id']==tid
        assert staff.post(f"/api/services/{s['id']}/tickets",json={'title':'Unsafe','url':'javascript:alert(1)'}).status_code==422
        payload['protocols']='TCP'
        assert staff.put(f"/api/services/{s['id']}",json=payload).json()['protocols']=='TCP'
        assert staff.delete(f"/api/services/{s['id']}/tickets/{tid}").status_code==204
        assert staff.get(f"/api/services/{s['id']}").json()['tickets']==[]
    with database.get_db() as conn:
        did=conn.execute("INSERT INTO devices(clinic_id,device_type,name) VALUES (3,'server','Remote')").lastrowid
        sid=conn.execute("INSERT INTO device_services(device_id,name) VALUES (?,'Remote service')",(did,)).lastrowid
    assert staff.get(f'/api/services/{sid}').status_code==404
    assert staff.post(f'/api/services/{sid}/tickets',json={'title':'Denied'}).status_code==404
    switch(staff,'sales')
    assert staff.get(f'/api/services/{service_ids[0]}').status_code==403
    assert staff.post(f'/api/services/{service_ids[0]}/tickets',json={'title':'Denied'}).status_code==403


def test_service_text_migration_preserves_and_deduplicates(tmp_path,monkeypatch):
    monkeypatch.setattr(database,'DATABASE_PATH',str(tmp_path/'legacy-services.db'))
    database.init_db()
    values=['DNS\nFile shares\nDNS','["Backup","Monitoring"]','[broken json','{"unexpected":"data"}','"SQL\\nWeb"']
    with database.get_db() as conn:
        conn.execute("INSERT INTO clinics(id,name) VALUES (1,'Legacy')")
        for i,value in enumerate(values,1):
            conn.execute("INSERT INTO devices(id,clinic_id,device_type,name,services) VALUES (?,1,'server',?,?)",(i,str(i),value))
    database.init_db()
    database.init_db()
    with database.get_db() as conn:
        names=[r[0] for r in conn.execute('SELECT name FROM device_services ORDER BY id')]
        assert names==['DNS','File shares','Backup','Monitoring','SQL','Web']
        assert conn.execute('SELECT services FROM devices WHERE id=3').fetchone()[0]=='[broken json'
        assert conn.execute('SELECT services FROM devices WHERE id=4').fetchone()[0]=='{"unexpected":"data"}'
        assert conn.execute('SELECT services FROM devices WHERE id=1').fetchone()[0] is None


def test_device_edit_preserves_unconverted_services(environment):
    _,staff,_=environment
    switch(staff,'it')
    with database.get_db() as conn:
        did=conn.execute("INSERT INTO devices(clinic_id,device_type,name,services) VALUES (1,'server','Legacy','[broken json')").lastrowid
    result=staff.put(f'/api/devices/{did}',json={'device_type':'server','name':'Renamed'})
    assert result.status_code==200,result.text
    assert result.json()['legacy_services']=='[broken json'
    with database.get_db() as conn:
        assert conn.execute('SELECT services FROM devices WHERE id=?',(did,)).fetchone()[0]=='[broken json'


def test_connection_details_validation_cleanup_and_views(environment):
    _,staff,_=environment
    switch(staff,'it')
    parent=staff.post('/api/clinics/1/devices',json={'device_type':'switch','name':'Core','rack':'A'}).json()['id']
    child=staff.post('/api/clinics/1/devices',json={'device_type':'server','name':'Host','uplink_id':parent}).json()['id']
    vm=staff.post('/api/clinics/1/devices',json={'device_type':'vm','name':'Guest','uplink_id':child}).json()['id']
    vlan=staff.post('/api/clinics/1/vlans',json={'tag':20,'name':'Production'}).json()['id']
    interfaces=[]
    for did in [parent,child]:
        r=staff.put(f'/api/devices/{did}/network',json={'interfaces':[{'name':'LAN','memberships':[{'vlan_id':vlan,'mode':'tagged'}]}]})
        assert r.status_code==200,r.text
        interfaces.append(r.json()['interfaces'][0]['id'])
    url=f'/api/clinics/1/connections/{parent}/{child}'
    payload=dict(source_interface_id=interfaces[0],target_interface_id=interfaces[1],speed_mbps=1000,vlan_mode='trunk',tagged_vlans=[vlan])
    r=staff.put(url,json=payload)
    assert r.status_code==200,r.text
    assert r.json()['details']['tagged_vlans']==[vlan]
    assert staff.put(url,json=payload|{'target_interface_id':interfaces[0]}).status_code==422
    assert staff.put(url,json=payload|{'vlan_mode':'access'}).status_code==422
    assert staff.put(url,json=payload|{'native_vlan_id':vlan}).status_code==422
    assert staff.put(f'/api/clinics/1/connections/{parent}/{vm}',json={}).status_code==404
    assert staff.put(f'/api/devices/{parent}/network',json={'interfaces':[]}).status_code==409
    assert staff.delete(f'/api/clinics/1/vlans/{vlan}').status_code==409
    topo=staff.get('/api/clinics/1/topology').json()
    assert vm in [n['id'] for n in topo['nodes']]
    assert vm not in [n['id'] for n in topo['physical_nodes']]
    assert next(n for n in topo['physical_nodes'] if n['id']==parent)['rack']=='A'
    assert not any(i['code']=='trunk_membership' for i in topo['documentation'])
    assert staff.put(f'/api/devices/{child}',json={'device_type':'server','name':'Host','uplink_id':None}).status_code==200
    assert staff.get(url).status_code==404
    with database.get_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM connection_details').fetchone()[0]==0
        assert conn.execute('SELECT COUNT(*) FROM connection_vlans').fetchone()[0]==0


def test_connection_scope_and_cross_site_vlan(environment):
    _,staff,_=environment
    switch(staff,'it')
    with database.get_db() as conn:
        remote=conn.execute("INSERT INTO devices(clinic_id,device_type,name) VALUES (3,'switch','Remote')").lastrowid
        loc=conn.execute("INSERT INTO clinic_locations(clinic_id,name) VALUES (1,'Branch')").lastrowid
    parent=staff.post('/api/clinics/1/devices',json={'device_type':'switch','name':'Core'}).json()['id']
    child=staff.post('/api/clinics/1/devices',json={'device_type':'switch','name':'Branch','location_id':loc,'uplink_id':parent}).json()['id']
    vlan=staff.post('/api/clinics/1/vlans',json={'tag':20,'name':'Main'}).json()['id']
    url=f'/api/clinics/1/connections/{parent}/{child}'
    assert staff.put(url,json={'vlan_mode':'access','native_vlan_id':vlan}).status_code==422
    assert staff.get(f'/api/clinics/3/connections/{remote}/{parent}').status_code==404
    assert staff.put(url,json={'notes':'Documentation only'}).status_code==200
    switch(staff,'sales')
    assert staff.get(url).status_code==403
    assert staff.put(url,json={}).status_code==403


def test_topology_import_preview_commit_and_stale_detection(environment):
    _,staff,_=environment
    switch(staff,'it')
    base='/api/clinics/1/topology'
    payload={'kind':'devices','site':'main','csv_text':'name,device_type,ip_address,uplink_name\nImported host,server,2001:db8::10,Imported switch\nImported switch,switch,192.0.2.1,\n'}
    preview=staff.post(base+'/import/preview',json=payload)
    assert preview.status_code==200,preview.text
    assert len(preview.json()['rows'])==2
    assert len(staff.get('/api/clinics/1/devices').json()['devices'])==1
    assert staff.get(base+'/audit').json()['items']==[]
    response=staff.post(base+'/import/commit',json=payload|{'preview_token':preview.json()['preview_token']})
    assert response.status_code==201,response.text
    data=staff.get('/api/clinics/1/devices').json()['devices']
    host=next(d for d in data if d['name']=='Imported host')
    switch_device=next(d for d in data if d['name']=='Imported switch')
    assert host['uplink_id']==switch_device['id']
    assert staff.get(f"/api/devices/{host['id']}/network").json()['interfaces'][0]['addresses'][0]['version']==6
    audit=staff.get(base+'/audit').json()['items']
    assert len(audit)==1 and 'staff #' in audit[0]['actor']
    assert any(c['table']=='devices' and c['action']=='added' for c in audit[0]['changes'])
    assert staff.post(base+'/import/commit',json=payload|{'preview_token':preview.json()['preview_token']}).status_code==409
    assert staff.post(base+'/import/preview',json=payload).status_code==422
    another=payload|{'csv_text':'name,device_type\nAnother,switch\n'}
    token=staff.post(base+'/import/preview',json=another).json()['preview_token']
    staff.put('/api/devices/1',json={'device_type':'workstation','name':'Changed since preview'})
    assert staff.post(base+'/import/commit',json=another|{'preview_token':token}).status_code==409


def test_topology_import_validation_atomicity_and_network_rows(environment):
    _,staff,_=environment
    switch(staff,'it')
    base='/api/clinics/1/topology'
    def preview(kind,text):return staff.post(base+'/import/preview',json={'kind':kind,'csv_text':text})
    for text in ['name,device_type\nFirst,switch\nBad,invalid\n',
                 'name,device_type,ip_address\nBad,switch,999.999.1.1\n',
                 'name,device_type,uplink_name\nA,switch,B\nB,switch,A\n',
                 'name,name\nA,B\n']:
        assert preview('devices',text).status_code==422
    assert len(staff.get('/api/clinics/1/devices').json()['devices'])==1
    vlan={'kind':'vlans','csv_text':'tag,name,subnets\n30,Imported VLAN,192.0.2.0/24;2001:db8::/64\n'}
    p=staff.post(base+'/import/preview',json=vlan)
    assert p.status_code==200,p.text
    assert staff.get('/api/clinics/1/vlans').json()['vlans']==[]
    assert staff.post(base+'/import/commit',json=vlan|{'preview_token':p.json()['preview_token']}).status_code==201
    interface={'kind':'interfaces','csv_text':'device_name,interface_name,address,prefix_length,vlan_tag,mode\nSecret device,LAN,192.0.2.10,24,30,access\nSecret device,LAN,2001:db8::10,64,30,access\n'}
    p=staff.post(base+'/import/preview',json=interface)
    assert p.status_code==200,p.text
    r=staff.post(base+'/import/commit',json=interface|{'preview_token':p.json()['preview_token']})
    assert r.status_code==201,r.text
    saved=staff.get('/api/devices/1/network').json()
    assert len(next(i for i in saved['interfaces'] if i['name']=='LAN')['addresses'])==2
    assert next(i for i in saved['interfaces'] if i['name']=='Primary')['addresses'][0]['address']=='10.0.0.1'
    assert staff.post(base+'/import/preview',json=interface).status_code==422
    assert staff.get('/api/devices/1/network').json()==saved


def test_topology_versions_audit_comparison_and_scope(environment):
    _,staff,_=environment
    switch(staff,'it')
    base='/api/clinics/1/topology'
    version=staff.post(base+'/versions',json={'label':'Before','site':'main'})
    assert version.status_code==201,version.text
    vid=version.json()['id']
    assert staff.get(base+'/audit').json()['items']==[]
    staff.put('/api/devices/1',json={'device_type':'workstation','name':'Renamed device'})
    changes=staff.get(base+f'/versions/{vid}/compare?site=main').json()['changes']
    assert next(c for c in changes if c['table']=='devices')['fields']['name']=={'before':'Secret device','after':'Renamed device'}
    original=staff.get(base+f'/versions/{vid}?site=main').json()
    assert original['document']['devices'][0]['name']=='Secret device'
    assert staff.get(base+f'/versions/{vid}?site=all').status_code==404
    assert staff.get('/api/clinics/3/topology/versions').status_code==404
    assert staff.get('/api/clinics/3/topology/audit').status_code==404
    assert staff.post('/api/clinics/3/topology/import/preview',json={'kind':'devices','csv_text':'name,device_type\nForbidden,switch\n'}).status_code==404
    assert staff.post(base+'/import/preview',json={'site':'all','kind':'devices','csv_text':'name,device_type\nForbidden,switch\n'}).status_code==422
    audit=staff.get(base+'/audit?limit=1').json()
    assert len(audit['items'])==1 and audit['next_before']
    assert staff.get(base+'/audit?before='+str(audit['next_before'])).json()['items']==[]
    switch(staff,'sales')
    for path in ['/versions','/audit',f'/versions/{vid}?site=main']:
        assert staff.get(base+path).status_code==403
    assert staff.post(base+'/import/preview',json={'kind':'devices','csv_text':'name,device_type\nForbidden,switch\n'}).status_code==403


def test_topology_history_rechecks_remote_vpn_area_scope(environment):
    _,staff,areas=environment
    switch(staff,'it')
    response=staff.post('/api/clinics/1/vpn/links',json={'remote_kind':'site','b_clinic_id':2,'notes':'Remote historical details'})
    assert response.status_code==201,response.text
    vid=staff.post('/api/clinics/1/topology/versions',json={'label':'VPN baseline'}).json()['id']
    assert staff.get(f'/api/clinics/1/topology/versions/{vid}').status_code==200
    assert staff.get('/api/clinics/1/topology/audit').json()['items']
    with database.get_db() as conn:
        conn.execute('UPDATE clinics SET area_id=? WHERE id=2',(areas['Calgary'],))
    assert staff.get(f'/api/clinics/1/topology/versions/{vid}').status_code==404
    assert staff.get(f'/api/clinics/1/topology/versions/{vid}/compare').status_code==404
    assert staff.get('/api/clinics/1/topology/versions').json()==[]
    assert staff.get('/api/clinics/1/topology/audit').json()['items']==[]


def test_ip_review_scope_and_ipv6(environment):
    _,staff,_=environment
    switch(staff,'it')
    params={'source_ip':'2001:db8:1::1','destination_ip':'2001:db8:1::2'}
    staff.post('/api/clinics/1/vlans',json={'tag':11,'name':'IPv6','subnets':['2001:db8:1::/64']})
    r=staff.get('/api/clinics/1/connectivity/ip-review',params=params)
    assert r.status_code==200,r.text
    assert r.json()['candidates'][0]['kind']=='local'
    assert r.json()['source_matches']
    assert staff.get('/api/clinics/3/connectivity/ip-review',params=params).status_code==404
    switch(staff,'sales')
    assert staff.get('/api/clinics/1/connectivity/ip-review',params=params).status_code==403


def test_interfaces_dual_stack_vlans_and_primary_compatibility(environment):
    _,staff,_=environment
    switch(staff,'it')
    d=staff.post('/api/clinics/1/devices',json={'device_type':'server','name':'Dual stack'}).json()
    r=staff.post('/api/clinics/1/vlans',json={'tag':20,'name':'Production','subnets':['10.20.0.10/24','2001:db8:20::/64']})
    assert r.status_code==201,r.text
    vlan=r.json()
    assert vlan['subnets']==['10.20.0.0/24','2001:db8:20::/64']
    payload={'interfaces':[{'name':'eth0','mac_address':'aabbccddeeff','memberships':[{'vlan_id':vlan['id'],'mode':'access'}],
        'addresses':[{'address':'10.20.0.10/24','vlan_id':vlan['id'],'is_primary':True}, {'address':'2001:0db8:20::10','prefix_length':64,'vlan_id':vlan['id']}]}]}
    r=staff.put(f"/api/devices/{d['id']}/network",json=payload)
    assert r.status_code==200,r.text
    saved=r.json();i=saved['interfaces'][0]
    assert i['mac_address']=='AA:BB:CC:DD:EE:FF'
    assert [a['version'] for a in i['addresses']]==[4,6]
    assert i['addresses'][1]['address']=='2001:db8:20::10'
    assert staff.get(f"/api/devices/{d['id']}").json()['ip_address']=='10.20.0.10'
    r=staff.put(f"/api/devices/{d['id']}",json={'name':'Renamed','device_type':'server','ip_address':'wrong'})
    assert r.status_code==200,r.text
    assert r.json()['ip_address']=='10.20.0.10'
    topo=staff.get('/api/clinics/1/topology').json()
    n=next(n for n in topo['nodes'] if n['id']==d['id'])
    assert len(n['addresses'])==2
    assert n['vlan_memberships'][0]['mode']=='access'
    assert staff.put(f"/api/devices/{d['id']}/network",json=saved).status_code==200
    assert staff.delete(f"/api/clinics/1/vlans/{vlan['id']}").status_code==409
    saved['interfaces'][0]['addresses'][1]['is_primary']=True
    assert staff.put(f"/api/devices/{d['id']}/network",json=saved).status_code==422
    assert len(staff.get(f"/api/devices/{d['id']}/network").json()['interfaces'][0]['addresses'])==2


def test_network_validation_gateway_and_site_boundaries(environment):
    _,staff,_=environment
    switch(staff,'it')
    with database.get_db() as conn:
        loc=conn.execute("INSERT INTO clinic_locations(clinic_id,name) VALUES (1,'Branch')").lastrowid
    v=staff.post('/api/clinics/1/vlans',json={'tag':10,'name':'Main'}).json()
    assert staff.post('/api/clinics/1/vlans',json={'tag':10,'name':'Duplicate'}).status_code==409
    branch=staff.post('/api/clinics/1/vlans',json={'tag':10,'name':'Branch','location_id':loc})
    assert branch.status_code==201,branch.text
    for bad in [{'tag':4095,'name':'Bad'},{'tag':5,'name':'Bad','color':'red;script'},{'tag':5,'name':'Bad','subnets':['wrong']}]:
        assert staff.post('/api/clinics/1/vlans',json=bad).status_code==422
    base={'interfaces':[{'name':'LAN','addresses':[{'address':'2001:db8::5','prefix_length':64}]}]}
    r=staff.put('/api/devices/1/network',json=base)
    assert r.status_code==200,r.text
    saved=r.json();iid=saved['interfaces'][0]['id']
    assert staff.put(f"/api/clinics/1/vlans/{v['id']}",json={'tag':10,'name':'Main','gateway_interface_id':iid}).status_code==200
    assert staff.put('/api/devices/1/network',json={'interfaces':[]}).status_code==409
    assert staff.put('/api/devices/1',json={'device_type':'workstation','location_id':loc}).status_code==409
    saved['interfaces'][0]['memberships']=[{'vlan_id':branch.json()['id'],'mode':'access'}]
    assert staff.put('/api/devices/1/network',json=saved).status_code==422
    for bad in ['300.1.1.1','2001:db8::xyz','fe80::1%eth0','10.0.0.1/33']:
        assert staff.put('/api/devices/1/network',json={'interfaces':[{'name':'LAN','addresses':[{'address':bad}]}]}).status_code==422
    assert staff.get('/api/devices/1/network').json()['interfaces'][0]['id']==iid


def test_network_roles_and_remote_records(environment):
    _,staff,_=environment
    switch(staff,'it')
    with database.get_db() as conn:
        did=conn.execute("INSERT INTO devices(clinic_id,device_type,name) VALUES (3,'router','Remote')").lastrowid
        iid=conn.execute("INSERT INTO network_interfaces(device_id,name) VALUES (?,'secret')",(did,)).lastrowid
        vid=conn.execute("INSERT INTO vlans(clinic_id,tag,name) VALUES (3,10,'Remote VLAN')").lastrowid
    assert staff.get(f'/api/devices/{did}/network').status_code==404
    assert staff.get('/api/clinics/3/vlans').status_code==404
    assert staff.post('/api/clinics/3/vlans',json={'tag':20,'name':'Denied'}).status_code==404
    assert staff.post('/api/clinics/1/vlans',json={'tag':20,'name':'Denied','gateway_interface_id':iid}).status_code==422
    assert staff.put('/api/devices/1/network',json={'interfaces':[{'name':'NIC','memberships':[{'vlan_id':vid}]}]}).status_code==422
    assert staff.put('/api/devices/1/network',json={'interfaces':[{'id':iid,'name':'Stolen'}]}).status_code==422
    switch(staff,'sales')
    assert staff.get('/api/clinics/1/vlans').status_code==403
    assert staff.get('/api/devices/1/network').status_code==403
    assert staff.put('/api/devices/1/network',json={'interfaces':[]}).status_code==403


def test_network_migration_preserves_legacy_and_is_repeatable(tmp_path,monkeypatch):
    monkeypatch.setattr(database,'DATABASE_PATH',str(tmp_path/'network-upgrade.db'))
    database.init_db()
    with database.get_db() as conn:
        conn.execute("INSERT INTO clinics(id,name) VALUES (1,'Legacy')")
        for id,ip in [(1,'10.0.0.10/24'),(2,'2001:db8::1'),(3,'DHCP - ask IT')]:
            conn.execute("INSERT INTO devices(id,clinic_id,device_type,name,ip_address) VALUES (?,1,'server',?,?)",(id,str(id),ip))
    database.init_db();database.init_db()
    with database.get_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM network_interfaces').fetchone()[0]==2
        assert conn.execute('SELECT COUNT(*) FROM network_addresses').fetchone()[0]==2
        assert conn.execute('SELECT prefix_length FROM network_addresses WHERE version=6').fetchone()[0] is None
        assert conn.execute('SELECT ip_address FROM devices WHERE id=3').fetchone()[0]=='DHCP - ask IT'
