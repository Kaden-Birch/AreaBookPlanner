"""Durable staggered refresh queue; upstream reads never perform configuration writes."""
import hashlib
import ipaddress
import json
import random
import secrets
import threading
import time
from fastapi import HTTPException
from .database import get_db
from .syncro_network import adapters, mac

SCHEMA = '''
CREATE TABLE IF NOT EXISTS integration_jobs (
 id INTEGER PRIMARY KEY, provider TEXT NOT NULL, source_key TEXT NOT NULL,
 clinic_id INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE, config TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 1, interval_minutes INTEGER NOT NULL DEFAULT 30,
 next_at REAL NOT NULL, last_attempt REAL, last_success REAL, failures INTEGER NOT NULL DEFAULT 0,
 error TEXT, warnings TEXT NOT NULL DEFAULT '[]', lease TEXT, lease_until REAL NOT NULL DEFAULT 0,
 UNIQUE(provider,source_key));
CREATE TABLE IF NOT EXISTS integration_fields (
 id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES integration_jobs(id) ON DELETE CASCADE,
 clinic_id INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
 entity TEXT NOT NULL, row_id INTEGER NOT NULL, field TEXT NOT NULL, last_value TEXT NOT NULL,
 overridden INTEGER NOT NULL DEFAULT 0, UNIQUE(entity,row_id,field));
CREATE TABLE IF NOT EXISTS integration_changes (
 id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES integration_jobs(id) ON DELETE CASCADE,
 clinic_id INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
 change_key TEXT NOT NULL, title TEXT NOT NULL, detail TEXT NOT NULL, visibility TEXT NOT NULL DEFAULT 'technical',
 status TEXT NOT NULL DEFAULT 'pending', updated_at REAL NOT NULL, UNIQUE(job_id,change_key));
'''

def setting(conn, key):
    row=conn.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
    return row[0] if row else None

def enabled(conn): return setting(conn,'integration_sync_enabled')=='1'

def discover(conn):
    sources=[]
    for r in conn.execute('SELECT * FROM syncro_links'):
        sources.append(('syncro',f"{r['tenant']}:{r['customer_id']}",r['clinic_id'],dict(r)))
    for r in conn.execute('SELECT * FROM unifi_sites'):
        sources.append(('unifi',f"{r['host_id']}/{r['site_id']}",r['clinic_id'],dict(r)))
    for index,(provider,key,cid,config) in enumerate(sources):
        conn.execute('INSERT INTO integration_jobs(provider,source_key,clinic_id,config,next_at) VALUES (?,?,?,?,?) ON CONFLICT(provider,source_key) DO UPDATE SET config=excluded.config',
                     (provider,key,cid,json.dumps(config),time.time()+index*1800/max(1,len(sources))))
    valid={(p,k) for p,k,_,_ in sources}
    for r in conn.execute('SELECT id,provider,source_key FROM integration_jobs'):
        if (r['provider'],r['source_key']) not in valid:
            conn.execute('UPDATE integration_jobs SET enabled=0,error=? WHERE id=?',('Source mapping removed; refresh paused',r['id']))

def claim(provider):
    now=time.time()
    with get_db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not enabled(c): return None
        if c.execute('SELECT id FROM integration_jobs WHERE provider=? AND lease_until>?',(provider,now)).fetchone(): return None
        r=c.execute('SELECT * FROM integration_jobs WHERE provider=? AND enabled=1 AND next_at<=? ORDER BY next_at,id LIMIT 1',(provider,now)).fetchone()
        if not r:return None
        token=secrets.token_hex(16)
        c.execute('UPDATE integration_jobs SET lease=?,lease_until=?,last_attempt=? WHERE id=?',(token,now+900,now,r['id']))
        return dict(r)|{'lease':token}

