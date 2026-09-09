"""Additive network documentation schema and idempotent legacy-address conversion."""
import ipaddress

SCHEMA = """
CREATE TABLE IF NOT EXISTS network_interfaces (
 id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
 name TEXT NOT NULL, mac_address TEXT, notes TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_interfaces_device ON network_interfaces(device_id);
CREATE TABLE IF NOT EXISTS vlans (
 id INTEGER PRIMARY KEY, clinic_id INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
 location_id INTEGER REFERENCES clinic_locations(id) ON DELETE CASCADE,
 tag INTEGER NOT NULL CHECK(tag BETWEEN 1 AND 4094), name TEXT NOT NULL,
 description TEXT, subnets TEXT NOT NULL DEFAULT '[]', color TEXT NOT NULL DEFAULT '#547ee8',
 gateway_interface_id INTEGER REFERENCES network_interfaces(id) ON DELETE SET NULL,
 dhcp_mode TEXT NOT NULL DEFAULT 'unknown', notes TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_vlan_site_tag ON vlans(clinic_id,IFNULL(location_id,0),tag);
CREATE TABLE IF NOT EXISTS interface_vlans (
 id INTEGER PRIMARY KEY, interface_id INTEGER NOT NULL REFERENCES network_interfaces(id) ON DELETE CASCADE,
 vlan_id INTEGER NOT NULL REFERENCES vlans(id) ON DELETE CASCADE, mode TEXT NOT NULL,
 UNIQUE(interface_id,vlan_id)
);
CREATE TABLE IF NOT EXISTS network_addresses (
 id INTEGER PRIMARY KEY, interface_id INTEGER NOT NULL REFERENCES network_interfaces(id) ON DELETE CASCADE,
 address TEXT NOT NULL, version INTEGER NOT NULL, prefix_length INTEGER,
 vlan_id INTEGER REFERENCES vlans(id) ON DELETE SET NULL,
 kind TEXT NOT NULL DEFAULT 'static', is_primary INTEGER NOT NULL DEFAULT 0, hostname TEXT, notes TEXT,
 UNIQUE(interface_id,address)
);
CREATE INDEX IF NOT EXISTS idx_addresses_interface ON network_addresses(interface_id);
CREATE TABLE IF NOT EXISTS connection_details (
 id INTEGER PRIMARY KEY,
 device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
 uplink_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
 source_interface_id INTEGER REFERENCES network_interfaces(id) ON DELETE SET NULL,
 target_interface_id INTEGER REFERENCES network_interfaces(id) ON DELETE SET NULL,
 speed_mbps INTEGER, duplex TEXT NOT NULL DEFAULT 'unknown', media TEXT NOT NULL DEFAULT 'unknown',
 vlan_mode TEXT NOT NULL DEFAULT 'unknown', native_vlan_id INTEGER REFERENCES vlans(id) ON DELETE SET NULL,
 admin_status TEXT NOT NULL DEFAULT 'unknown', notes TEXT,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(device_id,uplink_id)
);
CREATE TABLE IF NOT EXISTS connection_vlans (
 id INTEGER PRIMARY KEY, connection_id INTEGER NOT NULL REFERENCES connection_details(id) ON DELETE CASCADE,
 vlan_id INTEGER NOT NULL REFERENCES vlans(id) ON DELETE CASCADE, UNIQUE(connection_id,vlan_id)
);
CREATE TRIGGER IF NOT EXISTS clean_primary_connection AFTER UPDATE OF uplink_id ON devices
 WHEN OLD.uplink_id IS NOT NEW.uplink_id BEGIN
 DELETE FROM connection_details WHERE device_id=OLD.id AND uplink_id=OLD.uplink_id
 AND NOT EXISTS(SELECT 1 FROM device_links WHERE device_id=OLD.id AND uplink_id=OLD.uplink_id);
END;
CREATE TRIGGER IF NOT EXISTS clean_extra_connection AFTER DELETE ON device_links BEGIN
 DELETE FROM connection_details WHERE device_id=OLD.device_id AND uplink_id=OLD.uplink_id
 AND NOT EXISTS(SELECT 1 FROM devices WHERE id=OLD.device_id AND uplink_id=OLD.uplink_id);
END;
"""

def initialize(conn):
    conn.executescript(SCHEMA)
    for table in ('device_tickets','clinic_tickets'):
        if 'status' not in {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN status TEXT NOT NULL DEFAULT 'unknown' CHECK(status IN ('unknown','open','closed'))")
    if 'device_id' not in {r[1] for r in conn.execute('PRAGMA table_info(tasks)')}:
        conn.execute('ALTER TABLE tasks ADD COLUMN device_id INTEGER REFERENCES devices(id) ON DELETE SET NULL')
    if 'ipv6_enabled' not in {r[1] for r in conn.execute('PRAGMA table_info(devices)')}:
        conn.execute('ALTER TABLE devices ADD COLUMN ipv6_enabled INTEGER NOT NULL DEFAULT 0')
    for row in conn.execute('''SELECT id,ip_address,mac_address FROM devices d
        WHERE ip_address IS NOT NULL AND trim(ip_address)<>''
        AND NOT EXISTS(SELECT 1 FROM network_interfaces i WHERE i.device_id=d.id)''').fetchall():
        try:
            raw=row[1].strip()
            value=ipaddress.ip_interface(raw)
        except ValueError:
            continue  # Preserve malformed text on the device for manual review.
        iid=conn.execute("INSERT INTO network_interfaces(device_id,name,mac_address) VALUES (?,'Primary',?)",(row[0],row[2])).lastrowid
        conn.execute('''INSERT INTO network_addresses(interface_id,address,version,prefix_length,is_primary)
            VALUES (?,?,?,?,1)''',(iid,str(value.ip),value.version,value.network.prefixlen if '/' in raw else None))
