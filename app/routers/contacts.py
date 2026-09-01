"""Contact CRUD (contacts may belong to a clinic or be unattached)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from ..database import db_dependency, row_to_dict, rows_to_list
from ..logic import now_iso
from ..schemas import ContactIn

router = APIRouter(prefix="/api/contacts", tags=["contacts"])

CONTACT_COLUMNS = [
    "clinic_id", "first_name", "last_name", "role", "title", "phone", "mobile", "email",
    "is_primary", "notes",
]

ROLE_LABELS = {
    "manager": "Clinic manager",
    "doctor": "Doctor",
    "nurse": "Nurse",
    "receptionist": "Receptionist",
    "staff": "General staff",
    "owner": "Owner",
    "it": "IT contact",
    "other": "Other",
}

SELECT = """SELECT c.*, cl.name AS clinic_name, cl.relationship AS clinic_relationship
            FROM contacts c LEFT JOIN clinics cl ON cl.id = c.clinic_id"""


def _decorate(row: dict) -> dict:
    row["role_label"] = ROLE_LABELS.get(row["role"], row["role"])
    row["full_name"] = " ".join(p for p in [row.get("first_name"), row.get("last_name")] if p)
    row["is_primary"] = bool(row["is_primary"])
    return row


def _get_or_404(conn: sqlite3.Connection, contact_id: int) -> dict:
    row = row_to_dict(conn.execute(f"{SELECT} WHERE c.id = ?", (contact_id,)).fetchone())
    if row is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    return _decorate(row)


def _check_clinic(conn: sqlite3.Connection, clinic_id: int | None) -> None:
    if clinic_id is None:
        return
    if conn.execute("SELECT 1 FROM clinics WHERE id = ?", (clinic_id,)).fetchone() is None:
        raise HTTPException(status_code=422, detail="Clinic does not exist")


@router.get("")
def list_contacts(
    q: str | None = None,
    clinic_id: int | None = None,
    role: str | None = Query(default=None),
    conn: sqlite3.Connection = Depends(db_dependency),
):
    sql = f"{SELECT} WHERE 1=1"
    params: list = []
    if q:
        like = f"%{q.strip()}%"
        sql += """ AND (c.first_name LIKE ? OR c.last_name LIKE ? OR c.email LIKE ? OR c.phone LIKE ?
                   OR c.mobile LIKE ? OR c.title LIKE ? OR c.notes LIKE ? OR cl.name LIKE ?)"""
        params += [like] * 8
    if clinic_id is not None:
        sql += " AND c.clinic_id = ?"
        params.append(clinic_id)
    if role:
        sql += " AND c.role = ?"
        params.append(role)
    sql += " ORDER BY c.last_name COLLATE NOCASE, c.first_name COLLATE NOCASE"
    return [_decorate(r) for r in rows_to_list(conn.execute(sql, params))]


@router.post("", status_code=201)
def create_contact(payload: ContactIn, conn: sqlite3.Connection = Depends(db_dependency)):
    data = payload.model_dump()
    _check_clinic(conn, data["clinic_id"])
    data["is_primary"] = int(data["is_primary"])
    cols = ", ".join(CONTACT_COLUMNS)
    marks = ", ".join("?" * len(CONTACT_COLUMNS))
    cur = conn.execute(f"INSERT INTO contacts ({cols}) VALUES ({marks})", [data[c] for c in CONTACT_COLUMNS])
    return _get_or_404(conn, cur.lastrowid)


@router.get("/{contact_id}")
def get_contact(contact_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    return _get_or_404(conn, contact_id)


@router.put("/{contact_id}")
def update_contact(contact_id: int, payload: ContactIn, conn: sqlite3.Connection = Depends(db_dependency)):
    _get_or_404(conn, contact_id)
    data = payload.model_dump()
    _check_clinic(conn, data["clinic_id"])
    data["is_primary"] = int(data["is_primary"])
    sets = ", ".join(f"{c} = ?" for c in CONTACT_COLUMNS)
    conn.execute(
        f"UPDATE contacts SET {sets}, updated_at = ? WHERE id = ?",
        [data[c] for c in CONTACT_COLUMNS] + [now_iso(), contact_id],
    )
    return _get_or_404(conn, contact_id)


@router.delete("/{contact_id}", status_code=204)
def delete_contact(contact_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    _get_or_404(conn, contact_id)
    conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
    return None
