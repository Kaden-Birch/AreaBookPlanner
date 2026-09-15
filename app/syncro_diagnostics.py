"""Diagnostic shape and validated network literals, never arbitrary source text."""
import ipaddress
import json
import re
from .syncro_network import key, mac

DENY=re.compile(r'password|passwd|secret|token|credential|privatekey|recovery|apikey|notes?|comments?|customer|contact|user|email|script',re.I)

def network_diagnostics(asset):
    fields=[]
    def walk(value,path,depth=0):
        if depth>10 or len(fields)>=1000:return
        if isinstance(value,dict):
            for name,child in list(value.items())[:200]:
                if not DENY.search(key(name)):walk(child,path+[key(name)[:80]],depth+1)
        elif isinstance(value,list):
            for index,child in enumerate(value[:100]):walk(child,path+[str(index)],depth+1)
        else:
            if isinstance(value,str) and len(value)<=100000:
                try:
                    decoded=json.loads(value)
                    if isinstance(decoded,(dict,list)):
                        walk(decoded,path+['json'],depth+1);return
                except ValueError:pass
            entry={'path':'.'.join(path),'type':type(value).__name__}
            addresses=[];macs=[]
            # Free-form values are never exported, even in network-named fields.
            if isinstance(value,str) and len(value)<=100000:
                for part in re.split(r'[\s,;="\[\]{}()<>]+',value):
                    try:
                        if '%' not in part:
                            address=ipaddress.ip_interface(part)
                            if str(address.ip) not in addresses:addresses.append(str(address.ip))
                    except ValueError:pass
                    m=mac(part)
                    if m and m not in macs:macs.append(m)
            if addresses:entry['ip_literals']=addresses[:100]
            if macs:entry['mac_literals']=macs[:100]
            fields.append(entry)
    for name,value in asset.items():
        normalized=key(name)
        if normalized in ('rmmstore','properties') or any(s in normalized for s in ('network','adapter','interface','ipaddress','macaddress')):
            if not DENY.search(normalized):walk(value,[normalized])
    return {'format_version':1,'notice':'Filtered field paths/types and validated IP/MAC literals only. IP/MAC values may identify your network; review before sharing. No raw text or credentials are included.','fields':fields,'limited':len(fields)>=1000}
