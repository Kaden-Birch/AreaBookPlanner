"""Central API policy and request-scoped database reads.

Read queries receive explicit, scoped CTEs for all clinic-owned tables. The CTEs
filter before joins, aggregates and LIMIT, including legacy queries. Writes use
the real tables with temporary guard triggers; they never bypass row scope.
Only trusted application SQL reaches this connection. New tables must be added
to scope_rules and new API routes must be classified in permission_for.
"""
import re
import sqlite3

from fastapi import HTTPException, Request

from .auth import session_user
from .database import _connect

BUSINESS = {"sales", "manager", "client_success"}
WORKSPACES = BUSINESS | {"it"}


def permission_for(path, method):
    read = method in ("GET", "HEAD")
    if path.endswith('/area'):
        return {'manager'}
    if path.startswith(("/api/settings", "/api/import/", "/api/export/backup", "/api/geocode/bulk", "/api/views", "/api/templates", "/api/groups")):
        # Global legacy settings/imports have no safe workspace ownership yet.
        return WORKSPACES if read and path in ("/api/templates", "/api/groups") else set()
    if re.search(r"/(devices|services|topology|racks|vpn|network-ranges|connectivity|tickets)(/|\.|$)", path) or path.endswith(("/connect", "/disconnect")):
        return {"it"}
    if "/locations" in path or path.endswith("/sites"):
        return WORKSPACES if read else {"it"}
    if "/invoices" in path or "/inventory" in path or "/orders" in path or path == "/api/meta/billing":
        return BUSINESS
    if "/quotes" in path or path.endswith("/quote-defaults") or path.startswith("/api/pricebook"):
        if path.startswith("/api/pricebook") and not read:
            return {"manager"}
        return WORKSPACES if read else {"sales", "manager"}
    if path in ("/api/revenue",):
        return BUSINESS
    if path in ("/api/analytics", "/api/competitors") or path.endswith(("/stage", "/archive")):
        return {"sales", "manager"}
    if path.startswith("/api/clinics"):
        if read:
            return WORKSPACES
        if path.endswith(("/notes", "/quick-log", "/attachments")) or "/notes/" in path:
            return WORKSPACES
        if path.endswith("/ai-draft"):
            return {"sales", "manager"}
        if method == 'PUT' and re.fullmatch(r'/api/clinics/\d+', path):
            return BUSINESS
        return {"sales", "manager"}
    if path.startswith("/api/contacts"):
        return WORKSPACES if read else BUSINESS
    if path.startswith("/api/appointments"):
        return WORKSPACES if read else BUSINESS
    if path.startswith(("/api/tasks", "/api/attachments")):
        return WORKSPACES
    if path in ("/api/meta", "/api/meta/extras", "/api/geocode", "/api/dashboard", "/api/search", "/api/reminders", "/api/locations", "/api/call-sheet", "/api/drivetime", "/api/route", "/api/health"):
        return WORKSPACES
    if path.startswith("/api/export/"):
        return BUSINESS
    return set()


