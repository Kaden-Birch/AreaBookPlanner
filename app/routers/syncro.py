"""Read-only Syncro transport and explicitly reviewed, additive imports."""
import ipaddress
import hashlib
import json
import re
import secrets
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request as URLRequest, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from ..database import db_dependency
from .extras import get_setting, set_setting
from ..syncro_network import adapters, fill_missing
from ..integration_rate import wait_turn, backoff

router=APIRouter(prefix='/api/syncro',tags=['Syncro'])
SCHEMA='''
CREATE TABLE IF NOT EXISTS syncro_links (
 id INTEGER PRIMARY KEY,
 tenant TEXT NOT NULL, customer_id INTEGER NOT NULL, clinic_id INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(tenant,customer_id));
CREATE TABLE IF NOT EXISTS syncro_connections (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, tenant TEXT NOT NULL, api_key TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS syncro_records (
 id INTEGER PRIMARY KEY,
 tenant TEXT NOT NULL, kind TEXT NOT NULL, external_id INTEGER NOT NULL, clinic_id INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
 local_id INTEGER, data TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(tenant,kind,external_id));
CREATE TABLE IF NOT EXISTS syncro_previews (
 token TEXT PRIMARY KEY, actor_id INTEGER NOT NULL, expires REAL NOT NULL, tenant TEXT NOT NULL, customer_id INTEGER NOT NULL, data TEXT NOT NULL);
'''

def initialize(conn):
    """Remove the old one-customer-per-clinic constraint without losing identities."""
    definition=conn.execute("SELECT sql FROM sqlite_master WHERE name='syncro_links'").fetchone()[0]
    if 'UNIQUE(clinic_id)' in definition:
        conn.executescript('''CREATE TABLE syncro_links_many (
          id INTEGER PRIMARY KEY,tenant TEXT NOT NULL,customer_id INTEGER NOT NULL,
          clinic_id INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,UNIQUE(tenant,customer_id));
          INSERT INTO syncro_links_many SELECT * FROM syncro_links;
          DROP TABLE syncro_links;
          ALTER TABLE syncro_links_many RENAME TO syncro_links;''')
    for table,column,ddl in [('syncro_links','connection_id','INTEGER REFERENCES syncro_connections(id)'),
                            ('syncro_links','location_id','INTEGER REFERENCES clinic_locations(id) ON DELETE SET NULL'),
                            ('syncro_links','name',"TEXT NOT NULL DEFAULT ''"),('syncro_links','categories',"TEXT NOT NULL DEFAULT '[]'"),('syncro_records','customer_id','INTEGER')]:
        if column not in {r[1] for r in conn.execute('PRAGMA table_info('+table+')')}:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}')
    conn.execute('''UPDATE syncro_records SET customer_id=(SELECT customer_id FROM syncro_links l
        WHERE l.tenant=syncro_records.tenant AND l.clinic_id=syncro_records.clinic_id)
        WHERE customer_id IS NULL AND (SELECT COUNT(*) FROM syncro_links l WHERE l.tenant=syncro_records.tenant AND l.clinic_id=syncro_records.clinic_id)=1''')

def generation(client):return hashlib.sha256((client.tenant+'\0'+client.key).encode()).hexdigest()

def admin(conn):
    if 'admin' not in conn.user['roles']:raise HTTPException(403,'Syncro setup and imports require an administrator')

class Config(BaseModel):
    subdomain: str=Field(pattern=r'^[a-zA-Z0-9][a-zA-Z0-9-]{0,62}$')
    api_key: str | None=Field(default=None,max_length=1000)

    @field_validator('api_key')
    @classmethod
    def valid_key(cls,value):
        if value is not None and any(ord(ch)<33 or ord(ch)>126 for ch in value.strip()):raise ValueError('API key must not contain whitespace or control characters')
        return value

@router.get('/settings')
def settings(conn=Depends(db_dependency)):
    admin(conn)
    return {'subdomain':get_setting(conn,'syncro_subdomain') or '', 'configured':bool(get_setting(conn,'syncro_api_key'))}

