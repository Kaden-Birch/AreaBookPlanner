"""IT-scoped interface, address, and VLAN documentation."""
import ipaddress
import json
import re
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from ..database import db_dependency

router=APIRouter(prefix='/api',tags=['network'])

class Membership(BaseModel):
    vlan_id: int
    mode: Literal['access','tagged','native','routed']='access'

class Address(BaseModel):
    address: str
    prefix_length: int | None=None
    vlan_id: int | None=None
    kind: Literal['static','dhcp','management','virtual','loopback','service','nat','floating']='static'
    is_primary: bool=False
    hostname: str | None=Field(default=None,max_length=255)
    notes: str | None=Field(default=None,max_length=10000)

    @model_validator(mode='after')
    def valid(self):
        raw=self.address.strip()
        parsed=ipaddress.ip_interface(raw)
        if '%' in raw:
            raise ValueError('Record the interface separately; omit IPv6 zone suffixes')
        if '/' in raw:
            if self.prefix_length is not None and self.prefix_length!=parsed.network.prefixlen:
                raise ValueError('Address and prefix length disagree')
            self.prefix_length=parsed.network.prefixlen
        if self.prefix_length is not None and not 0<=self.prefix_length<=parsed.max_prefixlen:
            raise ValueError('Invalid prefix length for this IP version')
        self.address=str(parsed.ip)
        return self

class Interface(BaseModel):
    id: int | None=None
    name: str=Field(min_length=1,max_length=100)
    mac_address: str | None=None
    notes: str | None=Field(default=None,max_length=10000)
    addresses: list[Address]=Field(default_factory=list,max_length=100)
    memberships: list[Membership]=Field(default_factory=list,max_length=256)

    @field_validator('name')
    @classmethod
    def name_valid(cls,v):
        if not v.strip(): raise ValueError('Interface name is required')
        return v.strip()

    @field_validator('mac_address')
    @classmethod
    def mac_valid(cls,v):
        if not v or not v.strip(): return None
        raw=re.sub(r'[:.\-]','',v.strip())
        if not re.fullmatch('[0-9a-fA-F]{12}',raw): raise ValueError('MAC address must contain 12 hexadecimal digits')
        return ':'.join(raw[i:i+2] for i in range(0,12,2)).upper()

class DeviceNetwork(BaseModel):
    interfaces: list[Interface]=Field(default_factory=list,max_length=100)

class Vlan(BaseModel):
    location_id: int | None=None
    tag: int=Field(ge=1,le=4094)
    name: str=Field(min_length=1,max_length=100)
    description: str | None=Field(default=None,max_length=10000)
    subnets: list[str]=Field(default_factory=list,max_length=64)
    color: str='#547ee8'
    gateway_interface_id: int | None=None
    dhcp_mode: Literal['unknown','dhcp','static','mixed']='unknown'
    notes: str | None=Field(default=None,max_length=10000)

    @field_validator('name')
    @classmethod
    def name_valid(cls,v):
        if not v.strip(): raise ValueError('VLAN name is required')
        return v.strip()

    @field_validator('subnets')
    @classmethod
    def subnets_valid(cls,v):
        return list(dict.fromkeys(str(ipaddress.ip_network(s.strip(),strict=False)) for s in v))

    @field_validator('color')
    @classmethod
    def color_valid(cls,v):
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',v): raise ValueError('Use a six-digit hex color')
        return v

def device(conn,did):
    d=conn.execute('SELECT * FROM devices WHERE id=?',(did,)).fetchone()
    if not d: raise HTTPException(404,'Device not found')
    return dict(d)

def read_network(conn,did):
    interfaces=[dict(r) for r in conn.execute('SELECT * FROM network_interfaces WHERE device_id=? ORDER BY id',(did,))]
    for i in interfaces:
        i['addresses']=[dict(r) for r in conn.execute('SELECT * FROM network_addresses WHERE interface_id=? ORDER BY is_primary DESC,id',(i['id'],))]
        i['memberships']=[dict(r) for r in conn.execute('SELECT * FROM interface_vlans WHERE interface_id=? ORDER BY vlan_id',(i['id'],))]
    return {'interfaces':interfaces}

@router.get('/devices/{did}/network')
def get_network(did:int,conn=Depends(db_dependency)):
    d=device(conn,did)
    return read_network(conn,did)|{'legacy_ip':d['ip_address'],'legacy_mac':d['mac_address'],'location_id':d['location_id']}

