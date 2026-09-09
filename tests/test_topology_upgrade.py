"""Upgrade a populated legacy-shaped database, then repeat startup migrations."""
from app import database


def test_topology_upgrade_preserves_existing_records(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DATABASE_PATH', str(tmp_path / 'upgrade.db'))
    with database.get_db() as conn:
        conn.executescript(database.SCHEMA)
        database._apply_migrations(conn)
        conn.execute("INSERT INTO clinics(id,name) VALUES (1,'Upgrade fixture')")
        conn.execute("INSERT INTO devices(id,clinic_id,device_type,name,ip_address) VALUES (1,1,'server','Existing server','192.0.2.8')")
        conn.execute("INSERT INTO device_tickets(device_id,title) VALUES (1,'Existing device ticket')")
        conn.execute("INSERT INTO clinic_tickets(clinic_id,device_id,title) VALUES (1,1,'Existing support ticket')")
        conn.execute("INSERT INTO tasks(clinic_id,title) VALUES (1,'Existing task')")
        assert 'device_id' not in {r[1] for r in conn.execute('PRAGMA table_info(tasks)')}
    database.init_db()
    database.init_db()
    with database.get_db() as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
        assert conn.execute('SELECT status FROM device_tickets').fetchone()[0] == 'unknown'
        assert conn.execute('SELECT status FROM clinic_tickets').fetchone()[0] == 'unknown'
        assert conn.execute('SELECT device_id FROM tasks').fetchone()[0] is None
        assert conn.execute('SELECT ipv6_enabled FROM devices').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM network_interfaces WHERE device_id=1').fetchone()[0] == 1
        assert conn.execute('SELECT address FROM network_addresses').fetchone()[0] == '192.0.2.8'
        assert conn.execute('SELECT title FROM tasks').fetchone()[0] == 'Existing task'
