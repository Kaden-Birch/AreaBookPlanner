"""Appointment CRUD. Appointments are always linked to a clinic."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ..database import db_dependency, row_to_dict, rows_to_list
from ..logic import marker_color, now_iso, visit_stats
from ..schemas import AppointmentIn, AppointmentPatch

router = APIRouter(prefix="/api/appointments", tags=["appointments"])

APPT_COLUMNS = [
    "clinic_id", "contact_id", "title", "appt_type", "status", "start_time", "end_time",
    "location", "notes", "outcome",
]

TYPE_LABELS = {
    "visit": "Site visit",
    "call": "Phone call",
    "demo": "Demo",
    "install": "Installation",
    "support": "Support visit",
    "other": "Other",
}
STATUS_LABELS = {
    "scheduled": "Scheduled",
    "completed": "Completed",
    "cancelled": "Cancelled",
    "no_show": "No show",
}

SELECT = """SELECT a.*, cl.name AS clinic_name, cl.relationship AS clinic_relationship,
                   cl.address AS clinic_address, cl.lat AS clinic_lat, cl.lng AS clinic_lng,
                   c.first_name AS contact_first_name, c.last_name AS contact_last_name
            FROM appointments a
            JOIN clinics cl ON cl.id = a.clinic_id
            LEFT JOIN contacts c ON c.id = a.contact_id"""


def _decorate(conn: sqlite3.Connection, row: dict) -> dict:
    row["type_label"] = TYPE_LABELS.get(row["appt_type"], row["appt_type"])
    row["status_label"] = STATUS_LABELS.get(row["status"], row["status"])
    row["contact_name"] = " ".join(
        p for p in [row.get("contact_first_name"), row.get("contact_last_name")] if p
    ) or None
    stats = visit_stats(conn, row["clinic_id"])
    row["clinic_color"] = marker_color(row["clinic_relationship"], stats["last_visit"])
    return row


def _get_or_404(conn: sqlite3.Connection, appt_id: int) -> dict:
    row = row_to_dict(conn.execute(f"{SELECT} WHERE a.id = ?", (appt_id,)).fetchone())
    if row is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return _decorate(conn, row)


def _validate(conn: sqlite3.Connection, data: dict) -> None:
    if conn.execute("SELECT 1 FROM clinics WHERE id = ?", (data["clinic_id"],)).fetchone() is None:
        raise HTTPException(status_code=422, detail="Clinic does not exist")
    if data.get("contact_id") is not None:
        if conn.execute("SELECT 1 FROM contacts WHERE id = ?", (data["contact_id"],)).fetchone() is None:
            raise HTTPException(status_code=422, detail="Contact does not exist")
    if data.get("end_time") and data["end_time"] < data["start_time"]:
        raise HTTPException(status_code=422, detail="End time must be after start time")


@router.get("")
def list_appointments(
    start: str | None = None,
    end: str | None = None,
    clinic_id: int | None = None,
    status: str | None = None,
    upcoming: bool = False,
    limit: int | None = None,
    conn: sqlite3.Connection = Depends(db_dependency),
):
    sql = f"{SELECT} WHERE 1=1"
    params: list = []
    if start:
        sql += " AND a.start_time >= ?"
        params.append(start)
    if end:
        sql += " AND a.start_time < ?"
        params.append(end)
    if clinic_id is not None:
        sql += " AND a.clinic_id = ?"
        params.append(clinic_id)
    if status:
        sql += " AND a.status = ?"
        params.append(status)
    if upcoming:
        sql += " AND a.status = 'scheduled' AND a.start_time >= ?"
        params.append(now_iso())
    sql += " ORDER BY a.start_time ASC"
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    return [_decorate(conn, r) for r in rows_to_list(conn.execute(sql, params))]


@router.post("", status_code=201)
def create_appointment(payload: AppointmentIn, conn: sqlite3.Connection = Depends(db_dependency)):
    data = payload.model_dump()
    _validate(conn, data)
    cols = ", ".join(APPT_COLUMNS)
    marks = ", ".join("?" * len(APPT_COLUMNS))
    cur = conn.execute(f"INSERT INTO appointments ({cols}) VALUES ({marks})", [data[c] for c in APPT_COLUMNS])
    return _get_or_404(conn, cur.lastrowid)


@router.get("/{appt_id}")
def get_appointment(appt_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    return _get_or_404(conn, appt_id)


@router.put("/{appt_id}")
def update_appointment(appt_id: int, payload: AppointmentIn, conn: sqlite3.Connection = Depends(db_dependency)):
    _get_or_404(conn, appt_id)
    data = payload.model_dump()
    _validate(conn, data)
    sets = ", ".join(f"{c} = ?" for c in APPT_COLUMNS)
    conn.execute(
        f"UPDATE appointments SET {sets}, updated_at = ? WHERE id = ?",
        [data[c] for c in APPT_COLUMNS] + [now_iso(), appt_id],
    )
    return _get_or_404(conn, appt_id)


@router.patch("/{appt_id}")
def patch_appointment(appt_id: int, payload: AppointmentPatch, conn: sqlite3.Connection = Depends(db_dependency)):
    """Partial update used for quick actions (mark complete, reschedule by drag)."""
    _get_or_404(conn, appt_id)
    changes = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not changes:
        return _get_or_404(conn, appt_id)
    sets = ", ".join(f"{k} = ?" for k in changes)
    conn.execute(
        f"UPDATE appointments SET {sets}, updated_at = ? WHERE id = ?",
        [*changes.values(), now_iso(), appt_id],
    )
    return _get_or_404(conn, appt_id)


@router.delete("/{appt_id}", status_code=204)
def delete_appointment(appt_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    _get_or_404(conn, appt_id)
    conn.execute("DELETE FROM appointments WHERE id = ?", (appt_id,))
    return None