def collect(job):
    """Network I/O occurs with no application database transaction held open."""
    from .routers import syncro
    from .unifi_client import Client as UniFi
    from .unifi_mapping import device, network, text
    cfg=json.loads(job['config']); provider=job['provider']
    with get_db() as c:
        generation=hashlib.sha256((setting(c,provider+'_api_key') or '').encode()).hexdigest()
        baseline=source_baseline(c,job)
        if provider=='syncro':
            client=syncro.Client(c)
            if client.tenant!=cfg['tenant']:raise HTTPException(409,'Syncro account changed; relink this clinic')
            kinds=[r[0] for r in c.execute('SELECT DISTINCT kind FROM syncro_records WHERE clinic_id=? AND tenant=?',(job['clinic_id'],cfg['tenant']))]
        else:client=UniFi(setting(c,'unifi_api_key'));kinds=['devices','clients','networks','vpn']
    records=[]; complete=[]; warnings=[]; started=time.monotonic()
    for kind in kinds:
        try:
            if provider=='syncro':
                path='/customer_assets' if kind=='assets' else '/'+kind
                rows=client.collection(path,kind,cfg['customer_id']); batch=[]
                for raw in rows:
                    if time.monotonic()-started>240:raise HTTPException(502,'Refresh time budget exceeded; no partial inventory applied')
                    r=syncro.normalize(kind,raw,client.base)
                    if kind=='assets':
                        detail=client.get(path+'/'+str(r['id'])).get('asset')
                        if not isinstance(detail,dict) or detail.get('id')!=r['id'] or str(detail.get('customer_id'))!=str(cfg['customer_id']):raise HTTPException(502,'Syncro detail identity mismatch')
                        r=syncro.normalize(kind,{**raw,**detail},client.base)
                        r['interfaces']=adapters(detail);r['addresses']=[a for i in r['interfaces'] for a in i['addresses']]
                        r['mac_address']=next((i['mac_address'] for i in r['interfaces'] if i['mac_address']),'')
                    batch.append((kind,str(r['id']),r))
            else:
                base='/v1/sites/'+cfg['site_id']
                path='vpn/site-to-site-tunnels' if kind=='vpn' else kind
                rows=client.collection(base+'/'+path,cfg['host_id']);batch=[]
                for raw in rows:
                    overview=raw
                    if kind in ('devices','networks'):
                        raw=client.get(base+'/'+path+'/'+raw['id'],cfg['host_id'])
                        if raw.get('id')!=overview['id']:raise HTTPException(502,'UniFi detail identity mismatch')
                    if kind in ('devices','clients'):
                        if kind=='clients' and raw.get('type') not in ('WIRED','WIRELESS'):continue
                        r=device(kind,raw)
                        if kind=='devices':r['device_type']=device(kind,overview)['device_type']
                    elif kind=='networks':r=network(raw)|{'kind':kind}
                    else:r={'id':text(raw.get('id')),'kind':'vpn','name':text(raw.get('name')),'type':text(raw.get('type'))}
                    batch.append((kind,str(r['id']),r))
            records.extend(batch);complete.append(kind)
        except HTTPException as e:
            if e.status_code==429 or kind in ('assets','devices','clients'):raise
            warnings.append(kind+': '+str(e.detail))
    return {'records':records,'complete':complete,'warnings':warnings,'generation':generation,'baseline':baseline}

def source_baseline(c,job):
    cfg=json.loads(job['config'])
    if job['provider']=='syncro':
        query='SELECT id,local_id,data FROM syncro_records WHERE clinic_id=? AND tenant=? ORDER BY id'
        args=(job['clinic_id'],cfg['tenant'])
    else:
        query='SELECT id,local_id,data FROM unifi_records WHERE clinic_id=? AND host_id=? AND site_id=? ORDER BY id'
        args=(job['clinic_id'],cfg['host_id'],cfg['site_id'])
    return hashlib.sha256(json.dumps([list(r) for r in c.execute(query,args)]).encode()).hexdigest()

def notice(c,job,key,title,detail,visibility='technical'):
    encoded=json.dumps(detail,sort_keys=True)
    c.execute('''INSERT INTO integration_changes(job_id,clinic_id,change_key,title,detail,updated_at,visibility) VALUES (?,?,?,?,?,?,?)
      ON CONFLICT(job_id,change_key) DO UPDATE SET title=excluded.title,
      status=CASE WHEN integration_changes.detail=excluded.detail AND integration_changes.status!='resolved' THEN integration_changes.status ELSE 'pending' END,
      detail=excluded.detail,updated_at=excluded.updated_at''',(job['id'],job['clinic_id'],key,title,encoded,time.time(),visibility))

ALLOWED={'devices':{'ip_address','mac_address','os','model','manufacturer'},'network_addresses':{'address','prefix_length'},'clinic_tickets':{'status'}}

def managed(c,job,entity,rid,field,old,new,may_claim):
    if field not in ALLOWED.get(entity,set()) or new in (None,''):return
    row=c.execute(f'SELECT {field} FROM {entity} WHERE id=?',(rid,)).fetchone()
    if not row:return
    owner=c.execute('SELECT * FROM integration_fields WHERE entity=? AND row_id=? AND field=?',(entity,rid,field)).fetchone()
    if not owner:
        if not may_claim:return
        c.execute('INSERT INTO integration_fields(job_id,clinic_id,entity,row_id,field,last_value,overridden) VALUES (?,?,?,?,?,?,?)',(job['id'],job['clinic_id'],entity,rid,field,json.dumps(old),int(row[0]!=old)))
        owner=c.execute('SELECT * FROM integration_fields WHERE entity=? AND row_id=? AND field=?',(entity,rid,field)).fetchone()
    if owner['job_id']!=job['id'] or owner['overridden']:return
    if row[0]!=json.loads(owner['last_value']):
        c.execute('UPDATE integration_fields SET overridden=1 WHERE id=?',(owner['id'],))
        return
    if new!=row[0]:
        c.execute(f'UPDATE {entity} SET {field}=? WHERE id=?',(new,rid))
        c.execute('UPDATE integration_fields SET last_value=? WHERE id=?',(json.dumps(new),owner['id']))