@router.put('/settings')
def configure(payload:Config,conn=Depends(db_dependency)):
    admin(conn)
    previous=get_setting(conn,'syncro_subdomain')
    if previous and previous!=payload.subdomain.lower() and payload.api_key is None:raise HTTPException(422,'Enter a key for the new Syncro account')
    set_setting(conn,'syncro_subdomain',payload.subdomain.lower())
    if payload.api_key is not None:set_setting(conn,'syncro_api_key',payload.api_key.strip())
    return settings(conn)

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

_lock=threading.Lock()
_last=0.0

class Client:
    def __init__(self,conn,connection_id=None):
        if connection_id is not None:
            row=conn.execute('SELECT tenant,api_key FROM syncro_connections WHERE id=?',(connection_id,)).fetchone()
            if not row:raise HTTPException(404,'Syncro connection not found')
            self.tenant=row['tenant'];self.key=row['api_key']
        else:
            self.tenant=get_setting(conn,'syncro_subdomain') or ''
            self.key=get_setting(conn,'syncro_api_key') or ''
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}',self.tenant) or not self.key:raise HTTPException(409,'Configure Syncro in Global settings first')
        self.base=f'https://{self.tenant}.syncromsp.com'
    def get(self,path,params=None):
        global _last
        if not re.fullmatch(r'/(customers(?:/\d+)?|contacts|customer_assets(?:/\d+)?|tickets|invoices)',path):raise ValueError('Unsupported Syncro read')
        wait_turn('syncro', .7)
        req=URLRequest(self.base+'/api/v1'+path+'?'+urlencode(params or {}),headers={'Authorization':'Bearer '+self.key,'Accept':'application/json'},method='GET')
        try:
            with build_opener(NoRedirect()).open(req,timeout=15) as response:
                raw=response.read(8_000_001)
                if len(raw)>8_000_000:raise HTTPException(502,'Syncro response exceeds the safe size limit')
                value=json.loads(raw)
                if not isinstance(value,dict):raise ValueError()
                return value
        except HTTPError as e:
            if e.code==429:raise HTTPException(429,'Syncro rate limit reached; waiting for provider cooldown',headers={'Retry-After':backoff('syncro',e.headers.get('Retry-After'))}) from None
            raise HTTPException(502,f'Syncro returned HTTP {e.code}. Check read permissions or retry later.') from None
        except (URLError,TimeoutError,ValueError):raise HTTPException(502,'Syncro could not be read. Check connectivity and credentials.') from None
    def collection(self,path,key,customer=None):
        result=[];started=time.monotonic()
        for page in range(1,101):
            if time.monotonic()-started>45:raise HTTPException(502,'Syncro collection exceeded the import time limit; no partial category was imported')
            # Invoice API has no documented customer_id filter; filter locally.
            params={'page':page}
            if customer is not None and path!='/invoices':params['customer_id']=customer
            data=self.get(path,params);rows=data.get(key)
            if not isinstance(rows,list):raise HTTPException(502,'Unexpected Syncro collection response')
            result.extend(r for r in rows if isinstance(r,dict) and (customer is None or str(r.get('customer_id'))==str(customer)))
            meta=data.get('meta') or {}
            if not rows or meta.get('total_pages') is not None and page>=int(meta['total_pages']):return result
        raise HTTPException(502,'Syncro collection exceeds 100 pages; category not imported')

def text(value,limit=500):return str(value or '')[:limit]

def ticket_status(record):
    status=record.get('status','').lower()
    if status in ('resolved','closed','invoiced'):return 'closed'
    if status in ('new','in progress','waiting for parts','waiting on customer','scheduled','customer reply','not closed'):return 'open'
    return 'unknown'

