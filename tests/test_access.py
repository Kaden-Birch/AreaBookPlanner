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