def adapters_for(provider,r):
    return r.get('interfaces',[]) if provider=='syncro' else [{'mac_address':r.get('mac',''),'addresses':r.get('addresses',[])}]

def update_device(c,job,did,old,new):
    d=c.execute('SELECT * FROM devices WHERE id=? AND clinic_id=?',(did,job['clinic_id'])).fetchone()
    if not d:return
    provider=job['provider']; prefix='Imported from Syncro' if provider=='syncro' else 'Imported from UniFi'
    claimable=(d['notes'] or '').startswith(prefix)
    for field in ('os','model','manufacturer'):
        k='mac' if field=='mac_address' and provider=='unifi' else field
        managed(c,job,'devices',did,field,old.get(k),new.get(k),claimable)
    old_ifs=adapters_for(provider,old);new_ifs=adapters_for(provider,new)
    for adapter in new_ifs:
        m=mac(adapter.get('mac_address'))
        previous=[i for i in old_ifs if m and mac(i.get('mac_address'))==m]
        matches=[i for i in c.execute('SELECT * FROM network_interfaces WHERE device_id=?',(did,)) if m and mac(i['mac_address'])==m]
        if len(previous)!=1 or len(matches)!=1:continue
        iface=matches[0];origin=(iface['notes'] or '').startswith('Reported by '+('Syncro' if provider=='syncro' else 'UniFi'))
        for version in (4,6):
            before=[a for a in previous[0].get('addresses',[]) if a['version']==version]
            after=[a for a in adapter.get('addresses',[]) if a['version']==version]
            if len(before)!=1 or len(after)!=1:continue
            rows=list(c.execute('SELECT * FROM network_addresses WHERE interface_id=? AND version=?',(iface['id'],version)))
            if len(rows)!=1:continue
            row=rows[0];a=after[0]
            subnets=[]
            for vlan in c.execute('SELECT v.subnets FROM vlans v JOIN interface_vlans m ON m.vlan_id=v.id WHERE m.interface_id=?',(iface['id'],)):
                for raw in json.loads(vlan['subnets']):
                    try:
                        net=ipaddress.ip_network(raw,strict=False)
                        if net.version==version:subnets.append(net)
                    except ValueError:pass
            if subnets and not any(ipaddress.ip_address(a['address']) in net for net in subnets):
                notice(c,job,f'vlan:{did}:{iface["id"]}:{version}','Reported address is outside documented VLANs',{'device_id':did,'address':a['address']});continue
            managed(c,job,'network_addresses',row['id'],'address',before[0]['address'],a['address'],origin)
            managed(c,job,'network_addresses',row['id'],'prefix_length',before[0].get('prefix'),a.get('prefix'),origin)
            current=c.execute('SELECT address FROM network_addresses WHERE id=?',(row['id'],)).fetchone()[0]
            if row['is_primary'] and current==a['address']:
                managed(c,job,'devices',did,'ip_address',before[0]['address'],a['address'],origin and d['ip_address']==before[0]['address'])
    # Structural changes are observations for review, never silent rewiring/deletion.
    for field in ('uplink','ports','device_type'):
        if old.get(field)!=new.get(field):notice(c,job,f'{did}:{field}',f'{new.get("name","Device")}: {field} changed',{'before':old.get(field),'after':new.get(field),'device_id':did})
    old_macs={mac(i.get('mac_address')) for i in old_ifs};new_macs={mac(i.get('mac_address')) for i in new_ifs}
    if old_macs!=new_macs:notice(c,job,f'{did}:adapters','Network adapter inventory changed',{'device_id':did,'before':sorted(m for m in old_macs if m),'after':sorted(m for m in new_macs if m)})
    old_ips={a['address'] for i in old_ifs for a in i.get('addresses',[])}
    new_ips={a['address'] for i in new_ifs for a in i.get('addresses',[])}
    local_ips={r[0] for r in c.execute('SELECT a.address FROM network_addresses a JOIN network_interfaces i ON i.id=a.interface_id WHERE i.device_id=?',(did,))}
    if old_ips!=new_ips and (new_ips-local_ips or (old_ips-new_ips) & local_ips):
        notice(c,job,f'{did}:addresses','Address changes need review; local documentation preserved',{'device_id':did,'reported':sorted(new_ips),'documented':sorted(local_ips)})