def normalize(kind,r,base):
    common={'id':int(r['id'])}
    if kind=='contacts':return common|{k:text(r.get(k)) for k in ('name','email','phone','mobile')}
    if kind=='tickets':return common|{'title':text(r.get('subject')),'status':text(r.get('status')),'date':text(r.get('created_at')),'assets':[int(a['id']) for a in r.get('assets',[]) if isinstance(a,dict) and str(a.get('id','')).isdigit()],'url':base+'/tickets/'+str(int(r['id']))}
    if kind=='invoices':return common|{k:text(r.get(k)) for k in ('number','date','due_date','total','balance_due')}|{'paid':r.get('is_paid') is True,'url':base+'/invoices/'+str(int(r['id']))}
    # Only known technical fields: never copy arbitrary properties, notes or portal tokens.
    general=(r.get('rmm_store') or {}).get('general') or {}
    props={re.sub(r'[^a-z0-9]','',k.lower()):v for k,v in {**general,**(r.get('properties') or {})}.items()}
    def field(*names):
        for name in names:
            v=r.get(name) or props.get(re.sub(r'[^a-z0-9]','',name.lower()))
            if isinstance(v,(str,int,float)) and v:return text(v)
        return ''
    addresses=[]
    for part in re.split(r'[,;\s]+',' '.join(field(k) for k in ('ip_address','ip_addresses','ip','local_ip','ipv4','ipv6'))):
        try:
            address=ipaddress.ip_interface(part)
            item={'address':str(address.ip),'version':address.version,'prefix':address.network.prefixlen if '/' in part else None}
            if item not in addresses:addresses.append(item)
        except ValueError:pass
    kind_name=text(r.get('asset_type')).lower()
    dtype=next((t for t in ('server','switch','router','printer','firewall','vm') if kind_name==t),'workstation')
    mac=field('mac_address','mac')
    if not re.fullmatch(r'(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}',mac):mac=''
    return common|{'name':text(r.get('name')) or f'Syncro asset {r["id"]}','device_type':dtype,'source_type':kind_name,'serial':field('asset_serial','serial'),'manufacturer':field('manufacturer'),'model':field('model'),'os':field('os','operating_system'),'mac_address':mac,'addresses':addresses,'url':base+'/customer_assets/'+str(int(r['id']))}

@router.get('/customers')
def customers(query:str='',page:int=1,connection_id:int|None=None,conn=Depends(db_dependency)):
    admin(conn);client=Client(conn,connection_id)
    data=client.get('/customers',{'query':query[:200],'page':max(1,page)})
    links={r['customer_id']:r['clinic_id'] for r in conn.execute('SELECT * FROM syncro_links WHERE tenant=?',(client.tenant,))}
    return {'customers':[{'id':r['id'],'name':text(r.get('business_name') or r.get('fullname')),'city':text(r.get('city')),'clinic_id':links.get(r['id'])} for r in data.get('customers',[])],'meta':data.get('meta',{})}

class PreviewIn(BaseModel):
    connection_id:int|None=Field(default=None,gt=0)
    customer_id:int=Field(gt=0)
    categories:list[str]=Field(default_factory=lambda:['contacts','assets','tickets','invoices'],max_length=4)

@router.post('/preview')
def preview(payload:PreviewIn,conn=Depends(db_dependency)):
    admin(conn);client=Client(conn,payload.connection_id)
    if set(payload.categories)-{'contacts','assets','tickets','invoices'}:raise HTTPException(422,'Unsupported import category')
    customer=client.get('/customers/'+str(payload.customer_id)).get('customer')
    if not isinstance(customer,dict) or customer.get('id')!=payload.customer_id:raise HTTPException(502,'Unexpected Syncro customer response')
    clinic={'name':text(customer.get('business_name') or customer.get('fullname')),'address':text(customer.get('address')),'city':text(customer.get('city')),'province':text(customer.get('state')),'postal_code':text(customer.get('zip')),'phone':text(customer.get('phone')),'email':text(customer.get('email'))}
    for key,source,maximum in (('lat','latitude',90),('lng','longitude',180)):
        try:
            value=float(customer.get(source))
            clinic[key]=value if -maximum<=value<=maximum else None
        except (ValueError,TypeError):clinic[key]=None
    data={'clinic':clinic,'records':{},'warnings':[],'connection_id':payload.connection_id,'generation':generation(client)}
    for category in dict.fromkeys(payload.categories):
        try:
            rows=client.collection('/customer_assets' if category=='assets' else '/'+category,category,payload.customer_id)
            data['records'][category]=[normalize(category,r,client.base) for r in rows]
            if category=='assets':
                started=time.monotonic()
                for raw,record in zip(rows,data['records'][category]):
                    detail=raw
                    try:
                        if time.monotonic()-started>45:raise HTTPException(502,'Detail time limit reached; remaining assets use list data')
                        response=client.get('/customer_assets/'+str(record['id'])).get('asset')
                        if not isinstance(response,dict) or str(response.get('customer_id'))!=str(payload.customer_id) or response.get('id')!=record['id']:raise HTTPException(502,'Asset detail identity mismatch')
                        detail={**raw,**response}
                    except HTTPException as e:data['warnings'].append(f"Asset {record['id']}: {e.detail}; using available list data")
                    record['interfaces']=adapters(detail)
                    record['addresses']=[a for i in record['interfaces'] for a in i['addresses']]
                    record['mac_address']=next((i['mac_address'] for i in record['interfaces'] if i['mac_address']),'')
                    if not record['interfaces']:data['warnings'].append(f"Asset {record['id']}: no supported IP/MAC fields found; no interface will be invented")
        except (HTTPException,ValueError,TypeError) as e:data['warnings'].append(category+': '+(e.detail if isinstance(e,HTTPException) else 'Unexpected fields; category not imported'))
    token=secrets.token_urlsafe(32)
    conn.execute('DELETE FROM syncro_previews WHERE expires<?',(time.time(),))
    conn.execute('INSERT INTO syncro_previews VALUES (?,?,?,?,?,?)',(token,conn.user['id'],time.time()+1800,client.tenant,payload.customer_id,json.dumps(data)))
    linked=conn.execute('SELECT clinic_id,location_id FROM syncro_links WHERE tenant=? AND customer_id=?',(client.tenant,payload.customer_id)).fetchone()
    return {k:v for k,v in data.items() if k!='generation'}|{'token':token,'clinic_id':linked['clinic_id'] if linked else None,'location_id':linked['location_id'] if linked else None}

