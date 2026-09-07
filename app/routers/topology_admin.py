"""Preview-first additive imports and local topology version history."""
import csv
import hashlib
import io
import json
import sqlite3
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from ..database import db_dependency
from ..topology_history import document, differences, dependencies
from ..schemas import DeviceIn
from .devices import _clinic_or_404, create_device, update_device
from .network import Vlan, Interface, DeviceNetwork, create_vlan, read_network, put_network
from .vpn import _resolve_site_loc

router=APIRouter(prefix='/api/clinics/{cid}/topology',tags=['topology administration'])

def site_key(conn,cid,site,allow_all=True):
    _clinic_or_404(conn,cid)
    if site=='all' and allow_all:return 'all'
    if site=='all':raise HTTPException(422,'Select a single site for import')
    loc=_resolve_site_loc(conn,cid,site)
    return 'main' if loc is None else str(loc)

class VersionIn(BaseModel):
    label:str=Field(min_length=1,max_length=120)
    site:str='all'

@router.post('/versions',status_code=201)
def save_version(cid:int,payload:VersionIn,conn=Depends(db_dependency)):
    site=site_key(conn,cid,payload.site)
    if not payload.label.strip():raise HTTPException(422,'Give the version a name')
    user=getattr(conn,'user',{})
    actor=f"{user.get('display_name','System')} ({user.get('username','system')} #{user.get('id','-')})"
    snapshot=document(conn,cid,site)
    rid=conn.execute('INSERT INTO topology_versions(clinic_id,site,label,actor,document,required_clinics) VALUES (?,?,?,?,?,?)',
        (cid,site,payload.label.strip(),actor,json.dumps(snapshot),json.dumps(dependencies(snapshot)))).lastrowid
    return {'id':rid}

@router.get('/versions')
def versions(cid:int,site:str='all',conn=Depends(db_dependency)):
    site=site_key(conn,cid,site)
    return [dict(r) for r in conn.execute('SELECT id,label,site,actor,created_at FROM topology_versions WHERE clinic_id=? AND site=? ORDER BY id DESC LIMIT 200',(cid,site))]

@router.get('/versions/{vid}')
def version(cid:int,vid:int,site:str='all',conn=Depends(db_dependency)):
    site=site_key(conn,cid,site)
    row=conn.execute('SELECT * FROM topology_versions WHERE id=? AND clinic_id=? AND site=?',(vid,cid,site)).fetchone()
    if not row:raise HTTPException(404,'Version not found for this site')
    result=dict(row);result['document']=json.loads(result['document'])
    return result

@router.get('/versions/{vid}/compare')
def compare(cid:int,vid:int,site:str='all',other:int|None=None,conn=Depends(db_dependency)):
    old=version(cid,vid,site,conn)
    new=version(cid,other,site,conn)['document'] if other is not None else document(conn,cid,old['site'])
    return {'changes':differences(old['document'],new)}

@router.get('/audit')
def audit(cid:int,site:str='all',before:int|None=None,limit:int=Query(50,ge=1,le=100),conn=Depends(db_dependency)):
    site=site_key(conn,cid,site)
    rows=conn.execute('SELECT * FROM topology_audit WHERE clinic_id=? AND (? IS NULL OR id<?) ORDER BY id DESC LIMIT ?',(cid,before,before,limit)).fetchall()
    result=[]
    for row in rows:
        item=dict(row);changes=json.loads(item['changes'])
        if site!='all':
            loc=None if site=='main' else int(site)
            changes=[c for c in changes if loc in c.get('before_sites',[]) or loc in c.get('after_sites',[])]
        if changes:item['changes']=changes;result.append(item)
    return {'items':result,'next_before':rows[-1]['id'] if len(rows)==limit else None}

class ImportIn(BaseModel):
    kind:Literal['devices','vlans','interfaces']
    site:str='main'
    csv_text:str=Field(min_length=1,max_length=1000000)
    preview_token:str|None=None

HEADERS={
 'devices':{'name','device_type','ip_address','mac_address','serial','model','rack','rack_room','rack_position','notes','uplink_name'},
 'vlans':{'tag','name','subnets','description','color','dhcp_mode','notes'},
 'interfaces':{'device_name','interface_name','mac_address','address','prefix_length','vlan_tag','mode','hostname','notes'},
}

def import_rows(payload):
    if len(payload.csv_text.encode('utf-8'))>1000000:raise HTTPException(422,'CSV must be no larger than 1 MB')
    reader=csv.DictReader(io.StringIO(payload.csv_text.lstrip('\ufeff')),strict=True)
    fields=reader.fieldnames or []
    if not fields or len(set(fields))!=len(fields) or set(fields)-HEADERS[payload.kind]:
        raise HTTPException(422,'Missing, duplicate, or unsupported headers. Use the CSV template.')
    rows=[]
    try:
        for row in reader:
            if None in row or any(v is None for v in row.values()):raise HTTPException(422,f'CSV row {reader.line_num}: wrong number of columns')
            if any(v.strip() for v in row.values()):rows.append({k:v.strip() for k,v in row.items()})
            if len(rows)>500:raise HTTPException(422,'Import at most 500 rows at a time')
    except csv.Error as e:raise HTTPException(422,f'Invalid CSV: {e}')
    if not rows:raise HTTPException(422,'CSV contains no data rows')
    return rows

