"""SQLite database access for Area Book Planner.

Uses the standard-library sqlite3 module so the Docker image needs no native
build tooling. The database file lives at DATABASE_PATH (default: ./data/areabook.db).
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DATABASE_PATH = os.environ.get("DATABASE_PATH", "./data/areabook.db")
ATTACHMENTS_DIR = os.environ.get("ATTACHMENTS_DIR") or str(Path(DATABASE_PATH).parent / "attachments")

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS clinics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    address         TEXT,
    city            TEXT DEFAULT 'Calgary',
    province        TEXT DEFAULT 'AB',
    postal_code     TEXT,
    phone           TEXT,
    fax             TEXT,
    email           TEXT,
    website         TEXT,
    lat             REAL,
    lng             REAL,
    relationship    TEXT NOT NULL DEFAULT 'prospect'
                    CHECK (relationship IN ('current_client','interested','prospect','do_not_contact')),
    clinic_type     TEXT,
    emr_system      TEXT,
    it_provider     TEXT,
    provider_count  INTEGER,
    priority        TEXT DEFAULT 'medium' CHECK (priority IN ('high','medium','low')),
    tags            TEXT,
    notes           TEXT,
    next_follow_up  TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS contacts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id   INTEGER REFERENCES clinics(id) ON DELETE SET NULL,
    first_name  TEXT NOT NULL,
    last_name   TEXT,
    role        TEXT NOT NULL DEFAULT 'staff'
                CHECK (role IN ('manager','doctor','nurse','receptionist','staff','owner','it','other')),
    title       TEXT,
    phone       TEXT,
    mobile      TEXT,
    email       TEXT,
    is_primary  INTEGER NOT NULL DEFAULT 0,
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS appointments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id   INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    contact_id  INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    title       TEXT NOT NULL,
    appt_type   TEXT NOT NULL DEFAULT 'visit'
                CHECK (appt_type IN ('visit','call','demo','install','support','other')),
    status      TEXT NOT NULL DEFAULT 'scheduled'
                CHECK (status IN ('scheduled','completed','cancelled','no_show')),
    start_time  TEXT NOT NULL,
    end_time    TEXT,
    location    TEXT,
    notes       TEXT,
    outcome     TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS clinic_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id   INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    body        TEXT NOT NULL,
    author      TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id   INTEGER REFERENCES clinics(id) ON DELETE CASCADE,
    contact_id  INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    title       TEXT NOT NULL,
    notes       TEXT,
    due_date    TEXT,
    priority    TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('high','medium','low')),
    done        INTEGER NOT NULL DEFAULT 0,
    done_at     TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS clinic_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id   INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,
    title       TEXT NOT NULL,
    detail      TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS clinic_groups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS clinic_locations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id   INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    address     TEXT,
    city        TEXT DEFAULT 'Calgary',
    province    TEXT DEFAULT 'AB',
    postal_code TEXT,
    phone       TEXT,
    lat         REAL,
    lng         REAL,
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS clinic_links (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id        INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    other_clinic_id  INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    link_type        TEXT NOT NULL DEFAULT 'other',
    notes            TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS attachments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id    INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    filename     TEXT NOT NULL,
    stored_name  TEXT NOT NULL,
    content_type TEXT,
    size         INTEGER NOT NULL DEFAULT 0,
    kind         TEXT NOT NULL DEFAULT 'document',
    caption      TEXT,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS email_templates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    subject     TEXT NOT NULL,
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS devices (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id      INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    location_id    INTEGER REFERENCES clinic_locations(id) ON DELETE SET NULL,
    device_type    TEXT NOT NULL,
    name           TEXT NOT NULL,
    number         INTEGER,
    designation    TEXT,
    manufacturer   TEXT,
    model          TEXT,
    serial         TEXT,
    ip_address     TEXT,
    mac_address    TEXT,
    os             TEXT,
    user_name      TEXT,
    uplink_id      INTEGER REFERENCES devices(id) ON DELETE SET NULL,
    link_type      TEXT CHECK (link_type IN ('ethernet','wireless') OR link_type IS NULL),
    status         TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','spare','retired')),
    services       TEXT,
    purchase_date  TEXT,
    warranty_until TEXT,
    notes          TEXT,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS device_links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id   INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    uplink_id   INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    link_type   TEXT,
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS device_tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id   INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    url         TEXT,
    ticket_date TEXT,
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_devices_clinic ON devices(clinic_id);
CREATE INDEX IF NOT EXISTS idx_devices_uplink ON devices(uplink_id);
CREATE INDEX IF NOT EXISTS idx_tickets_device ON device_tickets(device_id);
CREATE INDEX IF NOT EXISTS idx_dlinks_device ON device_links(device_id);
CREATE INDEX IF NOT EXISTS idx_dlinks_uplink ON device_links(uplink_id);

CREATE TABLE IF NOT EXISTS price_book (
    key         TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    category    TEXT NOT NULL,
    unit        TEXT NOT NULL,
    alt_unit    TEXT,
    mode_group  TEXT,
    price       REAL,
    alt_price   REAL,
    description TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 1,
    custom      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS quotes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id        INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    title            TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','sent','accepted','declined','expired')),
    pricing_mode     TEXT NOT NULL DEFAULT 'per_device' CHECK (pricing_mode IN ('per_device','per_user')),
    emr_mode         TEXT NOT NULL DEFAULT 'flat' CHECK (emr_mode IN ('flat','per_user')),
    plan_key         TEXT,
    user_count       INTEGER NOT NULL DEFAULT 0,
    device_count     INTEGER NOT NULL DEFAULT 0,
    counts           TEXT,
    lines            TEXT NOT NULL,
    discount_pct     REAL NOT NULL DEFAULT 0,
    tax_pct          REAL NOT NULL DEFAULT 0,
    monthly_subtotal REAL NOT NULL DEFAULT 0,
    monthly_total    REAL NOT NULL DEFAULT 0,
    onetime_subtotal REAL NOT NULL DEFAULT 0,
    onetime_total    REAL NOT NULL DEFAULT 0,
    notes            TEXT,
    terms            TEXT,
    prepared_by      TEXT,
    contact_id       INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    valid_until      TEXT,
    sent_at          TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_quotes_clinic ON quotes(clinic_id);

CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT
);

CREATE TABLE IF NOT EXISTS saved_views (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    page        TEXT NOT NULL DEFAULT 'map',
    state       TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS inventory_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    sku           TEXT,
    category      TEXT,
    description   TEXT,
    location      TEXT,
    unit_price    REAL,                              -- what we charge the client
    cost          REAL,                              -- what it costs us
    quantity      INTEGER NOT NULL DEFAULT 0,        -- on hand
    reorder_level INTEGER,                           -- low-stock threshold
    supplier      TEXT,
    notes         TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id       INTEGER REFERENCES inventory_items(id) ON DELETE SET NULL,
    clinic_id     INTEGER REFERENCES clinics(id) ON DELETE SET NULL,
    name          TEXT NOT NULL,
    sku           TEXT,
    supplier      TEXT,
    quantity      INTEGER NOT NULL DEFAULT 1,
    unit_cost     REAL,
    unit_price    REAL,
    status        TEXT NOT NULL DEFAULT 'ordered' CHECK (status IN ('ordered','received','cancelled')),
    disposition   TEXT,                              -- how a received order was handled: inventory | invoiced
    ordered_date  TEXT,
    expected_date TEXT,
    received_date TEXT,
    ticket_url    TEXT,
    notes         TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS invoices (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id     INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    contact_id    INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    title         TEXT,
    status        TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','sent','paid','void')),
    issue_date    TEXT,
    due_date      TEXT,
    ticket_url    TEXT,
    notes         TEXT,
    tax_pct       REAL NOT NULL DEFAULT 0,
    discount_pct  REAL NOT NULL DEFAULT 0,
    subtotal      REAL NOT NULL DEFAULT 0,
    tax           REAL NOT NULL DEFAULT 0,
    total         REAL NOT NULL DEFAULT 0,
    stock_applied INTEGER NOT NULL DEFAULT 0,        -- has inventory been deducted for this invoice?
    sent_at       TEXT,
    paid_at       TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS invoice_lines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id  INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    item_id     INTEGER REFERENCES inventory_items(id) ON DELETE SET NULL,
    description TEXT NOT NULL,
    quantity    REAL NOT NULL DEFAULT 1,
    unit_price  REAL NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS device_services (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id     INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    description   TEXT,
    ip_addresses  TEXT,
    ports         TEXT,
    internal_url  TEXT,
    public_url    TEXT,
    support_url   TEXT,
    support_email TEXT,
    notes         TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS clinic_tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id   INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    device_id   INTEGER REFERENCES devices(id) ON DELETE SET NULL,   -- machine the ticket is about
    title       TEXT NOT NULL,
    url         TEXT,                                                -- link to the ticket (e.g. SyncroMSP)
    ticket_at   TEXT,                                                -- when the ticket was raised
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- Reusable external/custom VPN endpoints (e.g. AHS). Shared with every clinic unless
-- private_clinic_id is set, in which case only that clinic can use it.
CREATE TABLE IF NOT EXISTS vpn_endpoints (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,
    description       TEXT,
    address           TEXT,
    display_address   TEXT,
    lat               REAL,
    lng               REAL,
    vendor            TEXT,
    support_info      TEXT,
    private_clinic_id INTEGER REFERENCES clinics(id) ON DELETE CASCADE,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- A VPN link is one canonical, two-sided record. Side A is always a clinic site (the side
-- it was created from). Side B is either another clinic site (b_kind='site') or a custom
-- endpoint (b_kind='endpoint'). A location_id of NULL means that side's Main Site.
CREATE TABLE IF NOT EXISTS vpn_links (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT,
    vpn_type       TEXT,
    status         TEXT NOT NULL DEFAULT 'unknown'
                   CHECK (status IN ('unknown','up','down','disabled')),
    notes          TEXT,
    a_clinic_id    INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    a_location_id  INTEGER REFERENCES clinic_locations(id) ON DELETE SET NULL,
    a_device_id    INTEGER REFERENCES devices(id) ON DELETE SET NULL,
    b_kind         TEXT NOT NULL DEFAULT 'site' CHECK (b_kind IN ('site','endpoint')),
    b_clinic_id    INTEGER REFERENCES clinics(id) ON DELETE CASCADE,
    b_location_id  INTEGER REFERENCES clinic_locations(id) ON DELETE SET NULL,
    b_device_id    INTEGER REFERENCES devices(id) ON DELETE SET NULL,
    b_endpoint_id  INTEGER REFERENCES vpn_endpoints(id) ON DELETE CASCADE,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- Onward-access ("transit") routes: an explicit, directional statement that traffic from a
-- source site may continue through an intermediate ("via") site to a destination site, using
-- two documented VPN links. Two hops only; never inferred, always chosen by the user.
CREATE TABLE IF NOT EXISTS vpn_transit_routes (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    source_clinic_id   INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    source_location_id INTEGER REFERENCES clinic_locations(id) ON DELETE SET NULL,
    entry_vpn_link_id  INTEGER NOT NULL REFERENCES vpn_links(id) ON DELETE CASCADE,
    via_clinic_id      INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    via_location_id    INTEGER REFERENCES clinic_locations(id) ON DELETE SET NULL,
    exit_vpn_link_id   INTEGER NOT NULL REFERENCES vpn_links(id) ON DELETE CASCADE,
    dest_clinic_id     INTEGER NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    dest_location_id   INTEGER REFERENCES clinic_locations(id) ON DELETE SET NULL,
    rationale          TEXT,
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_vpn_links_a ON vpn_links(a_clinic_id);
CREATE INDEX IF NOT EXISTS idx_vpn_links_b ON vpn_links(b_clinic_id);
CREATE INDEX IF NOT EXISTS idx_vpn_endpoints_private ON vpn_endpoints(private_clinic_id);
CREATE INDEX IF NOT EXISTS idx_transit_source ON vpn_transit_routes(source_clinic_id);
CREATE INDEX IF NOT EXISTS idx_transit_entry ON vpn_transit_routes(entry_vpn_link_id);
CREATE INDEX IF NOT EXISTS idx_locations_clinic ON clinic_locations(clinic_id);
CREATE INDEX IF NOT EXISTS idx_links_clinic ON clinic_links(clinic_id);
CREATE INDEX IF NOT EXISTS idx_links_other ON clinic_links(other_clinic_id);
CREATE INDEX IF NOT EXISTS idx_attachments_clinic ON attachments(clinic_id);
CREATE INDEX IF NOT EXISTS idx_tasks_clinic ON tasks(clinic_id);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_events_clinic ON clinic_events(clinic_id);
CREATE INDEX IF NOT EXISTS idx_contacts_clinic ON contacts(clinic_id);
CREATE INDEX IF NOT EXISTS idx_appointments_clinic ON appointments(clinic_id);
CREATE INDEX IF NOT EXISTS idx_appointments_start ON appointments(start_time);
CREATE INDEX IF NOT EXISTS idx_notes_clinic ON clinic_notes(clinic_id);
CREATE INDEX IF NOT EXISTS idx_invoices_clinic2 ON invoices(clinic_id);
CREATE INDEX IF NOT EXISTS idx_invoice_lines_invoice ON invoice_lines(invoice_id);
CREATE INDEX IF NOT EXISTS idx_orders_item ON orders(item_id);
CREATE INDEX IF NOT EXISTS idx_orders_clinic ON orders(clinic_id);
CREATE INDEX IF NOT EXISTS idx_clinic_tickets_clinic ON clinic_tickets(clinic_id);
CREATE INDEX IF NOT EXISTS idx_device_services_device ON device_services(device_id);
"""


