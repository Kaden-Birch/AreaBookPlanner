"""Allowlisted Meraki observations; no raw configurations or secrets are retained."""
import ipaddress
import re
from fastapi import HTTPException
from .meraki_client import ID
from .syncro_network import adapters, mac
from .unifi_mapping import text

def identity(value):
    value = str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) else ''
    if not re.fullmatch(ID, value):
        raise HTTPException(502, 'Missing or invalid Meraki record identity; nothing imported')
    return value

def device(kind, raw):
    m = mac(raw.get('mac')) or ''
    if m and (m == '00:00:00:00:00:00' or int(m[:2], 16) & 1): m = ''
    nics = adapters({'macAddress': m, 'ipAddress': raw.get('lanIp') if kind=='devices' else raw.get('ip'), 'ipv6': raw.get('ip6')})
    return {'id': identity(raw.get('serial') if kind=='devices' else raw.get('id')), 'kind': kind,
            'name': text(raw.get('name') if kind=='devices' else raw.get('description')) or text(raw.get('serial')) or m or 'Meraki client',
            'device_type': {'switch':'switch','wireless':'access_point','appliance':'router','camera':'camera'}.get(raw.get('productType'), 'other'),
            'mac': m, 'addresses': [a for i in nics for a in i['addresses']], 'model': text(raw.get('model')),
            'serial': text(raw.get('serial')) if kind=='devices' else '', 'os': text(raw.get('os')),
            'manufacturer': 'Cisco Meraki' if kind=='devices' else text(raw.get('manufacturer')),
            'firmware': text(raw.get('firmware')), 'state': text(raw.get('status')),
            'connection_type': {'Wired':'WIRED','Wireless':'WIRELESS'}.get(raw.get('recentDeviceConnection'),'INFRASTRUCTURE' if kind=='devices' else 'UNKNOWN'),
            'uplink': text(raw.get('recentDeviceSerial')) if kind=='clients' else '',
            'uplink_port': text(raw.get('switchport')), 'vlan': text(str(raw.get('vlan') or '')),
            'ports': []}

def vlan(raw):
    rid = identity(raw.get('id')); subnets=[]
    try:
        if raw.get('subnet'): subnets.append(str(ipaddress.ip_network(raw['subnet'], strict=False)))
    except (ValueError, TypeError): pass
    return {'id':rid, 'kind':'networks', 'name':text(raw.get('name')), 'tag':int(rid) if rid.isdigit() and 1<=int(rid)<=4094 else None,
            'subnets':subnets, 'gateway':text(raw.get('applianceIp'))}

def topology(raw):
    nodes = raw.get('nodes'); links = raw.get('links')
    if not isinstance(nodes,list) or not isinstance(links,list) or len(nodes)>10000 or len(links)>10000:
        raise HTTPException(502,'Unexpected Meraki topology response')
    # Undirected LLDP/CDP observations do not prove an uplink direction or a cable.
    return {'id':'link-layer','kind':'topology','name':'Reported LLDP/CDP topology',
        'nodes':[{'id':text(n.get('derivedId')),'mac':mac(n.get('mac')),'type':text(n.get('type')),
                  'serial':text((n.get('device') or {}).get('serial'))} for n in nodes if isinstance(n,dict)],
        'links':[{'ends':[{'node':text((e.get('node') or {}).get('derivedId')),'serial':text((e.get('device') or {}).get('serial')),
                          'port':text(((e.get('discovered') or {}).get('lldp') or {}).get('portId'))} for e in l.get('ends',[]) if isinstance(e,dict)],
                  'last_reported':text(l.get('lastReportedAt'))} for l in links if isinstance(l,dict)],
        'incomplete':bool(raw.get('errors'))}

def collect(client, organization, network):
    base='/networks/'+identity(network)
    site=client.get(base)
    if str(site.get('id'))!=network or str(site.get('organizationId'))!=organization:
        raise HTTPException(409,'Meraki network does not belong to the selected organization')
    records=[]; warnings=[]; complete=[]; seen=set()
    for kind in ('devices','clients'):
        rows=client.collection(base+'/'+kind, {'perPage':1000,'timespan':86400} if kind=='clients' else None)
        ids=set()
        for raw in rows:
            if kind=='devices' and raw.get('networkId')!=network:
                raise HTTPException(502,'Meraki device belongs to a different network')
            r=device(kind,raw)
            if r['id'] in ids: raise HTTPException(502,'Repeated Meraki identity; nothing imported')
            ids.add(r['id'])
            if r['mac'] and r['mac'] in seen:
                warnings.append(r['name']+': repeated MAC observation omitted');continue
            if r['mac']:seen.add(r['mac'])
            if kind=='devices' and raw.get('productType')=='switch':
                try:
                    ports=client.collection('/devices/'+r['id']+'/switch/ports');port_ids=set()
                    for index,p in enumerate(ports):
                        pid=identity(p.get('portId'))
                        if pid in port_ids:raise HTTPException(502,'Repeated Meraki port identity')
                        port_ids.add(pid)
                        r['ports'].append({'id':pid,'idx':index+1,'name':text(p.get('name')),'type':text(p.get('type')),
                            'vlan':p.get('vlan') if isinstance(p.get('vlan'),int) else None,'allowed_vlans':text(p.get('allowedVlans')),
                            'voice_vlan':p.get('voiceVlan') if isinstance(p.get('voiceVlan'),int) else None,
                            'enabled':p.get('enabled') is True,'poe':p.get('poeEnabled') is True,'negotiation':text(p.get('linkNegotiation'))})
                except HTTPException as e:
                    if e.status_code==429:raise
                    r['ports']=[];warnings.append('Switch ports unavailable: '+str(e.detail))
            records.append(r)
        complete.append(kind)
    for kind,path in [('networks','appliance/vlans'),('vpn','appliance/vpn/siteToSiteVpn'),('topology','topology/linkLayer')]:
        if kind in ('networks','vpn') and 'appliance' not in site.get('productTypes',[]):continue
        try:
            if kind=='networks':batch=[vlan(r) for r in client.collection(base+'/'+path)]
            elif kind=='vpn':
                raw=client.get(base+'/'+path)
                batch=[{'id':'site-to-site','kind':'vpn','name':'Site-to-site VPN','type':text(raw.get('mode')),
                        'hubs':[{'network_id':text(h.get('hubId')),'default_route':h.get('useDefaultRoute') is True} for h in raw.get('hubs',[]) if isinstance(h,dict)],
                        'subnets':[{'subnet':text(s.get('localSubnet')),'enabled':s.get('useVpn') is True} for s in raw.get('subnets',[]) if isinstance(s,dict)]}]
            else:batch=[topology(client.get(base+'/'+path))]
            records.extend(batch);complete.append(kind)
        except HTTPException as e:
            if e.status_code==429:raise
            warnings.append(kind+': '+str(e.detail))
    return {'records':records,'complete':complete,'warnings':warnings,'site_name':text(site.get('name'))}