def apply_result(job,result,stop=None):
    from .routers.syncro import ticket_status
    from .topology_history import capture,record_changes
    with get_db() as c:
        c.execute('BEGIN IMMEDIATE')
        current=c.execute('SELECT * FROM integration_jobs WHERE id=? AND lease=?',(job['id'],job['lease'])).fetchone()
        if not current or not current['enabled'] or not enabled(c) or (stop and stop.is_set()):return False
        if current['config']!=job['config'] or source_baseline(c,job)!=result['baseline']:
            raise HTTPException(409,'Source mapping or a reviewed import changed during refresh; retrying with fresh data')
        if hashlib.sha256((setting(c,job['provider']+'_api_key') or '').encode()).hexdigest()!=result['generation']:raise HTTPException(409,'Credentials changed during refresh; result discarded')
        cfg=json.loads(job['config']);provider=job['provider'];table=provider+'_records'
        condition='tenant=? AND clinic_id=?' if provider=='syncro' else 'host_id=? AND site_id=? AND clinic_id=?'
        params=(cfg['tenant'],job['clinic_id']) if provider=='syncro' else (cfg['host_id'],cfg['site_id'],job['clinic_id'])
        existing={(r['kind'],str(r['external_id'])):dict(r) for r in c.execute(f'SELECT * FROM {table} WHERE '+condition,params)}
        before=capture(c);seen=set()
        for kind,rid,new in result['records']:
            seen.add((kind,rid));old=existing.get((kind,rid))
            c.execute("UPDATE integration_changes SET status='resolved' WHERE job_id=? AND change_key=?",(job['id'],'absent:'+kind+':'+rid))
            if not old or not old['local_id'] and kind in ('assets','devices','clients'):
                notice(c,job,kind+':'+rid,'New source record: '+str(new.get('name') or new.get('title') or rid),new,'sales' if kind=='invoices' else 'technical');continue
            previous=json.loads(old['data']);did=old['local_id']
            c.execute("UPDATE integration_changes SET status='resolved' WHERE job_id=? AND change_key=? AND title LIKE 'New source record:%'",(job['id'],kind+':'+rid))
            if kind in ('assets','devices','clients'):update_device(c,job,did,previous,new)
            elif kind=='tickets' and did:
                managed(c,job,'clinic_tickets',did,'status',ticket_status(previous),ticket_status(new),True)
            elif kind in ('networks','vpn') and previous!=new:notice(c,job,kind+':'+rid,'Network configuration changed: '+str(new.get('name') or rid),new)
            c.execute(f'UPDATE {table} SET data=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(json.dumps(new),old['id']))
        for key,old in existing.items():
            if key[0] in result['complete'] and key not in seen:
                notice(c,job,'absent:'+':'.join(key),'Source record no longer reported (not deleted locally)',{'kind':key[0],'id':key[1],'local_id':old['local_id']},'sales' if key[0]=='invoices' else 'technical')
        record_changes(c,before,{'id':0,'display_name':'Background '+provider+' sync','username':'integration-sync'},'/api/integration-sync/refresh','POST')
        now=time.time()
        c.execute('UPDATE integration_jobs SET last_success=?,next_at=?,failures=0,error=NULL,warnings=?,lease=NULL,lease_until=0 WHERE id=?',(now,now+current['interval_minutes']*60+random.uniform(0,30),json.dumps(result['warnings']),job['id']))
    return True

def finish_error(job,error):
    # Only vetted application messages are persisted; never arbitrary exception bodies.
    message=str(error.detail) if isinstance(error,HTTPException) else 'Refresh failed safely; check server connectivity and retry'
    delay=min(21600,60*2**min(job['failures'],8))
    if isinstance(error,HTTPException):
        try:delay=max(delay,float((error.headers or {}).get('Retry-After',0)))
        except (ValueError,TypeError):pass
    with get_db() as c:
        c.execute('UPDATE integration_jobs SET failures=failures+1,error=?,next_at=?,lease=NULL,lease_until=0 WHERE id=? AND lease=?',(message,time.time()+delay+random.uniform(0,15),job['id'],job['lease']))

def worker(provider,stop):
    while not stop.wait(5):
        job=None
        try:
            job=claim(provider)
            if job:
                result=collect(job)
                if not apply_result(job,result,stop):finish_error(job,HTTPException(409,'Refresh paused; collected result discarded'))
        except Exception as e:
            if job:
                try:finish_error(job,e)
                except Exception:pass

def start():
    stop=threading.Event()
    threads=[threading.Thread(target=worker,args=(p,stop),daemon=True,name=p+'-sync') for p in ('syncro','unifi')]
    for t in threads:t.start()
    return stop,threads