def apply_import(conn,cid,payload,site):
    rows=import_rows(payload);loc=None if site=='main' else int(site)
    existing=[dict(r) for r in conn.execute('SELECT * FROM devices WHERE clinic_id=?',(cid,)) if r['location_id']==loc]
    by_name={}
    for d in existing:by_name.setdefault(d['name'].casefold(),[]).append(d)
    def device(name):
        found=by_name.get(name.casefold(),[])
        if len(found)!=1:raise ValueError(f'Device name is missing or ambiguous at this site: {name}')
        return found[0]
    summaries=[]
    if payload.kind=='devices':
        created=[]
        serials={r['serial'].casefold() for r in existing if r['serial']}
        for index,row in enumerate(rows,2):
            try:
                if not row.get('name') or not row.get('device_type'):raise ValueError('name and device_type are required')
                if row['name'].casefold() in by_name:raise ValueError('Device name already exists; imports never overwrite')
                if row.get('serial') and row['serial'].casefold() in serials:raise ValueError('Serial already exists at this site')
                data={k:v for k,v in row.items() if v and k!='uplink_name'}
                model=DeviceIn(**data,location_id=loc)
                saved=create_device(cid,model,conn)
                if row.get('ip_address') or row.get('mac_address'):
                    put_network(saved['id'],DeviceNetwork(interfaces=[Interface(name='Primary',
                        mac_address=row.get('mac_address') or None,
                        addresses=[{'address':row['ip_address']}] if row.get('ip_address') else [])]),conn)
                by_name[row['name'].casefold()]=[saved]
                if row.get('serial'):serials.add(row['serial'].casefold())
                created.append((saved,model,row.get('uplink_name'),index))
                summaries.append({'row':index,'action':'Add device','name':saved['name']})
            except (ValueError,HTTPException) as e:raise HTTPException(422,f'Row {index}: {getattr(e,"detail",str(e))}')
        for saved,model,uplink,index in created:
            if uplink:
                try:update_device(saved['id'],model.model_copy(update={'uplink_id':device(uplink)['id']}),conn)
                except (ValueError,HTTPException) as e:raise HTTPException(422,f'Row {index}: {getattr(e,"detail",str(e))}')
    elif payload.kind=='vlans':
        for index,row in enumerate(rows,2):
            try:
                data={k:v for k,v in row.items() if v}
                data['subnets']=[s.strip() for s in row.get('subnets','').split(';') if s.strip()]
                saved=create_vlan(cid,Vlan(**data,location_id=loc),conn)
                summaries.append({'row':index,'action':'Add VLAN','name':saved['name']})
            except (ValueError,HTTPException) as e:raise HTTPException(422,f'Row {index}: {getattr(e,"detail",str(e))}')
    else:
        groups={};vlans={r['tag']:r['id'] for r in conn.execute('SELECT * FROM vlans WHERE clinic_id=?',(cid,)) if r['location_id']==loc}
        for index,row in enumerate(rows,2):
            try:
                did=device(row.get('device_name',''))['id'];name=row.get('interface_name','')
                if not name:raise ValueError('interface_name is required')
                key=(did,name.casefold())
                entry=groups.setdefault(key,{'name':name,'mac_address':row.get('mac_address') or None,'addresses':[],'memberships':[]})
                if (row.get('mac_address') or None)!=entry['mac_address']:raise ValueError('Rows for an interface must use the same MAC address')
                vid=None
                if row.get('vlan_tag'):
                    vid=vlans.get(int(row['vlan_tag']))
                    if vid is None:raise ValueError('Create the VLAN at this site first')
                    membership={'vlan_id':vid,'mode':row.get('mode') or 'access'}
                    if membership not in entry['memberships']:entry['memberships'].append(membership)
                if row.get('address'):
                    entry['addresses'].append({'address':row['address'],'prefix_length':int(row['prefix_length']) if row.get('prefix_length') else None,
                        'vlan_id':vid,'hostname':row.get('hostname'),'notes':row.get('notes')})
                Interface(**entry)
                summaries.append({'row':index,'action':'Add interface/address','name':row['device_name']+' / '+name})
            except (ValueError,HTTPException) as e:raise HTTPException(422,f'Row {index}: {getattr(e,"detail",str(e))}')
        for did in sorted({key[0] for key in groups}):
            current=read_network(conn,did)['interfaces']
            additions=[v for (d,_),v in groups.items() if d==did]
            if {i['name'].casefold() for i in current}&{i['name'].casefold() for i in additions}:
                raise HTTPException(422,'An interface name already exists; import only new interfaces')
            put_network(did,DeviceNetwork(interfaces=current+additions),conn)
    return summaries

def fingerprint(conn,cid,payload,site):
    data=[cid,site,payload.kind,payload.csv_text,document(conn,cid)]
    return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()

@router.post('/import/preview')
def preview_import(cid:int,payload:ImportIn,conn=Depends(db_dependency)):
    site=site_key(conn,cid,payload.site,False)
    token=fingerprint(conn,cid,payload,site)
    raw=getattr(conn,'raw',conn)
    raw.execute('SAVEPOINT topology_import_preview')
    try:
        rows=apply_import(conn,cid,payload,site)
        return {'rows':rows,'preview_token':token,'site':site}
    except (sqlite3.IntegrityError,csv.Error):raise HTTPException(422,'Invalid CSV or import conflicts with an existing record')
    finally:
        raw.execute('ROLLBACK TO topology_import_preview')
        raw.execute('RELEASE topology_import_preview')

@router.post('/import/commit',status_code=201)
def commit_import(cid:int,payload:ImportIn,conn=Depends(db_dependency)):
    site=site_key(conn,cid,payload.site,False)
    if payload.preview_token!=fingerprint(conn,cid,payload,site):
        raise HTTPException(409,'CSV or topology changed. Preview again before importing.')
    try:rows=apply_import(conn,cid,payload,site)
    except (sqlite3.IntegrityError,csv.Error):raise HTTPException(422,'Invalid CSV or import conflicts with an existing record')
    return {'imported_rows':len(rows)}