def scope_rules(role, area):
    current = " AND relationship='current_client'" if role == "client_success" else ""
    clinics = f"area_id={int(area)}{current}"
    owned = "clinic_id IN (SELECT id FROM clinics)"
    visibility = "visibility IN ('general','technical')" if role == "it" else "visibility IN ('general','sales')"
    rules = {"clinics": clinics}
    for table in ("contacts", "clinic_locations", "clinic_events", "quotes", "invoices", "orders", "devices", "clinic_tickets", "site_network_ranges"):
        rules[table] = owned
    for table in ("clinic_notes", "tasks", "appointments"):
        rules[table] = f"{owned} AND {visibility}"
    # Unlinked tasks/contacts/stock orders belong explicitly to the selected Area.
    # Client Success still sees only records attached to a current client.
    if role != 'client_success':
        for table in ('tasks', 'contacts', 'orders'):
            rules[table] = f"({owned} OR (clinic_id IS NULL AND area_id={int(area)}))"
            if table == 'tasks':
                rules[table] += f' AND {visibility}'
    rules["clinic_links"] = owned + " AND other_clinic_id IN (SELECT id FROM clinics)"
    rules["clinic_groups"] = "id IN (SELECT group_id FROM clinics)"
    rules["device_services"] = "device_id IN (SELECT id FROM devices)" if role == "it" else "0"
    rules["device_links"] = "device_id IN (SELECT id FROM devices) AND uplink_id IN (SELECT id FROM devices)"
    rules["device_tickets"] = "device_id IN (SELECT id FROM devices)"
    rules["invoice_lines"] = "invoice_id IN (SELECT id FROM invoices)"
    rules["vpn_links"] = "a_clinic_id IN (SELECT id FROM clinics) AND (b_kind='endpoint' OR b_clinic_id IN (SELECT id FROM clinics))"
    rules["vpn_endpoints"] = "private_clinic_id IS NULL OR private_clinic_id IN (SELECT id FROM clinics)"
    rules["vpn_transit_routes"] = "source_clinic_id IN (SELECT id FROM clinics) AND via_clinic_id IN (SELECT id FROM clinics) AND dest_clinic_id IN (SELECT id FROM clinics)"
    rules["attachments"] = owned + " AND " + visibility + " AND (note_id IS NULL OR note_id IN (SELECT id FROM clinic_notes))"
    # Event details can embed restricted note/device or remote-clinic information.
    rules['clinic_events'] += " AND event_type NOT IN ('attachment','link','location')"
    if role != "it":
        rules["clinic_notes"] += " AND service_id IS NULL"
        rules["attachments"] += " AND service_id IS NULL"
        rules["clinic_tickets"] = "0"
    if role == "it":
        rules["invoices"] = "0"
        rules["orders"] = "0"
    return rules


