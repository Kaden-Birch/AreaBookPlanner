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

CREATE INDEX IF NOT EXISTS idx_contacts_clinic ON contacts(clinic_id);
CREATE INDEX IF NOT EXISTS idx_appointments_clinic ON appointments(clinic_id);
CREATE INDEX IF NOT EXISTS idx_appointments_start ON appointments(start_time);
CREATE INDEX IF NOT EXISTS idx_notes_clinic ON clinic_notes(clinic_id);
"""


def _connect() -> sqlite3.Connection:
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = _connect()
    try:
        conn.executescript(SCHEMA)
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
