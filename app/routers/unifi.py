"""Admin-reviewed UniFi cloud imports. All upstream requests are read-only."""
import json
import re
import secrets
import time
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from ..database import db_dependency
from ..unifi_client import Client, HOST, ID
from ..unifi_mapping import device, network, text, local_state, match
from ..syncro_network import mac
from .extras import get_setting, set_setting

router = APIRouter(prefix='/api/unifi', tags=['UniFi'])
SCHEMA = '''
CREATE TABLE IF NOT EXISTS unifi_sites (
 id INTEGER PRIMARY KEY,
 host_id TEXT NOT NULL, site_id TEXT NOT NULL, clinic_id INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
 location_id INTEGER REFERENCES clinic_locations(id) ON DELETE CASCADE, name TEXT NOT NULL,
 warnings TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(host_id,site_id));
CREATE UNIQUE INDEX IF NOT EXISTS unifi_local_site ON unifi_sites(clinic_id,IFNULL(location_id,0));
CREATE TABLE IF NOT EXISTS unifi_records (
 id INTEGER PRIMARY KEY,
 host_id TEXT NOT NULL, site_id TEXT NOT NULL, kind TEXT NOT NULL, external_id TEXT NOT NULL,
 clinic_id INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
 local_id INTEGER, data TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(host_id,site_id,kind,external_id));
CREATE TABLE IF NOT EXISTS unifi_previews (
 token TEXT PRIMARY KEY, actor_id INTEGER NOT NULL, expires REAL NOT NULL, data TEXT NOT NULL);
'''

def admin(conn):
    if 'admin' not in conn.user['roles']:
        raise HTTPException(403, 'UniFi setup and imports require an administrator')

def client(conn):
    return Client(get_setting(conn, 'unifi_api_key'))

class Config(BaseModel):
    api_key: str = Field(max_length=2000)

@router.get('/settings')
def settings(conn=Depends(db_dependency)):
    admin(conn)
    return {'configured': bool(get_setting(conn, 'unifi_api_key'))}

@router.put('/settings')
def configure(payload: Config, conn=Depends(db_dependency)):
    admin(conn)
    key = payload.api_key.strip()
    if any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise HTTPException(422, 'API key must not contain spaces or control characters')
    set_setting(conn, 'unifi_api_key', key)
    set_setting(conn, 'unifi_generation', secrets.token_hex(16))
    conn.execute('DELETE FROM unifi_previews')
    return settings(conn)

@router.get('/hosts')
def hosts(conn=Depends(db_dependency)):
    admin(conn)
    rows = client(conn).collection('/v1/hosts')
    return [{'id': text(r.get('id')), 'name': text((r.get('reportedState') if isinstance(r.get('reportedState'), dict) else {}).get('name')) or text(r.get('id')),
             'type': text(r.get('type')), 'blocked': r.get('isBlocked') is True} for r in rows if re.fullmatch(HOST, text(r.get('id')))]

@router.get('/sites')
def sites(host_id: str = '', conn=Depends(db_dependency)):
    admin(conn)
    if not re.fullmatch(HOST, host_id):
        raise HTTPException(422, 'Invalid console ID')
    rows = client(conn).collection('/v1/sites', host_id)
    links = {r['site_id']: dict(r) for r in conn.execute('SELECT * FROM unifi_sites WHERE host_id=?', (host_id,))}
    return [{'id': text(r.get('id')), 'name': text(r.get('name')), 'link': links.get(r.get('id'))} for r in rows if re.fullmatch(ID, text(r.get('id')))]

def target(conn, cid, location):
    if not conn.execute('SELECT id FROM clinics WHERE id=?', (cid,)).fetchone():
        raise HTTPException(404, 'Clinic not found')
    if location is not None and not conn.execute('SELECT id FROM clinic_locations WHERE id=? AND clinic_id=?', (location, cid)).fetchone():
        raise HTTPException(422, 'Site does not belong to this clinic')

def check_link(conn, host, site, cid, location):
    if conn.execute('SELECT id FROM unifi_records WHERE host_id=? AND site_id=? AND clinic_id<>? LIMIT 1', (host, site, cid)).fetchone():
        raise HTTPException(409, 'UniFi source records already belong to another clinic')
    for r in conn.execute('SELECT * FROM unifi_sites WHERE (host_id=? AND site_id=?) OR (clinic_id=? AND location_id IS ?)', (host, site, cid, location)):
        if (r['host_id'], r['site_id'], r['clinic_id'], r['location_id']) != (host, site, cid, location):
            raise HTTPException(409, 'This UniFi or AreaBook site is already mapped elsewhere. Use its existing mapping.')