class ScopedConnection:
    def __init__(self, conn, user):
        self.raw = conn
        self.user = user
        self.rules = scope_rules(user["active_role"], user["area_id"])
        self.columns = {table: [r[1] for r in conn.execute(f"PRAGMA table_info({table})")] for table in self.rules}
        ctes = []
        for table, where in self.rules.items():
            fields = list(self.columns[table])
            # Legacy summary queries may count devices, but never receive details.
            if table == "devices" and user["active_role"] != "it":
                safe = {"id", "clinic_id", "location_id", "device_type", "status", "off_site"}
                fields = [c if c in safe else f"NULL AS {c}" for c in fields]
            if table == 'clinic_locations' and user['active_role'] != 'it':
                fields = ['NULL AS notes' if c == 'notes' else c for c in fields]
            if table == 'clinics' and user['active_role'] == 'it':
                hidden = {'deal_value','expected_close','win_probability','outcome_reason','outcome_notes','mrr','contract_start','contract_end','contract_term_months','renewal_reminder_days','competitor_contract_end'}
                fields = [f'NULL AS {c}' if c in hidden else c for c in fields]
            ctes.append(f"{table} AS (SELECT {','.join(fields)} FROM main.{table} WHERE {where})")
        self.prefix = "WITH " + ",".join(ctes) + " "
        # Snapshot IDs protect legacy UPDATE/DELETE calls lacking a preceding read.
        self.allowed = {table: {r[0] for r in conn.execute(self.prefix + f"SELECT id FROM {table}")} for table in self.rules}
        conn.create_function("scope_id", 2, lambda table, rid: int(rid in self.allowed.get(table, set())))
        for table in self.rules:
            if table == "clinic_groups":
                continue
            for operation in ("UPDATE", "DELETE"):
                conn.execute(f"""CREATE TEMP TRIGGER guard_{table}_{operation} BEFORE {operation} ON main.{table}
                    WHEN NOT scope_id('{table}', OLD.id) BEGIN SELECT RAISE(ABORT,'Outside workspace scope'); END""")
            checks = []
            if table == "clinics":
                checks.append(f"NEW.area_id IS NOT {int(user['area_id'])}")
                if user["active_role"] == "client_success":
                    checks.append("NEW.relationship <> 'current_client'")
            for col, target in (("clinic_id", "clinics"), ("other_clinic_id", "clinics"), ("contact_id", "contacts"),
                                ("device_id", "devices"), ("uplink_id", "devices"), ("location_id", "clinic_locations"),
                                ("invoice_id", "invoices"), ("note_id", "clinic_notes"), ("service_id", "device_services")):
                if col in self.columns[table]:
                    checks.append(f"(NEW.{col} IS NOT NULL AND NOT scope_id('{target}',NEW.{col}))")
            for col, target in (('task_id','tasks'), ('appointment_id','appointments'), ('attachment_id','attachments'), ('private_clinic_id','clinics'), ('b_endpoint_id','vpn_endpoints'), ('a_device_id','devices'), ('b_device_id','devices'), ('a_location_id','clinic_locations'), ('b_location_id','clinic_locations')):
                if col in self.columns[table]:
                    checks.append(f"(NEW.{col} IS NOT NULL AND NOT scope_id('{target}',NEW.{col}))")
            for col in ('a_clinic_id','b_clinic_id','source_clinic_id','via_clinic_id','dest_clinic_id'):
                if col in self.columns[table]:
                    checks.append(f"(NEW.{col} IS NOT NULL AND NOT scope_id('clinics',NEW.{col}))")
            if "clinic_id" in self.columns[table]:
                if table in ('tasks','contacts','orders') and user['active_role'] != 'client_success':
                    checks.append(f"(NEW.clinic_id IS NULL AND NEW.area_id IS NOT {int(user['area_id'])})")
                else:
                    checks.append("NEW.clinic_id IS NULL")
            if "visibility" in self.columns[table]:
                allowed = "'general','technical'" if user["active_role"] == "it" else "'general','sales'"
                checks.append(f"NEW.visibility NOT IN ({allowed})")
            if checks:
                for operation in ("INSERT", "UPDATE"):
                    conn.execute(f"""CREATE TEMP TRIGGER check_{table}_{operation} BEFORE {operation} ON main.{table}
                        WHEN {' OR '.join(checks)} BEGIN SELECT RAISE(ABORT,'Outside workspace scope'); END""")

    def execute(self, sql, parameters=()):
        statement = sql.lstrip()
        if statement.upper().startswith("SELECT"):
            return self.raw.execute(self.prefix + sql, parameters)
        if not re.match(r"^(INSERT|UPDATE|DELETE)\b", statement, re.I):
            raise HTTPException(403, "Unsupported workspace operation")
        try:
            cursor = self.raw.execute(sql, parameters)
        except sqlite3.IntegrityError as exc:
            if "Outside workspace scope" in str(exc):
                raise HTTPException(403, "Record is outside your workspace") from exc
            raise
        match = re.match(r"INSERT\s+INTO\s+(\w+)", statement, re.I)
        if match and match[1] in self.allowed:
            self.allowed[match[1]].add(cursor.lastrowid)
        return cursor


def scoped_db(request: Request):
    conn = _connect()
    try:
        # Keep the scope snapshot and mutations in one transaction; an Area
        # reassignment must not race a request's initial ownership checks.
        conn.execute('BEGIN')
        user = session_user(request, conn)
        if user["must_change_password"]:
            raise HTTPException(403, "Change your password first")
        if user["active_role"] not in permission_for(request.url.path, request.method):
            raise HTTPException(403, "This action is unavailable in your workspace")
        area = conn.execute("""SELECT 1 FROM user_role_areas ua JOIN areas a ON a.id=ua.area_id
            WHERE user_id=? AND role=? AND ua.area_id=? AND a.is_active=1""", (user["id"],user["active_role"],user["area_id"])).fetchone()
        if not area:
            raise HTTPException(403, "Ask an administrator to assign an active Area")
        yield ScopedConnection(conn, user)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
