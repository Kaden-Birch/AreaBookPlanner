"""Documentation for actual device links; never accepts derived display shortcuts."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from ..database import db_dependency
from .network import read_network, vlan_list

router=APIRouter(prefix='/api/clinics/{cid}/connections',tags=['connections'])

class Details(BaseModel):
    source_interface_id: int | None=None
    target_interface_id: int | None=None
    speed_mbps: int | None=Field(default=None,ge=1,le=10000000)
    duplex: Literal['unknown','full','half']='unknown'
    media: Literal['unknown','copper','fiber','wireless','virtual','other']='unknown'
    vlan_mode: Literal['unknown','access','trunk','routed']='unknown'
    native_vlan_id: int | None=None
    tagged_vlans: list[int]=Field(default_factory=list,max_length=256)
    admin_status: Literal['unknown','enabled','disabled']='unknown'
    notes: str | None=Field(default=None,max_length=10000)

def actual_link(conn,cid,parent,child):
    rows={r['id']:dict(r) for r in conn.execute('SELECT * FROM devices WHERE clinic_id=? AND id IN (?,?)',(cid,parent,child))}
    if len(rows)!=2: raise HTTPException(404,'Connection not found')
    primary=rows[child]['uplink_id']==parent
    if not primary and not conn.execute('SELECT id FROM device_links WHERE device_id=? AND uplink_id=?',(child,parent)).fetchone():
        raise HTTPException(404,'Connection not found')
    return rows[parent],rows[child],primary

def link_details(conn,cid):
    items={}
    for r in conn.execute('''SELECT c.*,s.name AS source_interface_name,t.name AS target_interface_name
        FROM connection_details c JOIN devices d ON d.id=c.device_id
        LEFT JOIN network_interfaces s ON s.id=c.source_interface_id
        LEFT JOIN network_interfaces t ON t.id=c.target_interface_id WHERE d.clinic_id=?''',(cid,)):
        data=dict(r);data['tagged_vlans']=[];items[(r['uplink_id'],r['device_id'])]=data
    by_id={d['id']:d for d in items.values()}
    for r in conn.execute('''SELECT cv.* FROM connection_vlans cv JOIN connection_details c ON c.id=cv.connection_id
        JOIN devices d ON d.id=c.device_id WHERE d.clinic_id=?''',(cid,)):
        if r['connection_id'] in by_id: by_id[r['connection_id']]['tagged_vlans'].append(r['vlan_id'])
    return items

@router.get('/{parent}/{child}')
def get_details(cid:int,parent:int,child:int,conn=Depends(db_dependency)):
    source,target,primary=actual_link(conn,cid,parent,child)
    return {'source':{'id':parent,'name':source['name']},'target':{'id':child,'name':target['name']},'primary':primary,
            'source_interfaces':read_network(conn,parent)['interfaces'],'target_interfaces':read_network(conn,child)['interfaces'],
            'vlans':[v for v in vlan_list(conn,cid) if v['location_id']==source['location_id']==target['location_id']],
            'details':link_details(conn,cid).get((parent,child))}

@router.put('/{parent}/{child}')
def put_details(cid:int,parent:int,child:int,payload:Details,conn=Depends(db_dependency)):
    source,target,_=actual_link(conn,cid,parent,child)
    for iid,did in [(payload.source_interface_id,parent),(payload.target_interface_id,child)]:
        if iid is not None and not conn.execute('SELECT id FROM network_interfaces WHERE id=? AND device_id=?',(iid,did)).fetchone():
            raise HTTPException(422,'Choose an interface belonging to the indicated device')
    if len(set(payload.tagged_vlans))!=len(payload.tagged_vlans): raise HTTPException(422,'Repeated tagged VLAN')
    if payload.tagged_vlans and payload.vlan_mode!='trunk': raise HTTPException(422,'Tagged VLANs require trunk mode')
    if payload.native_vlan_id in payload.tagged_vlans: raise HTTPException(422,'The native VLAN must not also be tagged')
    if payload.native_vlan_id is not None and payload.vlan_mode not in ('access','trunk'):
        raise HTTPException(422,'Access/native VLAN requires access or trunk mode')
    for vid in set(payload.tagged_vlans)|({payload.native_vlan_id} if payload.native_vlan_id is not None else set()):
        v=conn.execute('SELECT clinic_id,location_id FROM vlans WHERE id=?',(vid,)).fetchone()
        if not v or v['clinic_id']!=cid or v['location_id']!=source['location_id'] or v['location_id']!=target['location_id']:
            raise HTTPException(422,'VLANs carried by a link must belong to the site of both devices')
    data=payload.model_dump();tags=data.pop('tagged_vlans')
    existing=conn.execute('SELECT id FROM connection_details WHERE device_id=? AND uplink_id=?',(child,parent)).fetchone()
    if existing:
        id=existing['id'];conn.execute(f"UPDATE connection_details SET {','.join(k+'=?' for k in data)},updated_at=CURRENT_TIMESTAMP WHERE id=?",[*data.values(),id])
    else:
        id=conn.execute(f"INSERT INTO connection_details(device_id,uplink_id,{','.join(data)}) VALUES ({','.join('?' for _ in range(len(data)+2))})",[child,parent,*data.values()]).lastrowid
    conn.execute('DELETE FROM connection_vlans WHERE connection_id=?',(id,))
    for vid in tags: conn.execute('INSERT INTO connection_vlans(connection_id,vlan_id) VALUES (?,?)',(id,vid))
    return get_details(cid,parent,child,conn)

def documentation_issues(nodes,edges,vlans):
    """Evidence-based documentation gaps, not monitoring or reachability claims."""
    issues=[];by_id={n['id']:n for n in nodes}
    def add(kind,id,name,code,message,**extra): issues.append(dict(kind=kind,id=id,name=name,code=code,message=message,**extra))
    import ipaddress
    owners={}
    for n in nodes:
        if n.get('status')=='retired':continue
        for raw in [n.get('ip_address'),*(a.get('address') for a in n.get('addresses',[]))]:
            if not raw:continue
            try:address=ipaddress.ip_address(raw)
            except ValueError:continue
            # Link-local addresses may legitimately repeat on separate interfaces.
            if address.is_link_local:continue
            owners.setdefault((n.get('location_id'),str(address)),set()).add(n['id'])
    for (_,address),ids in owners.items():
        if len(ids)>1:
            for id in sorted(ids):add('device',id,by_id[id]['name'],'duplicate_address',f'{address} is documented on multiple devices at this site; verify whether intentionally shared')
    primary={e['to']:e['from'] for e in edges if e.get('primary') and e['from'] in by_id and e['to'] in by_id}
    cycle_members=set()
    for start in primary:
        path=[];seen={};current=start
        while current in primary and current not in seen:
            seen[current]=len(path);path.append(current);current=primary[current]
        if current in seen:cycle_members.update(path[seen[current]:])
    for id in sorted(cycle_members):add('device',id,by_id[id]['name'],'uplink','Primary uplinks form a cycle; review the documented relationships')
    pairs=set()
    for n in nodes:
        if n.get('status')=='retired' or n['device_type'] in ('patch_panel','shelf'): continue
        def gap(code,message): add('device',n['id'],n['name'],code,message)
        if n.get('ipv6_enabled'):
            has_ipv6=False
            for raw in [n.get('ip_address'),*(a.get('address') for a in n.get('addresses',[]))]:
                try:has_ipv6=has_ipv6 or ipaddress.ip_address(raw).version==6
                except ValueError:pass
            if not has_ipv6:gap('ipv6','IPv6 marked enabled, but no IPv6 address is documented')
        if not n.get('addresses') and not n.get('ip_address'): gap('address','No IP address recorded')
        if not n.get('interface_count'): gap('interface','No network interfaces recorded')
        if vlans and not n.get('vlan_memberships'): gap('vlan','No VLAN membership recorded; review whether applicable')
        if not n.get('uplink_id') and not n.get('off_site') and n['device_type'] not in ('router','firewall'):
            gap('uplink','No primary uplink recorded')
        if n['device_type'] in ('server','vm') and not n.get('services'): gap('services','No running services recorded')
    for v in vlans:
        if not v['subnets']: add('vlan',v['id'],v['name'],'subnet','No subnet or IPv6 prefix recorded')
        if not v['gateway_interface_id']: add('vlan',v['id'],v['name'],'gateway','No gateway interface recorded')
    for e in edges:
        source,target=by_id.get(e['from']),by_id.get(e['to'])
        if not source or not target or target.get('status')=='retired': continue
        detail=e.get('details') or {}
        def gap(code,message): add('connection',e['to'],source['name']+' → '+target['name'],code,message,parent=e['from'],child=e['to'])
        pair=(e['from'],e['to'])
        if pair in pairs:gap('duplicate_link','More than one connection uses these endpoints; verify whether this is an intentional parallel link')
        pairs.add(pair)
        if e.get('link_type')!='virtual' and (not detail.get('source_interface_id') or not detail.get('target_interface_id')):
            gap('ports','Endpoint interfaces are not fully documented')
        if detail.get('vlan_mode')=='trunk':
            tags=set(detail.get('tagged_vlans',[]))
            if not tags and not detail.get('native_vlan_id'): gap('trunk','Trunk has no carried VLANs recorded')
            for node,key in [(source,'source_interface_id'),(target,'target_interface_id')]:
                iid=detail.get(key)
                if iid:
                    recorded={m['vlan_id'] for m in node.get('vlan_memberships',[]) if m['interface_id']==iid and m['mode']=='tagged'}
                    if not tags.issubset(recorded): gap('trunk_membership',node['name']+': carried VLANs differ from tagged interface memberships')
    return issues
