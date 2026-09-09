"""Scoped documented paths. No live probing or inferred VPN transit permissions."""
from collections import deque
from fastapi import APIRouter, Depends, HTTPException
from ..database import db_dependency
from .devices import topology
from .vpn import connectivity, _ranges_for_site
from .network import vlan_list

router=APIRouter(prefix='/api',tags=['topology'])

def site_networks(conn,site):
    loc=None if str(site['site_id'])=='main' else int(site['site_id'])
    ranges={r['cidr'] for r in _ranges_for_site(conn,site['clinic_id'],loc)}
    ranges.update(s for v in vlan_list(conn,site['clinic_id'],str(site['site_id'])) for s in v['subnets'])
    return sorted(ranges)

def local_segment(conn,cid,site,start,end):
    topo=topology(cid,site,conn)
    nodes={n['id']:n for n in topo['nodes']+topo['offsite']}
    base={'kind':'local','clinic_id':cid,'site':site,'nodes':[],'links':[]}
    if start not in nodes or end not in nodes:
        return base|{'complete':False,'warning':'A VPN termination device is missing or outside this site’s documentation.'}
    adjacency={id:[] for id in nodes}
    for edge in topo['edges']:
        if edge['from'] in nodes and edge['to'] in nodes:
            adjacency[edge['from']].append((edge['to'],edge));adjacency[edge['to']].append((edge['from'],edge))
    previous={start:None};queue=deque([start])
    while queue:
        current=queue.popleft()
        if current==end:break
        for other,edge in adjacency[current]:
            if other not in previous:previous[other]=(current,edge);queue.append(other)
    if end not in previous:
        return base|{'complete':False,'nodes':[nodes[start],nodes[end]],'warning':'No documented local chain connects these devices. This is not proof of unreachability.'}
    ids=[end];links=[];current=end
    while previous[current] is not None:
        parent,edge=previous[current];detail=edge.get('details') or {}
        src_members={m['vlan_id'] for m in nodes[edge['from']].get('vlan_memberships',[]) if m['interface_id']==detail.get('source_interface_id')}
        dst_members={m['vlan_id'] for m in nodes[edge['to']].get('vlan_memberships',[]) if m['interface_id']==detail.get('target_interface_id')}
        # Connection metadata is stored in edge orientation; present it in trace order.
        if parent != edge['from']:
            detail = dict(detail)
            for suffix in ('interface_id', 'interface_name'):
                detail['source_'+suffix], detail['target_'+suffix] = detail.get('target_'+suffix), detail.get('source_'+suffix)
            src_members, dst_members = dst_members, src_members
        vlan_names={v['id']:f"{v['tag']} · {v['name']}" for v in topo['vlans']}
        boundary='VLAN transition: routed interface documented; routing policy unverified' if detail.get('vlan_mode')=='routed' else 'VLAN mismatch: endpoint memberships do not overlap; routing or tagging documentation needs review' if src_members and dst_members and not src_members&dst_members else 'Shared documented VLAN membership' if src_members&dst_members else 'VLAN transition unknown: interface membership incomplete'
        links.append({'from':parent,'to':current,'type':edge['link_type'],'details':detail,'vlan_boundary':boundary,
          'source_vlans':[vlan_names.get(v,str(v)) for v in sorted(src_members)],'destination_vlans':[vlan_names.get(v,str(v)) for v in sorted(dst_members)],
          'assessment':'Recorded routed interface; forwarding policy unverified' if detail.get('vlan_mode')=='routed' else
          'Virtual host relationship' if edge['link_type']=='virtual' else
          'Interface/VLAN documentation incomplete' if not detail.get('source_interface_id') or not detail.get('target_interface_id') or detail.get('vlan_mode','unknown')=='unknown' else
          'Documented '+detail['vlan_mode']+' connection; forwarding unverified'})
        ids.append(parent);current=parent
    return base|{'complete':True,'nodes':[nodes[id] for id in reversed(ids)],'links':list(reversed(links))}

