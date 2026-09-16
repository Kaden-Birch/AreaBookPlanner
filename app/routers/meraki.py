"""Clinic-specific credentials and explicit reviewed Meraki network imports."""
import json
import secrets
import time
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from ..database import db_dependency
from ..meraki_client import Client, ID
from ..meraki_mapping import collect, identity
from ..unifi_mapping import local_state, match, text
from .unifi import target, fill_device, Import

router=APIRouter(prefix='/api/meraki',tags=['Meraki'])
SCHEMA='''
CREATE TABLE IF NOT EXISTS meraki_credentials (
 id INTEGER PRIMARY KEY, clinic_id INTEGER NOT NULL UNIQUE REFERENCES clinics(id) ON DELETE CASCADE,
 api_key TEXT NOT NULL, generation TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meraki_sites (
 id INTEGER PRIMARY KEY, organization_id TEXT NOT NULL, network_id TEXT NOT NULL UNIQUE,
 clinic_id INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
 location_id INTEGER REFERENCES clinic_locations(id) ON DELETE CASCADE, name TEXT NOT NULL,
 warnings TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE UNIQUE INDEX IF NOT EXISTS meraki_local_site ON meraki_sites(clinic_id,IFNULL(location_id,0));
CREATE TABLE IF NOT EXISTS meraki_records (
 id INTEGER PRIMARY KEY, network_id TEXT NOT NULL, kind TEXT NOT NULL, external_id TEXT NOT NULL,
 clinic_id INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
 local_id INTEGER, data TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(network_id,kind,external_id));
CREATE TABLE IF NOT EXISTS meraki_previews (
 token TEXT PRIMARY KEY, clinic_id INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
 actor_id INTEGER NOT NULL, expires REAL NOT NULL, data TEXT NOT NULL);
'''

def admin(c):
    if 'admin' not in c.user['roles']:raise HTTPException(403,'Meraki setup and imports require an administrator')

def credential(c,cid):
    row=c.execute('SELECT api_key,generation FROM meraki_credentials WHERE clinic_id=?',(cid,)).fetchone()
    if not row or not row['api_key']:raise HTTPException(409,'Save a Meraki API key for this clinic first')
    return row

@router.get('/clinics/{cid}/settings')
def settings(cid:int,c=Depends(db_dependency)):
    admin(c);target(c,cid,None)
    row=c.execute('SELECT api_key FROM meraki_credentials WHERE clinic_id=?',(cid,)).fetchone()
    return {'configured':bool(row and row['api_key'])}

class Config(BaseModel):api_key:str=Field(max_length=2000)

@router.put('/clinics/{cid}/settings')
def configure(cid:int,p:Config,c=Depends(db_dependency)):
    admin(c);target(c,cid,None);key=p.api_key.strip()
    if any(ord(ch)<33 or ord(ch)>126 for ch in key):raise HTTPException(422,'API key must not contain spaces or control characters')
    c.execute('INSERT INTO meraki_credentials(clinic_id,api_key,generation) VALUES (?,?,?) ON CONFLICT(clinic_id) DO UPDATE SET api_key=excluded.api_key,generation=excluded.generation',(cid,key,secrets.token_hex(16)))
    c.execute('DELETE FROM meraki_previews WHERE clinic_id=?',(cid,))
    return settings(cid,c)

@router.get('/clinics/{cid}/organizations')
def organizations(cid:int,c=Depends(db_dependency)):
    admin(c);target(c,cid,None)
    return [{'id':identity(r.get('id')),'name':text(r.get('name'))} for r in Client(credential(c,cid)['api_key']).collection('/organizations')]

@router.get('/clinics/{cid}/networks')
def networks(cid:int,organization_id:str,c=Depends(db_dependency)):
    admin(c);target(c,cid,None);identity(organization_id)
    rows=Client(credential(c,cid)['api_key']).collection('/organizations/'+organization_id+'/networks',{'perPage':1000})
    links={r['network_id']:dict(r) for r in c.execute('SELECT * FROM meraki_sites WHERE clinic_id=?',(cid,))}
    return [{'id':identity(r.get('id')),'name':text(r.get('name')),'link':links.get(str(r.get('id')))} for r in rows if str(r.get('organizationId'))==organization_id]

