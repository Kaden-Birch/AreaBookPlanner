"""Conservative extraction of reported adapters; never infer physical wiring."""
import ipaddress
import json
import re

def key(value):return re.sub(r'[^a-z0-9]','',str(value).lower())

IP_KEYS={'ip','ipaddress','ipaddresses','ipv4','ipv6','ipv4address','ipv6address','ipv4addresses','ipv6addresses','localip','localipaddress','localipaddresses','internalip','internalipaddress'}
MAC_KEYS={'mac','macaddress','macaddresses','physicaladdress'}
CONTAINERS={'rmmstore','general','properties','network','networks','networkinfo','networkinformation','networkadapters','networkadapter','networkinterfaces','interfaces','adapters','ipconfig','networkadapterconfiguration','win32networkadapterconfiguration'}

def values(value):
    if isinstance(value,list):
        for item in value:yield from values(item)
    elif isinstance(value,str):
        yield from re.split(r'[,;\s]+',value.strip())

def mac(value):
    if not isinstance(value,str):return None
    digits=re.sub(r'[:.\-]','',value.strip())
    if re.fullmatch('[0-9a-fA-F]{12}',digits):return ':'.join(digits[i:i+2] for i in range(0,12,2)).lower()
    return None

def adapters(asset):
    found=[]
    def walk(value,depth=0):
        if depth>8:return
        if isinstance(value,str) and len(value)<100000:
            try:value=json.loads(value)
            except (ValueError,TypeError):return
        if isinstance(value,list):
            for item in value[:100]:walk(item,depth+1)
            return
        if not isinstance(value,dict):return
        fields={key(k):v for k,v in value.items()}
        addresses=[];macs=[]
        for k,v in fields.items():
            if k in IP_KEYS:
                for part in values(v):
                    try:
                        # A scoped link-local address needs an adapter scope which
                        # the existing network model cannot safely represent.
                        if '%' in part:continue
                        ip=ipaddress.ip_interface(part)
                        if ip.ip.is_unspecified or ip.ip.is_loopback:continue
                        a={'address':str(ip.ip),'version':ip.version,'prefix':ip.network.prefixlen if '/' in part else None}
                        if not any(x['address']==a['address'] for x in addresses):addresses.append(a)
                    except ValueError:pass
            if k in MAC_KEYS:
                for part in values(v):
                    m=mac(part)
                    if m and m not in macs:macs.append(m)
        if addresses or macs:
            # Scalar masks can safely describe a single address of that family.
            # Parallel lists are intentionally not paired by position.
            for version,keys in ((4,('subnetmask','ipsubnet','netmask','prefixlength')),(6,('ipv6prefixlength',))):
                family=[a for a in addresses if a['version']==version]
                mask=next((fields[k] for k in keys if isinstance(fields.get(k),(str,int))),None)
                if len(family)==1 and family[0]['prefix'] is None and mask is not None:
                    try:family[0]['prefix']=ipaddress.ip_interface(f"{family[0]['address']}/{mask}").network.prefixlen
                    except ValueError:pass
            name=next((fields[k] for k in ('interfacename','adaptername','description','name') if isinstance(fields.get(k),str)),None)
            found.append({'name':str(name or 'Reported interface')[:100],'mac_address':macs[0] if len(macs)==1 else '', 'addresses':addresses})
            # Multiple unassociated MACs are separate observations, never paired
            # arbitrarily with a parallel address list.
            if len(macs)>1:
                found.extend({'name':'Reported adapter','mac_address':m,'addresses':[]} for m in macs)
        for k,v in fields.items():
            if k in CONTAINERS:walk(v,depth+1)
    walk(asset)
    result=[]
    for item in found:
        existing=next((r for r in result if item['mac_address'] and r['mac_address']==item['mac_address']),None)
        if existing:
            for a in item['addresses']:
                if not any(x['address']==a['address'] for x in existing['addresses']):existing['addresses'].append(a)
        elif item not in result:result.append(item)
    # Flat RMM summaries often duplicate the addresses in detailed adapters.
    assigned={a['address'] for r in result if r['mac_address'] for a in r['addresses']}
    for r in result:
        if not r['mac_address']:r['addresses']=[a for a in r['addresses'] if a['address'] not in assigned]
    return [r for r in result if r['mac_address'] or r['addresses']][:100]

def fill_missing(conn,did,reported):
    """Only initialize a machine with no interfaces; never rewrite manual NICs."""
    device=conn.execute('SELECT * FROM devices WHERE id=?',(did,)).fetchone()
    if not device or conn.execute('SELECT id FROM network_interfaces WHERE device_id=?',(did,)).fetchone():return 0
    # Legacy manually documented IP/MAC must not be replaced either.
    if device['ip_address'] or device['mac_address']:return 0
    count=0;primary=None;first_mac=None;ipv6=False;names=set()
    for record in reported:
        name=record['name'];suffix=1
        while name in names:suffix+=1;name=record['name'][:90]+f' {suffix}'
        names.add(name)
        iid=conn.execute('INSERT INTO network_interfaces(device_id,name,mac_address,notes) VALUES (?,?,?,?)',(did,name,record['mac_address'] or None,'Reported by Syncro; no physical port, VLAN or uplink inferred.')).lastrowid
        first_mac=first_mac or record['mac_address']
        for a in record['addresses']:
            is_primary=primary is None
            conn.execute('INSERT INTO network_addresses(interface_id,address,version,prefix_length,is_primary) VALUES (?,?,?,?,?)',(iid,a['address'],a['version'],a['prefix'],int(is_primary)))
            primary=primary or a['address'];ipv6=ipv6 or a['version']==6
        count+=1
    if count:conn.execute('UPDATE devices SET ip_address=?,mac_address=?,ipv6_enabled=CASE WHEN ? THEN 1 ELSE ipv6_enabled END WHERE id=?',(primary,first_mac,int(ipv6),did))
    return count