@router.put('/devices/{did}/network')
def put_network(did:int,payload:DeviceNetwork,conn=Depends(db_dependency)):
    d=device(conn,did)
    existing={r['id'] for r in conn.execute('SELECT id FROM network_interfaces WHERE device_id=?',(did,))}
    ids=[i.id for i in payload.interfaces if i.id is not None]
    if len(set(ids))!=len(ids) or any(i not in existing for i in ids): raise HTTPException(422,'Invalid or repeated interface ID')
    names=[i.name.casefold() for i in payload.interfaces]
    if len(set(names))!=len(names): raise HTTPException(422,'Interface names must be unique on a device')
    addresses=[a for i in payload.interfaces for a in i.addresses]
    if sum(a.is_primary for a in addresses)>1: raise HTTPException(422,'Choose one primary address for the device')
    if addresses and not any(a.is_primary for a in addresses): addresses[0].is_primary=True
    for i in payload.interfaces:
        memberships={m.vlan_id for m in i.memberships}
        if len(memberships)!=len(i.memberships): raise HTTPException(422,'A VLAN may appear once per interface')
        if sum(m.mode in ('access','native') for m in i.memberships)>1: raise HTTPException(422,'Choose at most one access/native VLAN per interface')
        if len({a.address for a in i.addresses})!=len(i.addresses): raise HTTPException(422,'Duplicate address on an interface')
        for vid in memberships:
            v=conn.execute('SELECT clinic_id,location_id FROM vlans WHERE id=?',(vid,)).fetchone()
            if not v or v['clinic_id']!=d['clinic_id'] or v['location_id']!=d['location_id']:
                raise HTTPException(422,'VLAN must belong to the device’s clinic and site')
        if any(a.vlan_id is not None and a.vlan_id not in memberships for a in i.addresses):
            raise HTTPException(422,'Address VLAN must be assigned to its interface')
    for iid in existing-set(ids):
        if conn.execute('SELECT id FROM connection_details WHERE source_interface_id=? OR target_interface_id=?',(iid,iid)).fetchone():
            raise HTTPException(409,'This interface is assigned to a connection; update the connection before removing it')
        if conn.execute('SELECT id FROM vlans WHERE gateway_interface_id=?',(iid,)).fetchone():
            raise HTTPException(409,'This interface is a VLAN gateway; update the VLAN gateway before removing it')
        conn.execute('DELETE FROM network_interfaces WHERE id=?',(iid,))
    primary=None; primary_mac=None
    for i in payload.interfaces:
        if i.id is None:
            iid=conn.execute('INSERT INTO network_interfaces(device_id,name,mac_address,notes) VALUES (?,?,?,?)',(did,i.name,i.mac_address,i.notes)).lastrowid
        else:
            iid=i.id
            conn.execute('UPDATE network_interfaces SET name=?,mac_address=?,notes=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(i.name,i.mac_address,i.notes,iid))
        conn.execute('DELETE FROM network_addresses WHERE interface_id=?',(iid,))
        conn.execute('DELETE FROM interface_vlans WHERE interface_id=?',(iid,))
        for m in i.memberships:
            conn.execute('INSERT INTO interface_vlans(interface_id,vlan_id,mode) VALUES (?,?,?)',(iid,m.vlan_id,m.mode))
        for a in i.addresses:
            conn.execute('''INSERT INTO network_addresses(interface_id,address,version,prefix_length,vlan_id,kind,is_primary,hostname,notes)
                VALUES (?,?,?,?,?,?,?,?,?)''',(iid,a.address,ipaddress.ip_address(a.address).version,a.prefix_length,a.vlan_id,a.kind,int(a.is_primary),a.hostname,a.notes))
            if a.is_primary: primary=a.address;primary_mac=i.mac_address
    conn.execute('UPDATE devices SET ip_address=?,mac_address=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(primary,primary_mac or (payload.interfaces[0].mac_address if payload.interfaces else None),did))
    return read_network(conn,did)

def vlan_list(conn,cid,site=None):
    clause=''; args=[cid]
    if site=='main': clause=' AND v.location_id IS NULL'
    elif site and site!='all':
        try: location=int(site)
        except ValueError: raise HTTPException(422,'Invalid site')
        clause=' AND v.location_id=?';args.append(location)
    rows=[dict(r) for r in conn.execute('''SELECT v.*,l.name AS location_name,i.name AS gateway_interface_name,d.name AS gateway_device_name
        FROM vlans v LEFT JOIN clinic_locations l ON l.id=v.location_id
        LEFT JOIN network_interfaces i ON i.id=v.gateway_interface_id LEFT JOIN devices d ON d.id=i.device_id
        WHERE v.clinic_id=?'''+clause+' ORDER BY v.tag,v.id',args)]
    for v in rows: v['subnets']=json.loads(v['subnets'])
    return rows

@router.get('/clinics/{cid}/vlans')
def get_vlans(cid:int,site:str|None=None,conn=Depends(db_dependency)):
    if not conn.execute('SELECT id FROM clinics WHERE id=?',(cid,)).fetchone(): raise HTTPException(404,'Clinic not found')
    return {'vlans':vlan_list(conn,cid,site),'interfaces':[dict(r) for r in conn.execute('''SELECT i.id,i.name,d.name AS device_name,d.location_id
        FROM network_interfaces i JOIN devices d ON d.id=i.device_id WHERE d.clinic_id=? ORDER BY d.name,i.name''',(cid,))]}

def save_vlan(conn,cid,payload,vid=None):
    if not conn.execute('SELECT id FROM clinics WHERE id=?',(cid,)).fetchone(): raise HTTPException(404,'Clinic not found')
    if payload.location_id is not None and not conn.execute('SELECT id FROM clinic_locations WHERE id=? AND clinic_id=?',(payload.location_id,cid)).fetchone():
        raise HTTPException(422,'Invalid VLAN site')
    if vid is not None:
        old=conn.execute('SELECT * FROM vlans WHERE id=? AND clinic_id=?',(vid,cid)).fetchone()
        if not old: raise HTTPException(404,'VLAN not found')
        if old['location_id']!=payload.location_id and conn.execute('SELECT id FROM interface_vlans WHERE vlan_id=?',(vid,)).fetchone():
            raise HTTPException(409,'Remove VLAN memberships before moving this VLAN to another site')
        if old['location_id']!=payload.location_id and (conn.execute('SELECT id FROM connection_vlans WHERE vlan_id=?',(vid,)).fetchone() or conn.execute('SELECT id FROM connection_details WHERE native_vlan_id=?',(vid,)).fetchone()):
            raise HTTPException(409,'Remove this VLAN from connections before moving it to another site')
    if conn.execute('SELECT id FROM vlans WHERE clinic_id=? AND location_id IS ? AND tag=? AND id<>?',(cid,payload.location_id,payload.tag,vid or -1)).fetchone():
        raise HTTPException(409,'That VLAN ID already exists at this site')
    if payload.gateway_interface_id is not None:
        gateway=conn.execute('''SELECT d.clinic_id,d.location_id FROM network_interfaces i JOIN devices d ON d.id=i.device_id WHERE i.id=?''',(payload.gateway_interface_id,)).fetchone()
        if not gateway or gateway['clinic_id']!=cid or gateway['location_id']!=payload.location_id:
            raise HTTPException(422,'Gateway must be an interface at this clinic and site')
    data=payload.model_dump();data['subnets']=json.dumps(data['subnets'])
    if vid is None:
        vid=conn.execute(f"INSERT INTO vlans(clinic_id,{','.join(data)}) VALUES ({','.join('?' for _ in range(len(data)+1))})",[cid,*data.values()]).lastrowid
    else:
        conn.execute(f"UPDATE vlans SET {','.join(k+'=?' for k in data)},updated_at=CURRENT_TIMESTAMP WHERE id=?",[*data.values(),vid])
    return next(v for v in vlan_list(conn,cid) if v['id']==vid)

@router.post('/clinics/{cid}/vlans',status_code=201)
def create_vlan(cid:int,payload:Vlan,conn=Depends(db_dependency)):
    return save_vlan(conn,cid,payload)

@router.put('/clinics/{cid}/vlans/{vid}')
def update_vlan(cid:int,vid:int,payload:Vlan,conn=Depends(db_dependency)):
    return save_vlan(conn,cid,payload,vid)

@router.delete('/clinics/{cid}/vlans/{vid}',status_code=204)
def delete_vlan(cid:int,vid:int,conn=Depends(db_dependency)):
    if not conn.execute('SELECT id FROM vlans WHERE clinic_id=? AND id=?',(cid,vid)).fetchone(): raise HTTPException(404,'VLAN not found')
    if conn.execute('SELECT id FROM interface_vlans WHERE vlan_id=?',(vid,)).fetchone(): raise HTTPException(409,'Remove interface memberships before deleting this VLAN')
    if conn.execute('SELECT id FROM connection_vlans WHERE vlan_id=?',(vid,)).fetchone() or conn.execute('SELECT id FROM connection_details WHERE native_vlan_id=?',(vid,)).fetchone():
        raise HTTPException(409,'Remove this VLAN from connections before deleting it')
    conn.execute('DELETE FROM vlans WHERE id=?',(vid,))

def enrich_topology(conn,nodes,cid,site):
    by_id={n['id']:n for n in nodes}
    for n in nodes: n['addresses']=[];n['vlan_memberships']=[];n['interface_count']=0
    for r in conn.execute('''SELECT i.device_id,COUNT(*) AS n FROM network_interfaces i JOIN devices d ON d.id=i.device_id
        WHERE d.clinic_id=? GROUP BY i.device_id''',(cid,)):
        if r['device_id'] in by_id: by_id[r['device_id']]['interface_count']=r['n']
    for r in conn.execute('''SELECT a.*,i.device_id,i.name AS interface_name FROM network_addresses a
        JOIN network_interfaces i ON i.id=a.interface_id JOIN devices d ON d.id=i.device_id WHERE d.clinic_id=?
        ORDER BY a.is_primary DESC,a.id''',(cid,)):
        if r['device_id'] in by_id: by_id[r['device_id']]['addresses'].append(dict(r))
    for r in conn.execute('''SELECT m.*,i.device_id,i.name AS interface_name FROM interface_vlans m
        JOIN network_interfaces i ON i.id=m.interface_id JOIN devices d ON d.id=i.device_id WHERE d.clinic_id=?''',(cid,)):
        if r['device_id'] in by_id: by_id[r['device_id']]['vlan_memberships'].append(dict(r))
    return vlan_list(conn,cid,site)