class Preview(BaseModel):
    host_id: str = Field(pattern='^'+HOST+'$')
    site_id: str = Field(pattern='^'+ID+'$')
    clinic_id: int = Field(gt=0)
    location_id: int | None = Field(default=None, gt=0)

@router.post('/preview')
def preview(payload: Preview, conn=Depends(db_dependency)):
    admin(conn); target(conn, payload.clinic_id, payload.location_id)
    check_link(conn, payload.host_id, payload.site_id, payload.clinic_id, payload.location_id)
    generation = get_setting(conn, 'unifi_generation')
    c = client(conn)
    remote_site = next((r for r in c.collection('/v1/sites', payload.host_id) if r.get('id') == payload.site_id), None)
    if remote_site is None:
        raise HTTPException(404, 'UniFi site not found on this console')
    base = '/v1/sites/' + payload.site_id
    records = []; warnings = []; seen_macs = set()
    for kind in ('devices', 'clients', 'networks', 'vpn/site-to-site-tunnels'):
        try:
            rows = c.collection(base + '/' + kind, payload.host_id)
        except HTTPException as e:
            if kind in ('devices', 'clients'):
                raise  # Never label a partially read inventory as complete.
            warnings.append(kind + ': ' + e.detail); continue
        for raw in rows:
            rid = text(raw.get('id'))
            if not re.fullmatch(ID, rid):
                raise HTTPException(502, 'Invalid UniFi record identity; preview aborted')
            overview = raw
            if kind in ('devices', 'networks'):
                try:
                    detail = c.get(base + '/' + kind + '/' + rid, payload.host_id)
                    if detail.get('id') != rid:
                        raise HTTPException(502, 'Detail identity mismatch')
                    raw = {**raw, **detail}
                except HTTPException as e:
                    warnings.append(f'{kind} {rid}: {e.detail}; using list fields only')
            if kind in ('devices', 'clients'):
                if kind == 'clients' and raw.get('type') not in ('WIRED', 'WIRELESS'):
                    warnings.append(f'{rid}: VPN/Teleport or unknown client type omitted; not assumed to be a local machine'); continue
                record = device(kind, raw)
                if kind == 'devices':
                    record['device_type'] = device(kind, overview)['device_type']
                if record['mac'] and record['mac'] in seen_macs:
                    warnings.append(f'{rid}: repeated MAC observation omitted'); continue
                if record['mac']:
                    seen_macs.add(record['mac'])
            elif kind == 'networks':
                record = network(raw) | {'kind': kind}
            else:
                record = {'id': rid, 'kind': 'vpn', 'name': text(raw.get('name')), 'type': text(raw.get('type'))}
            records.append(record)
    local, fingerprint = local_state(conn, payload.clinic_id, payload.location_id)
    for r in records:
        if r['kind'] not in ('devices', 'clients'):
            continue
        old = conn.execute('SELECT local_id FROM unifi_records WHERE host_id=? AND site_id=? AND kind=? AND external_id=?', (payload.host_id, payload.site_id, r['kind'], r['id'])).fetchone()
        r['proposal'] = match(r, local, old['local_id'] if old else None)
    data = payload.model_dump() | {'generation': generation, 'site_name': text(remote_site.get('name')), 'records': records, 'warnings': warnings,
                                  'fingerprint': fingerprint, 'choices': [{'id': d['id'], 'name': d['name']} for d in local]}
    token = secrets.token_urlsafe(32)
    conn.execute('DELETE FROM unifi_previews WHERE expires<?', (time.time(),))
    conn.execute('INSERT INTO unifi_previews VALUES (?,?,?,?)', (token, conn.user['id'], time.time()+1800, json.dumps(data)))
    return data | {'token': token}

class Decision(BaseModel):
    kind: Literal['devices', 'clients']
    id: str = Field(max_length=128)
    action: Literal['skip', 'create', 'match']
    device_id: int | None = None

class Import(BaseModel):
    token: str = Field(max_length=200)
    decisions: list[Decision] = Field(max_length=10000)
    import_networks: bool = True
    import_uplinks: bool = False