class ImportIn(BaseModel):
    location_id:int|None=Field(default=None,gt=0)
    fill_missing_network:bool=False
    token:str
    area_id:int
    clinic_id:int | None=None
    name:str=Field(min_length=1,max_length=300)

class DiagnosticIn(BaseModel):
    token:str=Field(max_length=200)
    asset_id:int=Field(gt=0)

@router.post('/network-diagnostics')
def diagnostics(payload:DiagnosticIn,conn=Depends(db_dependency)):
    admin(conn)
    saved=conn.execute('SELECT * FROM syncro_previews WHERE token=? AND actor_id=? AND expires>?',(payload.token,conn.user['id'],time.time())).fetchone()
    if not saved:raise HTTPException(409,'Preview expired; build a new preview')
    data=json.loads(saved['data'])
    if not any(r['id']==payload.asset_id for r in data['records'].get('assets',[])):raise HTTPException(404,'Asset not in this preview')
    client=Client(conn,data.get('connection_id'))
    if data.get('generation')!=generation(client):raise HTTPException(409,'Syncro credentials changed; preview again')
    if client.tenant!=saved['tenant']:raise HTTPException(409,'Syncro account changed; preview again')
    asset=client.get('/customer_assets/'+str(payload.asset_id)).get('asset')
    if not isinstance(asset,dict) or asset.get('id')!=payload.asset_id or str(asset.get('customer_id'))!=str(saved['customer_id']):raise HTTPException(502,'Asset detail identity mismatch')
    from ..syncro_diagnostics import network_diagnostics
    from fastapi.responses import JSONResponse
    return JSONResponse(network_diagnostics(asset),headers={'Cache-Control':'no-store'})