def _connect() -> sqlite3.Connection:
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Columns added after the first release. Applied with ALTER TABLE on existing databases.
MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "clinics": [
        ("stage", "TEXT NOT NULL DEFAULT 'prospect'"),
        ("deal_value", "REAL"),
        ("expected_close", "TEXT"),
        ("win_probability", "INTEGER"),
        ("outcome_reason", "TEXT"),
        ("outcome_notes", "TEXT"),
        ("outcome_date", "TEXT"),
        ("shorthand", "TEXT"),
        ("archived", "INTEGER NOT NULL DEFAULT 0"),
        ("archived_at", "TEXT"),
        ("group_id", "INTEGER REFERENCES clinic_groups(id) ON DELETE SET NULL"),
        # Address shown on the clinic page (may differ from the geocoding address, e.g. a unit #).
        ("display_address", "TEXT"),
        # Opening hours, stored as a JSON object keyed by weekday.
        ("hours", "TEXT"),
        # Client lifecycle & recurring revenue
        ("mrr", "REAL"),
        ("contract_start", "TEXT"),
        ("contract_end", "TEXT"),
        ("contract_term_months", "INTEGER"),
        ("auto_renew", "INTEGER NOT NULL DEFAULT 0"),
        ("renewal_reminder_days", "INTEGER"),
        ("churned_at", "TEXT"),
        # Competitor / displacement intelligence
        ("competitor_contract_end", "TEXT"),
    ],
    "contacts": [
        ("extension", "TEXT"),
        ("use_main_line", "INTEGER NOT NULL DEFAULT 0"),
        ("group_id", "INTEGER REFERENCES clinic_groups(id) ON DELETE SET NULL"),
    ],
    "appointments": [
        ("reminder_minutes", "INTEGER"),
        ("rep", "TEXT"),
    ],
    "devices": [
        ("off_site", "INTEGER NOT NULL DEFAULT 0"),
        ("rack", "TEXT"),
        ("rack_room", "TEXT"),
        ("rack_position", "INTEGER"),
        ("rack_units", "INTEGER"),
        ("shelf_id", "INTEGER REFERENCES devices(id) ON DELETE SET NULL"),
    ],
    "tasks": [
        ("due_time", "TEXT"),
        ("reminder_minutes", "INTEGER"),
        ("rep", "TEXT"),
    ],
    "clinic_notes": [
        ("kind", "TEXT NOT NULL DEFAULT 'note'"),
        # A note can be about an appointment, a task, or a photo (attachment). All null = clinic-level.
        ("appointment_id", "INTEGER REFERENCES appointments(id) ON DELETE SET NULL"),
        ("task_id", "INTEGER REFERENCES tasks(id) ON DELETE SET NULL"),
        ("attachment_id", "INTEGER REFERENCES attachments(id) ON DELETE CASCADE"),
        ("service_id", "INTEGER REFERENCES device_services(id) ON DELETE CASCADE"),
    ],
    "attachments": [
        # The note a photo was uploaded with (so it links back to that note's context).
        ("note_id", "INTEGER REFERENCES clinic_notes(id) ON DELETE SET NULL"),
        ("service_id", "INTEGER REFERENCES device_services(id) ON DELETE CASCADE"),
    ],
    "clinic_events": [
        ("from_value", "TEXT"),
        ("to_value", "TEXT"),
    ],
    "clinic_locations": [
        # Address shown in the UI for a secondary site (may differ from the geocoding address).
        ("display_address", "TEXT"),
    ],
}