def check_link(c,org,network,cid,location):
    if c.execute('SELECT id FROM meraki_records WHERE network_id=? AND clinic_id<>? LIMIT 1',(network,cid)).fetchone():raise HTTPException(409,'This network already belongs to another clinic')
    for r in c.execute('SELECT * FROM meraki_sites WHERE network_id=? OR (clinic_id=? AND location_id IS ?)',(network,cid,location)):
        if (r['organization_id'],r['network_id'],r['clinic_id'],r['location_id'])!=(org,network,cid,location):
            raise HTTPException(409,'This Meraki network or AreaBook site is already mapped. Use the existing mapping.')

class Preview(BaseModel):
    clinic_id:int=Field(gt=0)
    organization_id:str=Field(pattern='^'+ID+'$')
    network_id:str=Field(pattern='^'+ID+'$')
    location_id:int|None=Field(default=None,gt=0)

@router.post('/preview')
def preview(p:Preview,c=Depends(db_dependency)):
    admin(c);target(c,p.clinic_id,p.location_id);check_link(c,p.organization_id,p.network_id,p.clinic_id,p.location_id)
    key=credential(c,p.clinic_id)
    data=collect(Client(key['api_key']),p.organization_id,p.network_id)
    local,fingerprint=local_state(c,p.clinic_id,p.location_id)
    for r in data['records']:
        if r['kind'] not in ('devices','clients'):continue
        old=c.execute('SELECT local_id FROM meraki_records WHERE network_id=? AND kind=? AND external_id=?',(p.network_id,r['kind'],r['id'])).fetchone()
        r['proposal']=match(r,local,old['local_id'] if old else None)
        r['proposal']['reason']=r['proposal']['reason'].replace('UniFi','Meraki')
    saved=p.model_dump()|data|{'generation':key['generation'],'fingerprint':fingerprint,'choices':[{'id':d['id'],'name':d['name']} for d in local]}
    token=secrets.token_urlsafe(32)
    c.execute('DELETE FROM meraki_previews WHERE expires<?',(time.time(),))
    c.execute('INSERT INTO meraki_previews VALUES (?,?,?,?,?)',(token,p.clinic_id,c.user['id'],time.time()+1800,json.dumps(saved)))
    return {k:v for k,v in saved.items() if k not in ('generation','fingerprint')}|{'token':token}