@router.post('/import')
def import_customer(payload:ImportIn,conn=Depends(db_dependency)):
    admin(conn)
    saved=conn.execute('SELECT * FROM syncro_previews WHERE token=? AND actor_id=? AND expires>?',(payload.token,conn.user['id'],time.time())).fetchone()
    if not saved:raise HTTPException(409,'Preview expired or already imported; preview again')
    if not conn.execute('SELECT id FROM areas WHERE id=? AND is_active=1',(payload.area_id,)).fetchone():raise HTTPException(422,'Choose an active Area')
    tenant,customer=saved['tenant'],saved['customer_id'];data=json.loads(saved['data'])
    client=Client(conn,data.get('connection_id'))
    if tenant!=client.tenant or data.get('generation')!=generation(client):raise HTTPException(409,'Syncro credentials changed; preview again')
    linked=conn.execute('SELECT * FROM syncro_links WHERE tenant=? AND customer_id=?',(tenant,customer)).fetchone()
    cid=linked['clinic_id'] if linked else payload.clinic_id
    if linked and payload.clinic_id not in (None,cid):raise HTTPException(409,'Customer is already linked to another clinic')
    if cid:
        if not conn.execute('SELECT id FROM clinics WHERE id=? AND area_id=?',(cid,payload.area_id)).fetchone():raise HTTPException(422,'Existing clinic must be in the selected Area')
    else:
        c=data['clinic']|{'name':payload.name.strip()}
        cid=conn.execute("INSERT INTO clinics(name,address,city,province,postal_code,phone,email,area_id,relationship,stage) VALUES (?,?,?,?,?,?,?,?,'current_client','won')",[c[k] for k in ('name','address','city','province','postal_code','phone','email')]+[payload.area_id]).lastrowid
        conn.execute('UPDATE clinics SET lat=?,lng=? WHERE id=?',(c.get('lat'),c.get('lng'),cid))
    location=linked['location_id'] if linked else payload.location_id
    if linked and payload.location_id not in (None,location):raise HTTPException(409,'Customer already mapped to a different site')
    if location and not conn.execute('SELECT id FROM clinic_locations WHERE id=? AND clinic_id=?',(location,cid)).fetchone():raise HTTPException(422,'Site must belong to the selected clinic')
    conn.execute('''INSERT INTO syncro_links(tenant,customer_id,clinic_id,connection_id,location_id,name) VALUES (?,?,?,?,?,?)
        ON CONFLICT(tenant,customer_id) DO UPDATE SET updated_at=CURRENT_TIMESTAMP,connection_id=excluded.connection_id,name=excluded.name''',
        (tenant,customer,cid,data.get('connection_id'),location,data['clinic']['name']))
    categories=sorted(set(json.loads(linked['categories']) if linked else [])|set(data['records']))
    conn.execute('UPDATE syncro_links SET categories=? WHERE tenant=? AND customer_id=?',(json.dumps(categories),tenant,customer))
    counts={'created':0,'preserved':0,'interfaces_added':0}
    for kind in ('contacts','assets','tickets','invoices'):
        for record in data['records'].get(kind,[]):
            old=conn.execute('SELECT * FROM syncro_records WHERE tenant=? AND kind=? AND external_id=?',(tenant,kind,record['id'])).fetchone()
            if old and old['clinic_id']!=cid:raise HTTPException(409,'A Syncro record is already linked to a different clinic')
            if old and old['customer_id'] not in (None,customer):raise HTTPException(409,'A source record moved between Syncro customers; review its existing mapping before importing')
            local=old['local_id'] if old else None
            if old:
                counts['preserved']+=1
                if kind=='tickets' and local:
                    previous=json.loads(old['data'])
                    # Refresh source-owned status only if staff have not overridden it.
                    conn.execute('UPDATE clinic_tickets SET status=? WHERE id=? AND clinic_id=? AND status=?',(ticket_status(record),local,cid,ticket_status(previous)))
            else:
                counts['created']+=1
                if kind=='contacts':
                    first,_,last=record['name'].partition(' ')
                    local=conn.execute('INSERT INTO contacts(clinic_id,first_name,last_name,email,phone,mobile) VALUES (?,?,?,?,?,?)',(cid,first or 'Syncro contact',last,record['email'],record['phone'],record['mobile'])).lastrowid
                elif kind=='assets':
                    local=conn.execute('INSERT INTO devices(clinic_id,location_id,name,device_type,serial,manufacturer,model,os,notes) VALUES (?,?,?,?,?,?,?,?,?)',(cid,location,record['name'],record['device_type'],record['serial'],record['manufacturer'],record['model'],record['os'],'Imported from Syncro: '+record['url']+'\nReview device type and assign uplink.')).lastrowid
                elif kind=='tickets':
                    assets=[r['local_id'] for a in record['assets'] if (r:=conn.execute("SELECT local_id FROM syncro_records WHERE tenant=? AND kind='assets' AND external_id=? AND clinic_id=?",(tenant,a,cid)).fetchone())]
                    status=ticket_status(record)
                    local=conn.execute('INSERT INTO clinic_tickets(clinic_id,device_id,title,url,ticket_at,status) VALUES (?,?,?,?,?,?)',(cid,assets[0] if assets else None,record['title'],record['url'],record['date'],status)).lastrowid
                    for did in assets[1:]:conn.execute('INSERT INTO device_tickets(device_id,title,url,ticket_date,status) VALUES (?,?,?,?,?)',(did,record['title'],record['url'],record['date'],status))
            if kind=='assets' and local and (not old or payload.fill_missing_network):
                legacy=[{'name':'Reported interface','mac_address':record.get('mac_address',''),'addresses':record.get('addresses',[])}] if record.get('mac_address') or record.get('addresses') else []
                counts['interfaces_added']+=fill_missing(conn,local,record.get('interfaces',legacy))
            conn.execute('INSERT INTO syncro_records(tenant,kind,external_id,clinic_id,local_id,data,customer_id) VALUES (?,?,?,?,?,?,?) ON CONFLICT(tenant,kind,external_id) DO UPDATE SET data=excluded.data,customer_id=excluded.customer_id,updated_at=CURRENT_TIMESTAMP',(tenant,kind,record['id'],cid,local,json.dumps(record),customer))
    conn.execute('DELETE FROM syncro_previews WHERE token=?',(payload.token,))
    from ..integration_sync import discover
    discover(conn)
    return {'clinic_id':cid,**counts,'warnings':data['warnings']}