@router.get('/clinics/{cid}/topology/trace')
def trace(cid:int,source_device_id:int,destination_clinic_id:int,destination_site:str='main',destination_device_id:int|None=None,conn=Depends(db_dependency)):
    source=conn.execute('SELECT * FROM devices WHERE id=? AND clinic_id=?',(source_device_id,cid)).fetchone()
    if not source:raise HTTPException(404,'Source device not found')
    if not conn.execute('SELECT id FROM clinics WHERE id=?',(destination_clinic_id,)).fetchone():raise HTTPException(404,'Destination clinic not found')
    try:dest_loc=None if destination_site=='main' else int(destination_site)
    except ValueError:raise HTTPException(422,'Choose a destination site')
    if dest_loc is not None and not conn.execute('SELECT id FROM clinic_locations WHERE id=? AND clinic_id=?',(dest_loc,destination_clinic_id)).fetchone():raise HTTPException(404,'Destination site not found')
    if destination_device_id is not None and not conn.execute('SELECT id FROM devices WHERE id=? AND clinic_id=? AND location_id IS ?',(destination_device_id,destination_clinic_id,dest_loc)).fetchone():raise HTTPException(404,'Destination device not found at this site')
    src_site=str(source['location_id']) if source['location_id'] is not None else 'main'
    destination={'clinic_id':destination_clinic_id,'site_id':destination_site}
    routes=[]
    if cid==destination_clinic_id and source['location_id']==dest_loc:
        routes.append({'relationship':'local','hops':[]})
    else:
        data=connectivity(cid,src_site,conn)
        for d in data['direct']:
            if d.get('kind')=='site' and d['clinic_id']==destination_clinic_id and str(d['site_id'])==destination_site:
                routes.append({'relationship':'direct','hops':[{'vpn_link_id':d['vpn_link_id'],'from':data['source_site'],'to':d}]})
        for d in data['remote']:
            if d['clinic_id']==destination_clinic_id and str(d['site_id'])==destination_site:
                routes.append({'relationship':'via','hops':d['path'],'rationale':d.get('rationale')})
    output=[]
    for route in routes[:50]:
        current=source_device_id;current_cid=cid;current_site=src_site;segments=[]
        for hop in route['hops']:
            link=dict(conn.execute('SELECT * FROM vpn_links WHERE id=?',(hop['vpn_link_id'],)).fetchone())
            loc=None if current_site=='main' else int(current_site)
            side='a' if (link['a_clinic_id'],link['a_location_id'])==(current_cid,loc) else 'b'
            other='b' if side=='a' else 'a'
            segments.append(local_segment(conn,current_cid,current_site,current,link[side+'_device_id']))
            segments.append({'kind':'vpn','id':link['id'],'name':link['name'],'notes':link['notes'],'status':link['status'],'from':hop['from'],'to':hop['to'],
                             'local_subnets':site_networks(conn,hop['from']),'remote_subnets':site_networks(conn,hop['to'])})
            current=link[other+'_device_id'];current_cid=hop['to']['clinic_id'];current_site=str(hop['to']['site_id'])
        if destination_device_id is not None:segments.append(local_segment(conn,current_cid,current_site,current,destination_device_id))
        else:segments.append(local_segment(conn,current_cid,current_site,current,current))
        output.append({'relationship':route['relationship'],'rationale':route.get('rationale'),'segments':segments,
          'documentation_complete':all(s.get('complete',True) for s in segments)})
    return {'source_device_id':source_device_id,'destination':destination,'routes':output,'truncated':len(routes)>50,
      'notice':'Documented paths only. VPN transit is included only when explicitly configured for this source site. Disabled tunnels are excluded. Up/down/unknown are recorded statuses, not live checks. Firewall, NAT, return routes and subnet forwarding are unverified.'}
