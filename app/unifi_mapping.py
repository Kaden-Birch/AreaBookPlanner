"""Allowlisted source snapshots and site-scoped device identity reconciliation."""
import hashlib
import ipaddress
import json
from .syncro_network import adapters, mac

def text(value):
    return value[:300] if isinstance(value, str) else ''

def device(kind, raw):
    features = raw.get('features') or []
    dtype = 'router' if 'gateway' in features else 'access_point' if 'accessPoint' in features else 'switch' if 'switching' in features else 'other'
    nic = adapters({'ipAddress': raw.get('ipAddress'), 'macAddress': raw.get('macAddress')})
    identity_mac = mac(raw.get('macAddress')) or ''
    if identity_mac and (identity_mac == '00:00:00:00:00:00' or int(identity_mac[:2], 16) & 1):
        identity_mac = ''  # Not a usable unicast device identity.
    ports = []
    interfaces = raw.get('interfaces')
    if isinstance(interfaces, dict):
        for p in (interfaces.get('ports') or [])[:1024]:
            if not isinstance(p, dict) or not isinstance(p.get('idx'), int) or not 0 <= p['idx'] <= 10000:
                continue
            ports.append({'idx': p['idx'], 'connector': {'RJ45': 'rj45', 'SFP': 'sfp', 'SFPPLUS': 'sfp+', 'QSFP28': 'qsfp'}.get(p.get('connector'), 'other'),
                          'max_speed': p.get('maxSpeedMbps') if isinstance(p.get('maxSpeedMbps'), int) and 0 < p['maxSpeedMbps'] <= 10000000 else None,
                          'speed': p.get('speedMbps') if isinstance(p.get('speedMbps'), int) else None, 'state': text(p.get('state'))})
    uplink = raw.get('uplink') or {}
    return {'id': text(raw.get('id')), 'kind': kind, 'name': text(raw.get('name')) or 'UniFi device',
            'device_type': dtype, 'mac': identity_mac,
            'addresses': nic[0]['addresses'] if nic else [], 'model': text(raw.get('model')),
            'state': text(raw.get('state')), 'firmware': text(raw.get('firmwareVersion')),
            'connection_type': text(raw.get('type')) if kind == 'clients' else 'INFRASTRUCTURE',
            'uplink': text(raw.get('uplinkDeviceId') or (uplink.get('deviceId') if isinstance(uplink, dict) else None)),
            'ports': ports}

def network(raw):
    subnets = []
    for field in ('ipv4Configuration', 'ipv6Configuration'):
        config = raw.get(field) or {}
        if not isinstance(config, dict):
            continue
        candidates = config.get('additionalHostIpSubnets') or []
        if not isinstance(candidates, list):
            candidates = []
        if config.get('hostIpAddress') and config.get('prefixLength') is not None:
            candidates = candidates + [f"{config['hostIpAddress']}/{config['prefixLength']}"]
        for value in candidates[:64]:
            try:
                parsed = ipaddress.ip_network(value, strict=False)
                if str(parsed) not in subnets:
                    subnets.append(str(parsed))
            except (ValueError, TypeError):
                pass
    return {'id': text(raw.get('id')), 'name': text(raw.get('name')), 'tag': raw.get('vlanId') if isinstance(raw.get('vlanId'), int) and 1 <= raw['vlanId'] <= 4094 else None,
            'subnets': subnets, 'management': text(raw.get('management'))}

def local_state(conn, cid, location):
    devices = [dict(r) for r in conn.execute('SELECT * FROM devices WHERE clinic_id=? AND location_id IS ? ORDER BY id', (cid, location))]
    for d in devices:
        d['extra_uplinks'] = [dict(r) for r in conn.execute('SELECT * FROM device_links WHERE device_id=? ORDER BY id', (d['id'],))]
        d['interfaces'] = [dict(r) for r in conn.execute('SELECT * FROM network_interfaces WHERE device_id=? ORDER BY id', (d['id'],))]
        for i in d['interfaces']:
            i['addresses'] = [dict(r) for r in conn.execute('SELECT * FROM network_addresses WHERE interface_id=? ORDER BY id', (i['id'],))]
            i['memberships'] = [dict(r) for r in conn.execute('SELECT * FROM interface_vlans WHERE interface_id=? ORDER BY id', (i['id'],))]
    vlans = [dict(r) for r in conn.execute('SELECT * FROM vlans WHERE clinic_id=? AND location_id IS ? ORDER BY id', (cid, location))]
    return devices, hashlib.sha256(json.dumps([devices, vlans], sort_keys=True).encode()).hexdigest()

def match(record, devices, linked=None):
    if linked is not None:
        if any(d['id'] == linked for d in devices):
            return {'action': 'match', 'device_id': linked, 'reason': 'Existing UniFi source link'}
        return {'action': 'skip', 'device_id': None, 'reason': 'Previously linked device was deleted or moved; review manually'}
    mac_matches = []; hints = []
    for d in devices:
        macs = {mac(d['mac_address'])} | {mac(i['mac_address']) for i in d['interfaces']}
        ips = {d['ip_address']} | {a['address'] for i in d['interfaces'] for a in i['addresses']}
        if record['mac'] and record['mac'] in macs:
            mac_matches.append(d['id'])
        elif ips.intersection(a['address'] for a in record['addresses']) or d['name'].casefold() == record['name'].casefold():
            hints.append(d['id'])
    if len(mac_matches) == 1:
        return {'action': 'match', 'device_id': mac_matches[0], 'reason': 'Unique exact MAC in this clinic/site'}
    if mac_matches or hints:
        return {'action': 'skip', 'device_id': None, 'reason': 'Ambiguous MAC or IP/name-only similarity — select a match or create explicitly', 'candidates': mac_matches or hints}
    return {'action': 'create', 'device_id': None, 'reason': 'No matching device in this clinic/site'}