def fill_device(conn, did, record, new, provider='UniFi'):
    """Fill blanks only. Conflicting observations remain in the source snapshot."""
    d = conn.execute('SELECT * FROM devices WHERE id=?', (did,)).fetchone()
    conn.execute("UPDATE devices SET model=COALESCE(NULLIF(model,''),?),mac_address=COALESCE(NULLIF(mac_address,''),?) WHERE id=?", (record['model'] or None, record['mac'] or None, did))
    interfaces = list(conn.execute('SELECT * FROM network_interfaces WHERE device_id=?', (did,)))
    matching = [i for i in interfaces if record['mac'] and mac(i['mac_address']) == record['mac']]
    iid = matching[0]['id'] if len(matching) == 1 else None
    if not interfaces and (record['mac'] or record['addresses']):
        # Don't attach a new MAC to conflicting legacy documentation.
        if new or (not d['mac_address'] or mac(d['mac_address']) == record['mac']):
            iid = conn.execute('INSERT INTO network_interfaces(device_id,name,mac_address,notes) VALUES (?,?,?,?)', (did, provider+' reported interface', record['mac'] or None, 'Reported by '+provider+'; management/client address, not a confirmed physical port.')).lastrowid
    if iid and not conn.execute('SELECT 1 FROM network_addresses WHERE interface_id=?', (iid,)).fetchone() and not conn.execute('SELECT 1 FROM interface_vlans WHERE interface_id=?', (iid,)).fetchone():
        for a in record['addresses']:
            if d['ip_address'] and d['ip_address'] != a['address']:
                continue
            primary = not conn.execute('SELECT 1 FROM network_addresses a JOIN network_interfaces i ON i.id=a.interface_id WHERE i.device_id=? AND a.is_primary=1', (did,)).fetchone()
            conn.execute('INSERT INTO network_addresses(interface_id,address,version,prefix_length,is_primary) VALUES (?,?,?,?,?)', (iid, a['address'], a['version'], a['prefix'], int(primary)))
            conn.execute("UPDATE devices SET ip_address=COALESCE(NULLIF(ip_address,''),?),ipv6_enabled=CASE WHEN ?=6 THEN 1 ELSE ipv6_enabled END WHERE id=?", (a['address'], a['version'], did))
    # Port inventory is safe on new devices only; don't guess correspondence to manual ports.
    if new:
        for p in record['ports']:
            conn.execute('INSERT INTO network_interfaces(device_id,name,port_group,port_order,connector,notes) VALUES (?,?,?,?,?,?)',
                         (did, 'Port '+str(p['idx']), 'UniFi ports', p['idx'], p['connector'], f"UniFi snapshot: maximum {p['max_speed']} Mbps; observed {p['speed']} Mbps; state {p['state']}. Supported negotiation speeds and VLAN membership not reported."))

