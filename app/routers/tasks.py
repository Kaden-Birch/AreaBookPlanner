"""Tasks / reminders, optionally linked to a clinic and contact."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ..database import db_dependency, row_to_dict, rows_to_list
from ..logic import now_iso
from ..schemas import TaskIn, TaskPatch

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

TASK_COLUMNS = ["clinic_id", "contact_id", "title", "notes", "due_date", "due_time", "reminder_minutes", "rep", "priority", "done"]

SELECT = """SELECT t.*, cl.name AS clinic_name, c.first_name AS contact_first_name, c.last_name AS contact_last_name
            FROM tasks t LEFT JOIN clinics cl ON cl.id = t.clinic_id
            LEFT JOIN contacts c ON c.id = t.contact_id"""


def _decorate(row: dict) -> dict:
    row["done"] = bool(row["done"])
    row["contact_name"] = " ".join(p for p in [row.get("contact_first_name"), row.get("contact_last_name")] if p) or None
    today = now_iso()[:10]
    row["overdue"] = (not row["done"]) and bool(row["due_date"]) and row["due_date"] < today
    row["due_today"] = (not row["done"]) and row["due_date"] == today
    return row


def _get_or_404(conn: sqlite3.Connection, task_id: int) -> dict:
    row = row_to_dict(conn.execute(f"{SELECT} WHERE t.id = ?", (task_id,)).fetchone())
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return _decorate(row)


def _validate(conn: sqlite3.Connection, data: dict) -> None:
    if data.get("clinic_id") is not None:
        if conn.execute("SELECT 1 FROM clinics WHERE id = ?", (data["clinic_id"],)).fetchone() is None:
            raise HTTPException(status_code=422, detail="Clinic does not exist")
    if data.get("contact_id") is not None:
        if conn.execute("SELECT 1 FROM contacts WHERE id = ?", (data["contact_id"],)).fetchone() is None:
            raise HTTPException(status_code=422, detail="Contact does not exist")


@router.get("")
def list_tasks(
    clinic_id: int | None = None,
    done: bool | None = None,
    due_before: str | None = None,
    q: str | None = None,
    conn: sqlite3.Connection = Depends(db_dependency),
):
    sql = f"{SELECT} WHERE 1=1"
    params: list = []
    if clinic_id is not None:
        sql += " AND t.clinic_id = ?"
        params.append(clinic_id)
    if done is not None:
        sql += " AND t.done = ?"
        params.append(int(done))
    if due_before:
        sql += " AND t.due_date IS NOT NULL AND t.due_date <= ?"
        params.append(due_before)
    if q:
        like = f"%{q.strip()}%"
        sql += " AND (t.title LIKE ? OR t.notes LIKE ? OR cl.name LIKE ?)"
        params += [like] * 3
    sql += " ORDER BY t.done ASC, t.due_date IS NULL, t.due_date ASC, CASE t.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, t.id DESC"
    return [_decorate(r) for r in rows_to_list(conn.execute(sql, params))]


@router.post("", status_code=201)
def create_task(payload: TaskIn, conn: sqlite3.Connection = Depends(db_dependency)):
    data = payload.model_dump()
    _validate(conn, data)
    data["done"] = int(data["done"])
    cols = ", ".join(TASK_COLUMNS + ["done_at"])
    marks = ", ".join("?" * (len(TASK_COLUMNS) + 1))
    cur = conn.execute(
        f"INSERT INTO tasks ({cols}) VALUES ({marks})",
        [data[c] for c in TASK_COLUMNS] + [now_iso() if data["done"] else None],
    )
    return _get_or_404(conn, cur.lastrowid)


@router.get("/{task_id}")
def get_task(task_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    return _get_or_404(conn, task_id)


@router.put("/{task_id}")
def update_task(task_id: int, payload: TaskIn, conn: sqlite3.Connection = Depends(db_dependency)):
    before = _get_or_404(conn, task_id)
    data = payload.model_dump()
    _validate(conn, data)
    data["done"] = int(data["done"])
    done_at = before["done_at"] if before["done"] and data["done"] else (now_iso() if data["done"] else None)
    sets = ", ".join(f"{c} = ?" for c in TASK_COLUMNS)
    conn.execute(
        f"UPDATE tasks SET {sets}, done_at = ?, updated_at = ? WHERE id = ?",
        [data[c] for c in TASK_COLUMNS] + [done_at, now_iso(), task_id],
    )
    return _get_or_404(conn, task_id)


@router.patch("/{task_id}")
def patch_task(task_id: int, payload: TaskPatch, conn: sqlite3.Connection = Depends(db_dependency)):
    """Quick toggle done / reschedule."""
    _get_or_404(conn, task_id)
    if payload.done is not None:
        conn.execute(
            "UPDATE tasks SET done = ?, done_at = ?, updated_at = ? WHERE id = ?",
            (int(payload.done), now_iso() if payload.done else None, now_iso(), task_id),
        )
    if payload.due_date is not None:
        conn.execute("UPDATE tasks SET due_date = ?, updated_at = ? WHERE id = ?", (payload.due_date or None, now_iso(), task_id))
    return _get_or_404(conn, task_id)


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    _get_or_404(conn, task_id)
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    return None
