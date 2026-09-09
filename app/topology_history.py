"""Local topology versions and transactional web-edit audit records."""
import json

SCHEMA = """
CREATE TABLE IF NOT EXISTS topology_groups (
 id INTEGER PRIMARY KEY, clinic_id INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
 location_id INTEGER REFERENCES clinic_locations(id) ON DELETE CASCADE,
 name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', color TEXT NOT NULL DEFAULT '#547ee8',
 device_ids TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS topology_versions (
 id INTEGER PRIMARY KEY, clinic_id INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
 site TEXT NOT NULL, label TEXT NOT NULL, actor TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, document TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS topology_audit (
 id INTEGER PRIMARY KEY, clinic_id INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
 actor TEXT NOT NULL, request_path TEXT NOT NULL, method TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, changes TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_topology_versions_clinic ON topology_versions(clinic_id,id);
CREATE INDEX IF NOT EXISTS idx_topology_audit_clinic ON topology_audit(clinic_id,id);
"""

# Historical records with VPN references require every referenced clinic to
# remain authorized; access.py enforces that when reading versions and audits.
QUERIES = {
 'device_tickets': "SELECT t.*,d.location_id FROM device_tickets t JOIN devices d ON d.id=t.device_id WHERE d.clinic_id=?",
 'support_tickets': "SELECT t.*,d.location_id FROM clinic_tickets t JOIN devices d ON d.id=t.device_id WHERE d.clinic_id=?",
 'device_tasks': "SELECT t.*,d.location_id FROM tasks t JOIN devices d ON d.id=t.device_id WHERE d.clinic_id=? AND t.visibility='technical'",
 'groups': "SELECT g.* FROM topology_groups g WHERE g.clinic_id=?",
 'devices': "SELECT d.* FROM devices d WHERE d.clinic_id=?",
 'vlans': "SELECT v.* FROM vlans v WHERE v.clinic_id=?",
 'interfaces': "SELECT i.*,d.location_id FROM network_interfaces i JOIN devices d ON d.id=i.device_id WHERE d.clinic_id=?",
 'addresses': "SELECT a.*,d.location_id FROM network_addresses a JOIN network_interfaces i ON i.id=a.interface_id JOIN devices d ON d.id=i.device_id WHERE d.clinic_id=?",
 'memberships': "SELECT m.*,d.location_id FROM interface_vlans m JOIN network_interfaces i ON i.id=m.interface_id JOIN devices d ON d.id=i.device_id WHERE d.clinic_id=?",
 'links': "SELECT l.*,d.location_id FROM device_links l JOIN devices d ON d.id=l.device_id WHERE d.clinic_id=?",
 'connections': "SELECT c.*,d.location_id FROM connection_details c JOIN devices d ON d.id=c.device_id WHERE d.clinic_id=?",
 'connection_vlans': "SELECT v.*,d.location_id FROM connection_vlans v JOIN connection_details c ON c.id=v.connection_id JOIN devices d ON d.id=c.device_id WHERE d.clinic_id=?",
 'services': "SELECT s.*,d.location_id FROM device_services s JOIN devices d ON d.id=s.device_id WHERE d.clinic_id=?",
 'sites': "SELECT l.*,l.id AS location_id FROM clinic_locations l WHERE l.clinic_id=?",
 'network_ranges': "SELECT r.* FROM site_network_ranges r WHERE r.clinic_id=?",
 'vpn_links': "SELECT v.* FROM vpn_links v WHERE v.a_clinic_id=? OR v.b_clinic_id=?",
 'vpn_transit': "SELECT r.*,r.source_location_id AS location_id FROM vpn_transit_routes r WHERE r.source_clinic_id=?",
}

def document(conn,cid,site='all'):
    out={}
    for key,sql in QUERIES.items():
        rows=[dict(r) for r in conn.execute(sql,(cid,cid) if key=='vpn_links' else (cid,))]
        if key=='vpn_links':
            for r in rows:
                r['local_sites']=[r[side+'_location_id'] for side in ('a','b') if r[side+'_clinic_id']==cid]
                r['location_id']=r['local_sites'][0]
        if site!='all':
            loc=None if site=='main' else int(site)
            rows=[r for r in rows if loc in r.get('local_sites',[r.get('location_id')])]
        out[key]=sorted(rows,key=lambda r:r['id'])
    return out

def dependencies(doc):
    ids=set()
    for rows in doc.values():
        for row in rows:
            for key in ('clinic_id','a_clinic_id','b_clinic_id','source_clinic_id','via_clinic_id','dest_clinic_id'):
                if row.get(key) is not None:ids.add(row[key])
    return sorted(ids)

def initialize(conn):
    conn.executescript(SCHEMA)
    for table in ('topology_versions','topology_audit'):
        if 'required_clinics' not in {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN required_clinics TEXT NOT NULL DEFAULT '[]'")

def differences(before,after):
    changes=[]
    for table in QUERIES:
        old={r['id']:r for r in before.get(table,[])}
        new={r['id']:r for r in after.get(table,[])}
        for rid in sorted(old.keys()|new.keys()):
            a,b=old.get(rid),new.get(rid)
            fields=[k for k in sorted(set(a or {})|set(b or {}))
                    if k not in ('updated_at','created_at') and (a or {}).get(k)!=(b or {}).get(k)]
            if not fields: continue
            changes.append({'table':table,'id':rid,'action':'added' if a is None else 'removed' if b is None else 'changed',
                            'name':(b or a).get('name',str(rid)),'before_site':a.get('location_id') if a else None,
                            'after_site':b.get('location_id') if b else None,
                            'before_sites':a.get('local_sites',[a.get('location_id')]) if a else [],
                            'after_sites':b.get('local_sites',[b.get('location_id')]) if b else [],
                            'fields':{k:{'before':(a or {}).get(k),'after':(b or {}).get(k)} for k in fields}})
    return changes

def capture(conn):
    return {r['id']:document(conn,r['id']) for r in conn.execute('SELECT id FROM clinics')}

def record_changes(conn,before,user,path,method):
    for cid,after in capture(conn).items():
        changes=differences(before.get(cid,{}),after)
        if changes:
            required=sorted(set(dependencies(before.get(cid,{})))|set(dependencies(after)))
            conn.execute('INSERT INTO topology_audit(clinic_id,actor,request_path,method,changes,required_clinics) VALUES (?,?,?,?,?,?)',
                         (cid,f"{user['display_name']} ({user['username']} #{user['id']})",path,method,json.dumps(changes),json.dumps(required)))