@router.post('/import')
def import_site(payload: Import, conn=Depends(db_dependency)):
    admin(conn)
    # The request-scoped connection already owns a transaction.
    saved = conn.execute('SELECT * FROM unifi_previews WHERE token=? AND actor_id=? AND expires>?', (payload.token, conn.user['id'], time.time())).fetchone()
    if not saved:
        raise HTTPException(409, 'Preview expired or already imported; build a new preview')
    data = json.loads(saved['data']); cid = data['clinic_id']; location = data['location_id']
    if data.get('generation') != get_setting(conn, 'unifi_generation') or not get_setting(conn, 'unifi_api_key'):
        raise HTTPException(409, 'UniFi credentials changed; build a new preview')
    target(conn, cid, location); check_link(conn, data['host_id'], data['site_id'], cid, location)
    local, fingerprint = local_state(conn, cid, location)
    if fingerprint != data['fingerprint']:
        raise HTTPException(409, 'Local topology changed since preview. Build a new preview to protect those edits.')
    records = {(r['kind'], r['id']): r for r in data['records'] if r['kind'] in ('devices', 'clients')}
    decisions = {(d.kind, d.id): d for d in payload.decisions}
    if len(decisions) != len(payload.decisions) or set(decisions) != set(records):
        raise HTTPException(422, 'Review every device exactly once')
    counts = {'created': 0, 'matched': 0, 'skipped': 0, 'vlans_added': 0, 'uplinks_added': 0}
    selected = {}; warnings = list(data['warnings'])
    for key, r in records.items():
        choice = decisions[key]
        old = conn.execute('SELECT local_id FROM unifi_records WHERE host_id=? AND site_id=? AND kind=? AND external_id=?', (data['host_id'], data['site_id'], *key)).fetchone()
        if choice.action == 'skip':
            counts['skipped'] += 1; continue
        if old and old['local_id'] is not None and (choice.action != 'match' or choice.device_id != old['local_id']):
            raise HTTPException(409, 'Existing source links cannot be reassigned or duplicated during import')
        if choice.action == 'match':
            if not any(d['id'] == choice.device_id for d in local):
                raise HTTPException(422, 'Matched device must belong to the selected clinic/site')
            did = choice.device_id; counts['matched'] += 1
        else:
            if r['proposal']['action'] == 'match':
                raise HTTPException(409, 'An exact match already exists; match or skip to avoid duplicates')
            did = conn.execute('INSERT INTO devices(clinic_id,location_id,name,device_type,manufacturer,notes) VALUES (?,?,?,?,?,?)',
                               (cid, location, r['name'], r['device_type'], 'Ubiquiti' if r['kind'] == 'devices' else None, 'Imported from UniFi. Review device type; source observations are available in the clinic UniFi panel.')).lastrowid
            counts['created'] += 1
        fill_device(conn, did, r, choice.action == 'create')
        selected[key] = did
    if payload.import_uplinks:
        for key, did in selected.items():
            r = records[key]; up = selected.get(('devices', r['uplink']))
            current = conn.execute('SELECT * FROM devices WHERE id=?', (did,)).fetchone()
            if not up or up == did or current['uplink_id'] or current['device_type'] == 'vm' or conn.execute('SELECT id FROM device_links WHERE device_id=? LIMIT 1', (did,)).fetchone():
                continue
            # Infrastructure uplinks may be wireless mesh: leave media unknown.
            pending = [up]; seen = set(); cycle = False
            while pending:
                cursor = pending.pop()
                if cursor == did:
                    cycle = True; break
                if cursor in seen:
                    continue
                seen.add(cursor)
                parent = conn.execute('SELECT uplink_id FROM devices WHERE id=?', (cursor,)).fetchone()
                if parent and parent['uplink_id']:
                    pending.append(parent['uplink_id'])
                pending.extend(r['uplink_id'] for r in conn.execute('SELECT uplink_id FROM device_links WHERE device_id=?', (cursor,)))
            if cycle:
                warnings.append(r['name']+': uplink would form a cycle; skipped'); continue
            media = {'WIRED': 'ethernet', 'WIRELESS': 'wireless'}.get(r['connection_type'])
            conn.execute('UPDATE devices SET uplink_id=?,link_type=? WHERE id=?', (up, media, did))
            counts['uplinks_added'] += 1
    for r in data['records']:
        key = (r['kind'], r['id']); local_id = selected.get(key)
        if r['kind'] == 'networks' and payload.import_networks and r['tag']:
            existing = conn.execute('SELECT id FROM vlans WHERE clinic_id=? AND location_id IS ? AND tag=?', (cid, location, r['tag'])).fetchone()
            if existing:
                local_id = existing['id']
            else:
                local_id = conn.execute('INSERT INTO vlans(clinic_id,location_id,tag,name,subnets,notes) VALUES (?,?,?,?,?,?)', (cid, location, r['tag'], r['name'] or 'UniFi VLAN', json.dumps(r['subnets']), 'Imported from UniFi; review controller and interface membership.')).lastrowid
                counts['vlans_added'] += 1
        # Skips still refresh the observation, but never discard an existing source identity.
        conn.execute('''INSERT INTO unifi_records(host_id,site_id,kind,external_id,clinic_id,local_id,data) VALUES (?,?,?,?,?,?,?)
                        ON CONFLICT(host_id,site_id,kind,external_id) DO UPDATE SET data=excluded.data,
                        local_id=CASE WHEN excluded.kind='networks' THEN COALESCE(excluded.local_id,unifi_records.local_id) ELSE COALESCE(unifi_records.local_id,excluded.local_id) END,
                        updated_at=CURRENT_TIMESTAMP''',
                     (data['host_id'], data['site_id'], r['kind'], r['id'], cid, local_id, json.dumps(r)))
    conn.execute('INSERT INTO unifi_sites(host_id,site_id,clinic_id,location_id,name,warnings) VALUES (?,?,?,?,?,?) ON CONFLICT(host_id,site_id) DO UPDATE SET warnings=excluded.warnings,updated_at=CURRENT_TIMESTAMP', (data['host_id'], data['site_id'], cid, location, data['site_name'], json.dumps(warnings)))
    conn.execute('DELETE FROM unifi_previews WHERE token=?', (payload.token,))
    from ..integration_sync import discover
    discover(conn)
    return counts | {'clinic_id': cid, 'warnings': warnings}

@router.get('/clinics/{cid}')
def clinic_records(cid: int, conn=Depends(db_dependency)):
    target(conn, cid, None)
    return {'sites': [dict(r) for r in conn.execute('SELECT * FROM unifi_sites WHERE clinic_id=?', (cid,))],
            'records': [{'data': json.loads(r['data']), 'local_id': r['local_id'], 'updated_at': r['updated_at'], 'host_id': r['host_id'], 'site_id': r['site_id']} for r in conn.execute('SELECT * FROM unifi_records WHERE clinic_id=?', (cid,))]}
