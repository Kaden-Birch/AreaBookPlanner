"""Clinic CRUD, clinic notes, and clinic detail (with contacts + appointments)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from ..database import db_dependency, row_to_dict, rows_to_list
from ..logic import (
    LOST_REASONS, RELATIONSHIP_LABELS, STAGE_LABELS, WON_REASONS, enrich_clinic, log_event, now_iso,
)
from ..schemas import ClinicIn, NoteIn, StageChange

router = APIRouter(prefix="/api/clinics", tags=["clinics"])

CLINIC_COLUMNS = [
    "name", "address", "city", "province", "postal_code", "phone", "fax", "email", "website",
    "lat", "lng", "relationship", "clinic_type", "emr_system", "it_provider", "provider_count",
    "priority", "tags", "notes", "next_follow_up",
    "stage", "deal_value", "expected_close", "win_probability",
    "outcome_reason", "outcome_notes", "outcome_date",
]


def _sync_stage_and_relationship(data: dict, previous: dict | None) -> None:
    """Keep the pipeline stage and the map relationship consistent.

    Winning a deal makes the clinic a current client; marking a clinic as a
    current client counts as a won deal. Do-not-contact never changes stage.
    """
    prev_stage = previous.get("stage") if previous else None
    prev_rel = previous.get("relationship") if previous else None
    if data["stage"] == "won" and data["stage"] != prev_stage and data["relationship"] != "do_not_contact":
        data["relationship"] = "current_client"
    elif data["relationship"] == "current_client" and data["relationship"] != prev_rel and data["stage"] != "won":
        data["stage"] = "won"
    if data["stage"] in ("won", "lost") and data["stage"] != prev_stage and not data.get("outcome_date"):
        data["outcome_date"] = now_iso()[:10]


def _log_changes(conn: sqlite3.Connection, clinic_id: int, before: dict, after: dict) -> None:
    if before.get("stage") != after.get("stage"):
        detail = None
        if after["stage"] in ("won", "lost") and after.get("outcome_reason"):
            reasons = WON_REASONS if after["stage"] == "won" else LOST_REASONS
            detail = reasons.get(after["outcome_reason"], after["outcome_reason"])
            if after.get("outcome_notes"):
                detail += f" — {after['outcome_notes']}"
        log_event(
            conn, clinic_id, "stage_change",
            f"Stage: {STAGE_LABELS.get(before.get('stage'), before.get('stage'))} → {STAGE_LABELS.get(after['stage'], after['stage'])}",
            detail,
        )
    if before.get("relationship") != after.get("relationship"):
        log_event(
            conn, clinic_id, "relationship_change",
            f"Relationship: {RELATIONSHIP_LABELS.get(before.get('relationship'))} → {RELATIONSHIP_LABELS.get(after['relationship'])}",
        )


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
    stage: str | None = None,
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
    if stage:
        sql += " AND stage IN (%s)" % ",".join("?" * len(stage.split(",")))
        params += stage.split(",")
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
    _sync_stage_and_relationship(data, None)
    cols = ", ".join(CLINIC_COLUMNS)
    marks = ", ".join("?" * len(CLINIC_COLUMNS))
    cur = conn.execute(
        f"INSERT INTO clinics ({cols}) VALUES ({marks})", [data[c] for c in CLINIC_COLUMNS]
    )
    log_event(conn, cur.lastrowid, "created", "Clinic added",
              f"{STAGE_LABELS[data['stage']]} · {RELATIONSHIP_LABELS[data['relationship']]}")
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
    clinic["tasks"] = rows_to_list(
        conn.execute(
            "SELECT * FROM tasks WHERE clinic_id = ? ORDER BY done ASC, due_date IS NULL, due_date ASC, id DESC",
            (clinic_id,),
        )
    )
    clinic["timeline"] = build_timeline(conn, clinic_id)
    return clinic


def build_timeline(conn: sqlite3.Connection, clinic_id: int) -> list[dict]:
    """Merge notes, appointments, tasks and status events into one dated feed."""
    items: list[dict] = []
    for n in rows_to_list(conn.execute("SELECT * FROM clinic_notes WHERE clinic_id = ?", (clinic_id,))):
        items.append({"type": "note", "at": n["created_at"], "id": n["id"], "title": "Note", "body": n["body"]})
    for a in rows_to_list(conn.execute(
        """SELECT a.*, c.first_name, c.last_name FROM appointments a
           LEFT JOIN contacts c ON c.id = a.contact_id WHERE a.clinic_id = ?""", (clinic_id,))):
        who = " ".join(p for p in [a["first_name"], a["last_name"]] if p)
        body = " · ".join(p for p in [f"with {who}" if who else None, a["outcome"] or a["notes"]] if p)
        items.append({
            "type": "appointment", "at": a["start_time"], "id": a["id"], "title": a["title"],
            "body": body or None, "appt_type": a["appt_type"], "status": a["status"],
            "future": a["start_time"] > now_iso(),
        })
    for t in rows_to_list(conn.execute("SELECT * FROM tasks WHERE clinic_id = ?", (clinic_id,))):
        at = t["done_at"] if t["done"] and t["done_at"] else (t["due_date"] + "T23:59" if t["due_date"] else t["created_at"])
        items.append({
            "type": "task", "at": at, "id": t["id"], "title": ("Done: " if t["done"] else "Task: ") + t["title"],
            "body": t["notes"], "done": bool(t["done"]), "future": (not t["done"]) and at > now_iso(),
        })
    for e in rows_to_list(conn.execute("SELECT * FROM clinic_events WHERE clinic_id = ?", (clinic_id,))):
        items.append({"type": e["event_type"], "at": e["created_at"], "id": e["id"], "title": e["title"], "body": e["detail"]})
    items.sort(key=lambda x: x["at"], reverse=True)
    return items


@router.get("/{clinic_id}/timeline")
def get_timeline(clinic_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    _get_clinic_or_404(conn, clinic_id)
    return build_timeline(conn, clinic_id)


@router.patch("/{clinic_id}/stage")
def change_stage(clinic_id: int, payload: StageChange, conn: sqlite3.Connection = Depends(db_dependency)):
    """Move a clinic to another pipeline stage (Kanban drag/drop)."""
    before = _get_clinic_or_404(conn, clinic_id)
    data = dict(before)
    data["stage"] = payload.stage
    if payload.stage in ("won", "lost"):
        data["outcome_reason"] = payload.outcome_reason
        data["outcome_notes"] = payload.outcome_notes
        data["outcome_date"] = now_iso()[:10]
    else:
        data["outcome_reason"] = None
        data["outcome_notes"] = None
        data["outcome_date"] = None
    _sync_stage_and_relationship(data, before)
    conn.execute(
        """UPDATE clinics SET stage = ?, relationship = ?, outcome_reason = ?, outcome_notes = ?,
           outcome_date = ?, updated_at = ? WHERE id = ?""",
        (data["stage"], data["relationship"], data["outcome_reason"], data["outcome_notes"],
         data["outcome_date"], now_iso(), clinic_id),
    )
    _log_changes(conn, clinic_id, before, data)
    return enrich_clinic(conn, _get_clinic_or_404(conn, clinic_id))


@router.put("/{clinic_id}")
def update_clinic(clinic_id: int, payload: ClinicIn, conn: sqlite3.Connection = Depends(db_dependency)):
    before = _get_clinic_or_404(conn, clinic_id)
    data = payload.model_dump()
    _sync_stage_and_relationship(data, before)
    sets = ", ".join(f"{c} = ?" for c in CLINIC_COLUMNS)
    conn.execute(
        f"UPDATE clinics SET {sets}, updated_at = ? WHERE id = ?",
        [data[c] for c in CLINIC_COLUMNS] + [now_iso(), clinic_id],
    )
    _log_changes(conn, clinic_id, before, data)
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