@router.post('/import')
def import_site(p:Import,c=Depends(db_dependency)):
    admin(c)
    saved=c.execute('SELECT * FROM meraki_previews WHERE token=? AND actor_id=? AND expires>?',(p.token,c.user['id'],time.time())).fetchone()
    if not saved:raise HTTPException(409,'Preview expired or already used; build a new preview')
    data=json.loads(saved['data']);cid=data['clinic_id'];location=data['location_id'];network=data['network_id']
    if credential(c,cid)['generation']!=data['generation']:raise HTTPException(409,'Clinic credentials changed; build a new preview')
    target(c,cid,location);check_link(c,data['organization_id'],network,cid,location)
    local,fingerprint=local_state(c,cid,location)
    if fingerprint!=data['fingerprint']:raise HTTPException(409,'Local topology changed; build a new preview')
    records={(r['kind'],r['id']):r for r in data['records'] if r['kind'] in ('devices','clients')}
    choices={(d.kind,d.id):d for d in p.decisions}
    if len(choices)!=len(p.decisions) or set(choices)!=set(records):raise HTTPException(422,'Review every device exactly once')
    selected={};counts={'created':0,'matched':0,'skipped':0,'vlans_added':0,'uplinks_added':0}
    for k,r in records.items():
        choice=choices[k]
        if choice.action=='skip':counts['skipped']+=1;continue
        old=c.execute('SELECT local_id FROM meraki_records WHERE network_id=? AND kind=? AND external_id=?',(network,*k)).fetchone()
        if old and old['local_id'] is not None and (choice.action!='match' or choice.device_id!=old['local_id']):raise HTTPException(409,'Existing source link cannot be reassigned or duplicated')
        if choice.action=='match':
            if not any(d['id']==choice.device_id for d in local):raise HTTPException(422,'Match must belong to this clinic/site')
            did=choice.device_id;counts['matched']+=1
        else:
            if r['proposal']['action']=='match':raise HTTPException(409,'Exact match exists; match or skip')
            did=c.execute('INSERT INTO devices(clinic_id,location_id,name,device_type,manufacturer,os,serial,notes) VALUES (?,?,?,?,?,?,?,?)',
                (cid,location,r['name'],r['device_type'],r['manufacturer'],r['os'],r['serial'],'Imported from Meraki. Review device type and network observations.')).lastrowid
            counts['created']+=1
        fill_device(c,did,r|{'ports':[]},choice.action=='create','Meraki')
        if choice.action=='create':
            for port in r['ports']:
                c.execute('INSERT INTO network_interfaces(device_id,name,port_group,port_order,notes) VALUES (?,?,?,?,?)',
                    (did,'Port '+port['id']+(' · '+port['name'] if port['name'] else ''),'Meraki ports',port['idx'],
                     'Reported by Meraki. Port configuration snapshot: '+json.dumps(port)+'. Review VLAN membership; negotiation is not a supported-speed inventory.'))
        selected[k]=did
    if p.import_uplinks:
        # Only explicit client attachment reports; never orient undirected LLDP links.
        for k,did in selected.items():
            r=records[k];up=selected.get(('devices',r['uplink']))
            d=c.execute('SELECT * FROM devices WHERE id=?',(did,)).fetchone()
            if k[0]!='clients' or r['state']!='Online' or r['connection_type'] not in ('WIRED','WIRELESS') or not up or up==did or d['uplink_id'] or d['device_type']=='vm':continue
            if c.execute('SELECT id FROM device_links WHERE device_id=?',(did,)).fetchone():continue
            pending=[up];seen=set();cycle=False
            while pending:
                n=pending.pop()
                if n==did:cycle=True;break
                if n in seen:continue
                seen.add(n)
                parent=c.execute('SELECT uplink_id FROM devices WHERE id=?',(n,)).fetchone()
                if parent and parent['uplink_id']:pending.append(parent['uplink_id'])
                pending.extend(row['uplink_id'] for row in c.execute('SELECT uplink_id FROM device_links WHERE device_id=?',(n,)))
            if cycle:continue
            c.execute('UPDATE devices SET uplink_id=?,link_type=? WHERE id=?',(up,'wireless' if r['connection_type']=='WIRELESS' else 'ethernet',did));counts['uplinks_added']+=1
    for r in data['records']:
        local_id=selected.get((r['kind'],r['id']))
        if r['kind']=='networks' and p.import_networks and r['tag']:
            existing=c.execute('SELECT id FROM vlans WHERE clinic_id=? AND location_id IS ? AND tag=?',(cid,location,r['tag'])).fetchone()
            if existing:local_id=existing['id']
            else:
                local_id=c.execute('INSERT INTO vlans(clinic_id,location_id,tag,name,subnets,notes) VALUES (?,?,?,?,?,?)',(cid,location,r['tag'],r['name'] or 'Meraki VLAN',json.dumps(r['subnets']),'Imported from Meraki. Review controller and interface membership.')).lastrowid
                counts['vlans_added']+=1
        c.execute('''INSERT INTO meraki_records(network_id,kind,external_id,clinic_id,local_id,data) VALUES (?,?,?,?,?,?)
            ON CONFLICT(network_id,kind,external_id) DO UPDATE SET data=excluded.data,local_id=COALESCE(meraki_records.local_id,excluded.local_id),updated_at=CURRENT_TIMESTAMP''',(network,r['kind'],r['id'],cid,local_id,json.dumps(r)))
    c.execute('''INSERT INTO meraki_sites(organization_id,network_id,clinic_id,location_id,name,warnings) VALUES (?,?,?,?,?,?)
        ON CONFLICT(network_id) DO UPDATE SET name=excluded.name,warnings=excluded.warnings,updated_at=CURRENT_TIMESTAMP''',(data['organization_id'],network,cid,location,data['site_name'],json.dumps(data['warnings'])))
    c.execute('DELETE FROM meraki_previews WHERE token=?',(p.token,))
    from ..integration_sync import discover
    discover(c)
    return counts|{'clinic_id':cid,'warnings':data['warnings']}

@router.get('/clinics/{cid}')
def observations(cid:int,c=Depends(db_dependency)):
    target(c,cid,None)
    return {'sites':[dict(r) for r in c.execute('SELECT * FROM meraki_sites WHERE clinic_id=?',(cid,))],
            'records':[{'data':json.loads(r['data']),'local_id':r['local_id'],'updated_at':r['updated_at'],'network_id':r['network_id']} for r in c.execute('SELECT * FROM meraki_records WHERE clinic_id=?',(cid,))]}