@router.get('/clinics/{cid}')
def clinic_records(cid:int,conn=Depends(db_dependency)):
    if not conn.execute('SELECT id FROM clinics WHERE id=?',(cid,)).fetchone():raise HTTPException(404,'Clinic not found')
    kinds=['contacts']
    if 'admin' in conn.user['roles']:kinds+=['assets','tickets','invoices']
    elif conn.user['active_role']=='it':kinds+=['assets','tickets']
    else:kinds+=['invoices']
    links=[{k:r[k] for k in ('id','tenant','customer_id','clinic_id','location_id','name','updated_at')} for r in conn.execute('SELECT * FROM syncro_links WHERE clinic_id=? ORDER BY id',(cid,))]
    return {'link':links[0] if links else None,'links':links,'records':[{'tenant':r['tenant'],'customer_id':r['customer_id'],'kind':r['kind'],'data':json.loads(r['data']),'local_id':r['local_id'],'updated_at':r['updated_at']} for r in conn.execute('SELECT * FROM syncro_records WHERE clinic_id=?',(cid,)) if r['kind'] in kinds]}

class ConnectionIn(Config):
    name:str=Field(min_length=1,max_length=200)

@router.get('/connections')
def connections(conn=Depends(db_dependency)):
    admin(conn)
    return [{'id':None,'name':'Default connection','subdomain':get_setting(conn,'syncro_subdomain') or '', 'configured':bool(get_setting(conn,'syncro_api_key'))}]+[
        {'id':r['id'],'name':r['name'],'subdomain':r['tenant'],'configured':bool(r['api_key'])} for r in conn.execute('SELECT * FROM syncro_connections ORDER BY id')]

@router.post('/connections')
def add_connection(p:ConnectionIn,conn=Depends(db_dependency)):
    admin(conn)
    if not p.api_key or not p.api_key.strip():raise HTTPException(422,'Enter an API key')
    rid=conn.execute('INSERT INTO syncro_connections(name,tenant,api_key) VALUES (?,?,?)',(p.name.strip(),p.subdomain.lower(),p.api_key.strip())).lastrowid
    return {'id':rid}

@router.put('/connections/{rid}')
def update_connection(rid:int,p:ConnectionIn,conn=Depends(db_dependency)):
    admin(conn)
    row=conn.execute('SELECT * FROM syncro_connections WHERE id=?',(rid,)).fetchone()
    if not row:raise HTTPException(404,'Connection not found')
    if row['tenant']!=p.subdomain.lower():raise HTTPException(409,'Create a separate connection for a different Syncro subdomain')
    conn.execute('UPDATE syncro_connections SET name=?,api_key=? WHERE id=?',(p.name.strip(),row['api_key'] if p.api_key is None else p.api_key.strip(),rid))
    conn.execute("DELETE FROM syncro_previews WHERE json_extract(data,'$.connection_id')=?",(rid,))
    return {'saved':True}
