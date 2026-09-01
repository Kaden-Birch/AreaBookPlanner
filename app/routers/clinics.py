"""Clinic CRUD, clinic notes, and clinic detail (with contacts + appointments)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from ..database import db_dependency, row_to_dict, rows_to_list
from ..logic import enrich_clinic, now_iso
from ..schemas import ClinicIn, NoteIn

router = APIRouter(prefix="/api/clinics", tags=["clinics"])

CLINIC_COLUMNS = [
    "name", "address", "city", "province", "postal_code", "phone", "fax", "email", "website",
    "lat", "lng", "relationship", "clinic_type", "emr_system", "it_provider", "provider_count",
    "priority", "tags", "notes", "next_follow_up",
]


def _get_clinic_or_404(conn: sqlite3.Connection, clinic_id: int) -> dict:
    row = row_to_dict(conn.execute("SELECT * FROM clinics WHERE id = ?", (clinic_id,)).fetchone())
    if row is None:
        raise HTTPException(status_code=404, detail="Clinic not found")
    return row


@router.get("")
def list_clinics(
    q: str | None = Query(default=None, description="Search name/address/tags/notes"),
    relationship: str | None = None,
    color: str | None = None,
    has_location: bool | None = None,
    conn: sqlite3.Connection = Depends(db_dependency),
):
    sql = "SELECT * FROM clinics WHERE 1=1"
    params: list = []
    if q:
        like = f"%{q.strip()}%"
        sql += """ AND (name LIKE ? OR address LIKE ? OR postal_code LIKE ? OR tags LIKE ?
                   OR notes LIKE ? OR emr_system LIKE ? OR clinic_type LIKE ?)"""
        params += [like] * 7
    if relationship:
        sql += " AND relationship = ?"
        params.append(relationship)
    if has_location is True:
        sql += " AND lat IS NOT NULL AND lng IS NOT NULL"
    elif has_location is False:
        sql += " AND (lat IS NULL OR lng IS NULL)"
    sql += " ORDER BY name COLLATE NOCASE ASC"
    clinics = [enrich_clinic(conn, c) for c in rows_to_list(conn.execute(sql, params))]
    if color:
        wanted = set(color.split(","))
        clinics = [c for c in clinics if c["color"] in wanted]
    return clinics


@router.post("", status_code=201)
def create_clinic(payload: ClinicIn, conn: sqlite3.Connection = Depends(db_dependency)):
    data = payload.model_dump()
    cols = ", ".join(CLINIC_COLUMNS)
    marks = ", ".join("?" * len(CLINIC_COLUMNS))
    cur = conn.execute(
        f"INSERT INTO clinics ({cols}) VALUES ({marks})", [data[c] for c in CLINIC_COLUMNS]
    )
    return enrich_clinic(conn, _get_clinic_or_404(conn, cur.lastrowid))


@router.get("/{clinic_id}")
def get_clinic(clinic_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    clinic = enrich_clinic(conn, _get_clinic_or_404(conn, clinic_id))
    clinic["contacts"] = rows_to_list(
        conn.execute(
            "SELECT * FROM contacts WHERE clinic_id = ? ORDER BY is_primary DESC, last_name COLLATE NOCASE, first_name COLLATE NOCASE",
            (clinic_id,),
        )
    )
    clinic["appointments"] = rows_to_list(
        conn.execute(
            """SELECT a.*, c.first_name AS contact_first_name, c.last_name AS contact_last_name
               FROM appointments a LEFT JOIN contacts c ON c.id = a.contact_id
               WHERE a.clinic_id = ? ORDER BY a.start_time DESC""",
            (clinic_id,),
        )
    )
    clinic["note_log"] = rows_to_list(
        conn.execute(
            "SELECT * FROM clinic_notes WHERE clinic_id = ? ORDER BY created_at DESC, id DESC",
            (clinic_id,),
        )
    )
    return clinic


@router.put("/{clinic_id}")
def update_clinic(clinic_id: int, payload: ClinicIn, conn: sqlite3.Connection = Depends(db_dependency)):
    _get_clinic_or_404(conn, clinic_id)
    data = payload.model_dump()
    sets = ", ".join(f"{c} = ?" for c in CLINIC_COLUMNS)
    conn.execute(
        f"UPDATE clinics SET {sets}, updated_at = ? WHERE id = ?",
        [data[c] for c in CLINIC_COLUMNS] + [now_iso(), clinic_id],
    )
    return enrich_clinic(conn, _get_clinic_or_404(conn, clinic_id))


@router.patch("/{clinic_id}/location")
def update_location(
    clinic_id: int, body: dict, conn: sqlite3.Connection = Depends(db_dependency)
):
    """Quick pin move from the map (drag) without resubmitting the whole record."""
    _get_clinic_or_404(conn, clinic_id)
    lat, lng = body.get("lat"), body.get("lng")
    if lat is None or lng is None:
        raise HTTPException(status_code=422, detail="lat and lng are required")
    conn.execute(
        "UPDATE clinics SET lat = ?, lng = ?, updated_at = ? WHERE id = ?",
        (float(lat), float(lng), now_iso(), clinic_id),
    )
    return enrich_clinic(conn, _get_clinic_or_404(conn, clinic_id))


@router.delete("/{clinic_id}", status_code=204)
def delete_clinic(clinic_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    _get_clinic_or_404(conn, clinic_id)
    conn.execute("DELETE FROM clinics WHERE id = ?", (clinic_id,))
    return None


# ---- Note log -------------------------------------------------------------

@router.get("/{clinic_id}/notes")
def list_notes(clinic_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    _get_clinic_or_404(conn, clinic_id)
    return rows_to_list(
        conn.execute(
            "SELECT * FROM clinic_notes WHERE clinic_id = ? ORDER BY created_at DESC, id DESC",
            (clinic_id,),
        )
    )


@router.post("/{clinic_id}/notes", status_code=201)
def add_note(clinic_id: int, payload: NoteIn, conn: sqlite3.Connection = Depends(db_dependency)):
    _get_clinic_or_404(conn, clinic_id)
    cur = conn.execute(
        "INSERT INTO clinic_notes (clinic_id, body, author) VALUES (?, ?, ?)",
        (clinic_id, payload.body.strip(), payload.author),
    )
    conn.execute("UPDATE clinics SET updated_at = ? WHERE id = ?", (now_iso(), clinic_id))
    return row_to_dict(conn.execute("SELECT * FROM clinic_notes WHERE id = ?", (cur.lastrowid,)).fetchone())


@router.delete("/{clinic_id}/notes/{note_id}", status_code=204)
def delete_note(clinic_id: int, note_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    cur = conn.execute("DELETE FROM clinic_notes WHERE id = ? AND clinic_id = ?", (note_id, clinic_id))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Note not found")
    return None