DEFAULT_EMAIL_TEMPLATES = [
    (
        "Introduction",
        "ChinookIT - IT support for {clinic_name}",
        "Hi {contact_first_name},\n\nThanks for taking the time to chat today. ChinookIT looks after IT for medical "
        "clinics across Calgary - networks, backups, EMR support and fast on-site response.\n\n"
        "I'd love to set up a short visit to see how things are set up at {clinic_name} and where we could help.\n\n"
        "Best regards,\n{rep_name}\nChinookIT",
    ),
    (
        "Quote follow-up",
        "Following up on our quote for {clinic_name}",
        "Hi {contact_first_name},\n\nJust checking in on the quote I sent over for {clinic_name}. Happy to walk through "
        "any questions or adjust the scope if it would help.\n\nWould a quick call this week work?\n\n"
        "Thanks,\n{rep_name}\nChinookIT",
    ),
    (
        "Thanks for the visit",
        "Great to meet you at {clinic_name}",
        "Hi {contact_first_name},\n\nThanks for showing me around {clinic_name} today. I'll put together the "
        "information we discussed and send it over shortly.\n\nBest,\n{rep_name}\nChinookIT",
    ),
]


def _apply_migrations(conn: sqlite3.Connection) -> None:
    for table, columns in MIGRATIONS.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, ddl in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    # Keep the pipeline consistent with the relationship for pre-existing rows.
    conn.execute("UPDATE clinics SET stage = 'won' WHERE relationship = 'current_client' AND stage <> 'won'")
    # The "Contacted" stage was removed; fold any existing rows up into "Interested".
    conn.execute("UPDATE clinics SET stage = 'prospect' WHERE stage = 'contacted'")
    # Migrate legacy free-text device services (a JSON array of names) into structured
    # device_services rows, then clear the text column so it isn't migrated twice.
    import json as _json
    for row in conn.execute("SELECT id, services FROM devices WHERE services IS NOT NULL AND services <> ''").fetchall():
        try:
            names = _json.loads(row[1])
        except (ValueError, TypeError):
            names = []
        for name in names:
            name = str(name).strip()
            if name:
                conn.execute("INSERT INTO device_services (device_id, name) VALUES (?, ?)", (row[0], name))
        conn.execute("UPDATE devices SET services = NULL WHERE id = ?", (row[0],))
    if conn.execute("SELECT COUNT(*) FROM email_templates").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO email_templates (name, subject, body) VALUES (?, ?, ?)", DEFAULT_EMAIL_TEMPLATES
        )
    # Price book: insert any built-in items that are missing (prices stay as the user set them).
    from .logic import PRICE_BOOK_DEFAULTS

    existing = {r[0] for r in conn.execute("SELECT key FROM price_book")}
    for i, item in enumerate(PRICE_BOOK_DEFAULTS):
        if item["key"] not in existing:
            conn.execute(
                "INSERT INTO price_book (key, label, category, unit, alt_unit, mode_group, description, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (item["key"], item["label"], item["category"], item["unit"], item.get("alt_unit"), item.get("mode_group"), item.get("description"), i * 10),
            )


def init_db() -> None:
    conn = _connect()
    try:
        conn.executescript(SCHEMA)
        _apply_migrations(conn)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def db_dependency() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency yielding a connection per request."""
    with get_db() as conn:
        yield conn


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def rows_to_list(rows) -> list[dict]:
    return [dict(r) for r in rows]
