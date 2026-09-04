"""Groups, attachments, search, reminders, analytics, saved views, email templates,
CSV import and bulk geocoding."""
from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..database import ATTACHMENTS_DIR, db_dependency, get_db, row_to_dict, rows_to_list
from ..logic import (
    IN_PERSON_TYPES, LINK_TYPES, OPEN_STAGES, QUICK_LOGS, REMINDER_OPTIONS, STAGE_LABELS, enrich_clinic,
    log_event, now_iso,
)
from ..schemas import AiDraftIn, BulkGeocodeRequest, ClinicIn, GroupIn, ImportRequest, SavedViewIn, SettingsIn, TemplateIn
from .clinics import CLINIC_COLUMNS, _sync_stage_and_relationship, find_duplicates
from .misc import NOMINATIM_URL, USER_AGENT, CALGARY_VIEWBOX

router = APIRouter(prefix="/api", tags=["extras"])

MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


# ---- Groups / chains --------------------------------------------------------

@router.get("/groups")
def list_groups(conn: sqlite3.Connection = Depends(db_dependency)):
    rows = rows_to_list(conn.execute(
        """SELECT g.*, (SELECT COUNT(*) FROM clinics c WHERE c.group_id = g.id) AS member_count
           FROM clinic_groups g ORDER BY g.name COLLATE NOCASE"""))
    for g in rows:
        g["members"] = rows_to_list(conn.execute(
            "SELECT id, name, relationship, shorthand FROM clinics WHERE group_id = ? ORDER BY name COLLATE NOCASE", (g["id"],)))
    return rows


@router.post("/groups", status_code=201)
def create_group(payload: GroupIn, conn: sqlite3.Connection = Depends(db_dependency)):
    cur = conn.execute("INSERT INTO clinic_groups (name, notes) VALUES (?, ?)", (payload.name.strip(), payload.notes))
    return row_to_dict(conn.execute("SELECT * FROM clinic_groups WHERE id = ?", (cur.lastrowid,)).fetchone())


@router.put("/groups/{group_id}")
def update_group(group_id: int, payload: GroupIn, conn: sqlite3.Connection = Depends(db_dependency)):
    cur = conn.execute("UPDATE clinic_groups SET name = ?, notes = ? WHERE id = ?", (payload.name.strip(), payload.notes, group_id))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Group not found")
    return row_to_dict(conn.execute("SELECT * FROM clinic_groups WHERE id = ?", (group_id,)).fetchone())


@router.delete("/groups/{group_id}", status_code=204)
def delete_group(group_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    cur = conn.execute("DELETE FROM clinic_groups WHERE id = ?", (group_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Group not found")
    return None


# ---- Locations across all clinics (for the map) ----------------------------

@router.get("/locations")
def all_locations(conn: sqlite3.Connection = Depends(db_dependency)):
    rows = rows_to_list(conn.execute(
        """SELECT l.*, c.name AS clinic_name, c.relationship, c.shorthand
           FROM clinic_locations l JOIN clinics c ON c.id = l.clinic_id
           WHERE l.lat IS NOT NULL AND l.lng IS NOT NULL"""))
    for r in rows:
        parent = enrich_clinic(conn, {"id": r["clinic_id"], "relationship": r["relationship"], "stage": "prospect", "tags": None})
        r["color"] = parent["color"]
        r["color_label"] = parent["color_label"]
    return rows


# ---- Attachments (documents & photos) --------------------------------------

def _safe_name(name: str) -> str:
    name = os.path.basename(name or "file")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "file"
    return name[:120]


@router.get("/clinics/{clinic_id}/attachments")
def list_attachments(clinic_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    return rows_to_list(conn.execute("SELECT * FROM attachments WHERE clinic_id = ? ORDER BY created_at DESC, id DESC", (clinic_id,)))


@router.post("/clinics/{clinic_id}/attachments", status_code=201)
async def upload_attachment(
    clinic_id: int, file: UploadFile = File(...), caption: str | None = Form(default=None),
    kind: str | None = Form(default=None), note_id: int | None = Form(default=None),
    service_id: int | None = Form(default=None),
    conn: sqlite3.Connection = Depends(db_dependency),
):
    if conn.execute("SELECT 1 FROM clinics WHERE id = ?", (clinic_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Clinic not found")
    data = await file.read()
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than 25 MB")
    if not data:
        raise HTTPException(status_code=422, detail="Empty file")
    content_type = file.content_type or "application/octet-stream"
    if kind not in ("document", "photo"):
        kind = "photo" if content_type.startswith("image/") else "document"
    # Only link to a note that belongs to this clinic.
    if note_id is not None and conn.execute(
            "SELECT 1 FROM clinic_notes WHERE id = ? AND clinic_id = ?", (note_id, clinic_id)).fetchone() is None:
        note_id = None
    # Only link to a service on one of this clinic's devices.
    if service_id is not None and conn.execute(
            """SELECT 1 FROM device_services s JOIN devices d ON d.id = s.device_id
               WHERE s.id = ? AND d.clinic_id = ?""", (service_id, clinic_id)).fetchone() is None:
        service_id = None
    filename = _safe_name(file.filename or "file")
    cur = conn.execute(
        "INSERT INTO attachments (clinic_id, filename, stored_name, content_type, size, kind, caption, note_id, service_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (clinic_id, filename, "", content_type, len(data), kind, caption, note_id, service_id),
    )
    stored = f"{cur.lastrowid}_{filename}"
    Path(ATTACHMENTS_DIR).mkdir(parents=True, exist_ok=True)
    (Path(ATTACHMENTS_DIR) / stored).write_bytes(data)
    conn.execute("UPDATE attachments SET stored_name = ? WHERE id = ?", (stored, cur.lastrowid))
    log_event(conn, clinic_id, "attachment", f"{'Photo' if kind == 'photo' else 'Document'} added: {filename}", caption)
    return row_to_dict(conn.execute("SELECT * FROM attachments WHERE id = ?", (cur.lastrowid,)).fetchone())


@router.get("/attachments/{att_id}/file")
def get_attachment_file(att_id: int, download: bool = False, conn: sqlite3.Connection = Depends(db_dependency)):
    row = row_to_dict(conn.execute("SELECT * FROM attachments WHERE id = ?", (att_id,)).fetchone())
    if row is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    path = Path(ATTACHMENTS_DIR) / row["stored_name"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="File is missing from disk")
    headers = {"Content-Disposition": f'{"attachment" if download else "inline"}; filename="{row["filename"]}"'}
    return FileResponse(path, media_type=row["content_type"] or "application/octet-stream", headers=headers)


@router.delete("/attachments/{att_id}", status_code=204)
def delete_attachment(att_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    row = row_to_dict(conn.execute("SELECT * FROM attachments WHERE id = ?", (att_id,)).fetchone())
    if row is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    conn.execute("DELETE FROM attachments WHERE id = ?", (att_id,))
    try:
        (Path(ATTACHMENTS_DIR) / row["stored_name"]).unlink(missing_ok=True)
    except OSError:
        pass
    return None


# ---- Global search ----------------------------------------------------------

@router.get("/search")
def search(q: str, limit: int = 8, conn: sqlite3.Connection = Depends(db_dependency)):
    q = (q or "").strip()
    if len(q) < 2:
        return {"clinics": [], "contacts": [], "notes": [], "tasks": [], "locations": [], "devices": [], "services": []}
    like = f"%{q}%"
    clinics = [
        enrich_clinic(conn, c) for c in rows_to_list(conn.execute(
            """SELECT * FROM clinics WHERE name LIKE ? OR shorthand LIKE ? OR address LIKE ? OR tags LIKE ? OR postal_code LIKE ?
               ORDER BY CASE WHEN shorthand = ? THEN 0 WHEN name LIKE ? THEN 1 ELSE 2 END, name COLLATE NOCASE LIMIT ?""",
            (like, like, like, like, like, q.upper(), f"{q}%", limit)))
    ]
    contacts = rows_to_list(conn.execute(
        """SELECT c.id, c.first_name, c.last_name, c.role, c.email, c.phone, c.clinic_id, cl.name AS clinic_name
           FROM contacts c LEFT JOIN clinics cl ON cl.id = c.clinic_id
           WHERE c.first_name LIKE ? OR c.last_name LIKE ? OR (c.first_name || ' ' || c.last_name) LIKE ? OR c.email LIKE ? OR c.title LIKE ?
           ORDER BY c.last_name COLLATE NOCASE LIMIT ?""", (like, like, like, like, like, limit)))
    notes = rows_to_list(conn.execute(
        """SELECT n.id, n.body, n.created_at, n.clinic_id, cl.name AS clinic_name FROM clinic_notes n
           JOIN clinics cl ON cl.id = n.clinic_id WHERE n.body LIKE ? ORDER BY n.created_at DESC LIMIT ?""", (like, limit)))
    tasks = rows_to_list(conn.execute(
        """SELECT t.id, t.title, t.due_date, t.done, t.clinic_id, cl.name AS clinic_name FROM tasks t
           LEFT JOIN clinics cl ON cl.id = t.clinic_id WHERE t.title LIKE ? OR t.notes LIKE ? ORDER BY t.done, t.due_date LIMIT ?""", (like, like, limit)))
    locations = rows_to_list(conn.execute(
        """SELECT l.id, l.name, l.address, l.clinic_id, cl.name AS clinic_name FROM clinic_locations l
           JOIN clinics cl ON cl.id = l.clinic_id WHERE l.name LIKE ? OR l.address LIKE ? LIMIT ?""", (like, like, limit)))
    devices = rows_to_list(conn.execute(
        """SELECT d.id, d.name, d.device_type, d.ip_address, d.user_name, d.clinic_id, cl.name AS clinic_name FROM devices d
           JOIN clinics cl ON cl.id = d.clinic_id
           WHERE d.name LIKE ? OR d.ip_address LIKE ? OR d.user_name LIKE ? OR d.serial LIKE ? OR d.model LIKE ? LIMIT ?""",
        (like, like, like, like, like, limit)))
    from ..logic import DEVICE_TYPES
    for d in devices:
        d["icon"] = DEVICE_TYPES.get(d["device_type"], DEVICE_TYPES["other"])["icon"]
    services = rows_to_list(conn.execute(
        """SELECT s.id, s.name, s.ip_addresses, s.ports, s.internal_url, s.public_url,
                  d.id AS device_id, d.name AS device_name, cl.id AS clinic_id, cl.name AS clinic_name
           FROM device_services s JOIN devices d ON d.id = s.device_id JOIN clinics cl ON cl.id = d.clinic_id
           WHERE s.name LIKE ? OR s.description LIKE ? OR s.ip_addresses LIKE ? OR s.ports LIKE ?
           ORDER BY s.name COLLATE NOCASE LIMIT ?""", (like, like, like, like, limit)))
    return {
        "clinics": [{"id": c["id"], "name": c["name"], "shorthand": c["shorthand"], "address": c["address"], "color": c["color"], "color_label": c["color_label"]} for c in clinics],
        "contacts": contacts, "notes": notes, "tasks": tasks, "locations": locations, "devices": devices, "services": services,
    }


# ---- Reminders (browser notifications) --------------------------------------

@router.get("/reminders")
def reminders(horizon_minutes: int = 120, conn: sqlite3.Connection = Depends(db_dependency)):
    """Appointments and tasks starting within the horizon (plus a little grace behind).

    The browser decides when to fire: at the event time, and reminder_minutes before it.
    """
    now = datetime.now().replace(second=0, microsecond=0)
    lo = (now - timedelta(minutes=15)).isoformat(timespec="minutes")
    hi = (now + timedelta(minutes=horizon_minutes)).isoformat(timespec="minutes")
    items = []
    for a in rows_to_list(conn.execute(
        """SELECT a.id, a.title, a.start_time, a.reminder_minutes, a.clinic_id, cl.name AS clinic_name, cl.address
           FROM appointments a JOIN clinics cl ON cl.id = a.clinic_id
           WHERE a.status = 'scheduled' AND a.start_time >= ? AND a.start_time <= ?""", (lo, hi))):
        items.append({
            "kind": "appointment", "id": a["id"], "title": a["title"], "clinic_id": a["clinic_id"],
            "clinic_name": a["clinic_name"], "at": a["start_time"][:16], "reminder_minutes": a["reminder_minutes"],
            "url": f"#/clinics/{a['clinic_id']}", "body": a["address"] or "",
        })
    for t in rows_to_list(conn.execute(
        """SELECT t.id, t.title, t.due_date, t.due_time, t.reminder_minutes, t.clinic_id, cl.name AS clinic_name
           FROM tasks t LEFT JOIN clinics cl ON cl.id = t.clinic_id
           WHERE t.done = 0 AND t.due_date IS NOT NULL AND t.due_date >= ? AND t.due_date <= ?""", (lo[:10], hi[:10]))):
        at = f"{t['due_date']}T{t['due_time'] or '09:00'}"
        if lo <= at <= hi:
            items.append({
                "kind": "task", "id": t["id"], "title": t["title"], "clinic_id": t["clinic_id"],
                "clinic_name": t["clinic_name"], "at": at, "reminder_minutes": t["reminder_minutes"],
                "url": f"#/clinics/{t['clinic_id']}" if t["clinic_id"] else "#/tasks", "body": t["clinic_name"] or "Task due",
            })
    return {"now": now.isoformat(timespec="minutes"), "items": items, "options": REMINDER_OPTIONS}


# ---- Analytics ----------------------------------------------------------------

def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


@router.get("/analytics")
def analytics(weeks: int = 12, months: int = 12, conn: sqlite3.Connection = Depends(db_dependency)):
    today = date.today()
    now = now_iso()
    placeholders = ",".join("?" * len(IN_PERSON_TYPES))
    visits = rows_to_list(conn.execute(
        f"""SELECT a.start_time, a.rep, a.clinic_id, a.appt_type FROM appointments a
            WHERE a.appt_type IN ({placeholders}) AND a.status NOT IN ('cancelled','no_show') AND a.start_time <= ?""",
        (*IN_PERSON_TYPES, now)))
    all_appts = rows_to_list(conn.execute(
        "SELECT rep, appt_type, status, start_time FROM appointments WHERE start_time <= ?", (now,)))

    # Visits per week
    first_week = _week_start(today) - timedelta(weeks=weeks - 1)
    by_week = {(first_week + timedelta(weeks=i)).isoformat(): 0 for i in range(weeks)}
    for v in visits:
        d = _week_start(date.fromisoformat(v["start_time"][:10])).isoformat()
        if d in by_week:
            by_week[d] += 1
    # Visits per month + new clinics per month + won/lost per month
    month_keys = []
    y, m = today.year, today.month
    for _ in range(months):
        month_keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    month_keys.reverse()
    visits_month = {k: 0 for k in month_keys}
    for v in visits:
        k = v["start_time"][:7]
        if k in visits_month:
            visits_month[k] += 1
    clinics = [enrich_clinic(conn, c) for c in rows_to_list(conn.execute("SELECT * FROM clinics"))]
    new_month = {k: 0 for k in month_keys}
    won_month = {k: 0 for k in month_keys}
    lost_month = {k: 0 for k in month_keys}
    for c in clinics:
        k = (c["created_at"] or "")[:7]
        if k in new_month:
            new_month[k] += 1
        if c["stage"] in ("won", "lost") and c["outcome_date"]:
            k = c["outcome_date"][:7]
            if k in won_month:
                (won_month if c["stage"] == "won" else lost_month)[k] += 1

    won = sum(1 for c in clinics if c["stage"] == "won")
    lost = sum(1 for c in clinics if c["stage"] == "lost")
    open_deals = sum(1 for c in clinics if c["stage"] in OPEN_STAGES)

    # Time in stage from event history
    durations: dict[str, list[float]] = defaultdict(list)
    events = rows_to_list(conn.execute(
        "SELECT clinic_id, from_value, to_value, created_at FROM clinic_events WHERE event_type = 'stage_change' AND from_value IS NOT NULL ORDER BY clinic_id, created_at"))
    by_clinic: dict[int, list[dict]] = defaultdict(list)
    for e in events:
        by_clinic[e["clinic_id"]].append(e)
    created_by_id = {c["id"]: c["created_at"] for c in clinics}
    for cid, evs in by_clinic.items():
        start = created_by_id.get(cid)
        for e in evs:
            try:
                s = datetime.fromisoformat((start or e["created_at"]).replace("Z", "+00:00"))
                t = datetime.fromisoformat(e["created_at"].replace("Z", "+00:00"))
                durations[e["from_value"]].append(max(0.0, (t - s).total_seconds() / 86400))
            except ValueError:
                pass
            start = e["created_at"]
    time_in_stage = [
        {"stage": s, "label": STAGE_LABELS[s], "avg_days": round(sum(durations[s]) / len(durations[s]), 1) if durations[s] else None, "n": len(durations[s])}
        for s in OPEN_STAGES
    ]

    # Activity by rep
    reps: dict[str, dict] = defaultdict(lambda: {"visits": 0, "calls": 0, "notes": 0, "tasks_done": 0, "appointments": 0})
    for a in all_appts:
        r = a["rep"] or "Unassigned"
        if a["status"] in ("cancelled", "no_show"):
            continue
        reps[r]["appointments"] += 1
        if a["appt_type"] in IN_PERSON_TYPES:
            reps[r]["visits"] += 1
        elif a["appt_type"] == "call":
            reps[r]["calls"] += 1
    for n in rows_to_list(conn.execute("SELECT author FROM clinic_notes")):
        reps[n["author"] or "Unassigned"]["notes"] += 1
    for t in rows_to_list(conn.execute("SELECT rep FROM tasks WHERE done = 1")):
        reps[t["rep"] or "Unassigned"]["tasks_done"] += 1
    by_rep = [{"rep": k, **v, "total": v["appointments"] + v["notes"] + v["tasks_done"]} for k, v in reps.items()]
    by_rep.sort(key=lambda x: -x["total"])

    # This month vs last month visits
    this_m = month_keys[-1]
    last_m = month_keys[-2] if len(month_keys) > 1 else None
    return {
        "visits_by_week": [{"week": k, "count": v} for k, v in by_week.items()],
        "visits_by_month": [{"month": k, "count": v} for k, v in visits_month.items()],
        "new_clinics_by_month": [{"month": k, "count": v} for k, v in new_month.items()],
        "outcomes_by_month": [{"month": k, "won": won_month[k], "lost": lost_month[k]} for k in month_keys],
        "conversion": {"won": won, "lost": lost, "open": open_deals,
                       "rate": round(won / (won + lost) * 100, 1) if (won + lost) else None},
        "time_in_stage": time_in_stage,
        "by_rep": by_rep,
        "totals": {
            "visits_this_month": visits_month[this_m],
            "visits_last_month": visits_month[last_m] if last_m else 0,
            "visits_all_time": len(visits),
            "clinics_total": len(clinics),
            "clients": sum(1 for c in clinics if c["relationship"] == "current_client"),
        },
        "funnel": [{"stage": s, "label": STAGE_LABELS[s], "count": sum(1 for c in clinics if c["stage"] == s)} for s in STAGE_LABELS],
    }


# ---- Saved views -------------------------------------------------------------

@router.get("/views")
def list_views(page: str | None = None, conn: sqlite3.Connection = Depends(db_dependency)):
    sql = "SELECT * FROM saved_views"
    params: list = []
    if page:
        sql += " WHERE page = ?"
        params.append(page)
    rows = rows_to_list(conn.execute(sql + " ORDER BY name COLLATE NOCASE", params))
    for r in rows:
        r["state"] = json.loads(r["state"])
    return rows


@router.post("/views", status_code=201)
def create_view(payload: SavedViewIn, conn: sqlite3.Connection = Depends(db_dependency)):
    cur = conn.execute("INSERT INTO saved_views (name, page, state) VALUES (?, ?, ?)", (payload.name.strip(), payload.page, json.dumps(payload.state)))
    row = row_to_dict(conn.execute("SELECT * FROM saved_views WHERE id = ?", (cur.lastrowid,)).fetchone())
    row["state"] = json.loads(row["state"])
    return row


@router.delete("/views/{view_id}", status_code=204)
def delete_view(view_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    cur = conn.execute("DELETE FROM saved_views WHERE id = ?", (view_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="View not found")
    return None


# ---- Email templates ---------------------------------------------------------

@router.get("/templates")
def list_templates(conn: sqlite3.Connection = Depends(db_dependency)):
    return rows_to_list(conn.execute("SELECT * FROM email_templates ORDER BY name COLLATE NOCASE"))


@router.post("/templates", status_code=201)
def create_template(payload: TemplateIn, conn: sqlite3.Connection = Depends(db_dependency)):
    cur = conn.execute("INSERT INTO email_templates (name, subject, body) VALUES (?, ?, ?)", (payload.name.strip(), payload.subject, payload.body))
    return row_to_dict(conn.execute("SELECT * FROM email_templates WHERE id = ?", (cur.lastrowid,)).fetchone())


@router.put("/templates/{tpl_id}")
def update_template(tpl_id: int, payload: TemplateIn, conn: sqlite3.Connection = Depends(db_dependency)):
    cur = conn.execute("UPDATE email_templates SET name = ?, subject = ?, body = ? WHERE id = ?", (payload.name.strip(), payload.subject, payload.body, tpl_id))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Template not found")
    return row_to_dict(conn.execute("SELECT * FROM email_templates WHERE id = ?", (tpl_id,)).fetchone())


@router.delete("/templates/{tpl_id}", status_code=204)
def delete_template(tpl_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    cur = conn.execute("DELETE FROM email_templates WHERE id = ?", (tpl_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Template not found")
    return None


# ---- Misc metadata for the UI -----------------------------------------------

@router.get("/meta/extras")
def meta_extras():
    return {"link_types": LINK_TYPES, "quick_logs": QUICK_LOGS, "reminder_options": REMINDER_OPTIONS}


# ---- CSV import ---------------------------------------------------------------

IMPORT_FIELDS = [c for c in CLINIC_COLUMNS if c not in ("group_id",)]


@router.post("/import/clinics")
def import_clinics(payload: ImportRequest, conn: sqlite3.Connection = Depends(db_dependency)):
    """Bulk-create clinics from already-mapped rows (the UI does the CSV parsing/mapping)."""
    created, skipped, errors = [], [], []
    for i, raw in enumerate(payload.rows):
        row = {k: v for k, v in raw.items() if k in IMPORT_FIELDS}
        if not str(row.get("name") or "").strip():
            errors.append({"row": i + 1, "error": "Missing name"})
            continue
        try:
            data = ClinicIn(**row).model_dump()
        except Exception as exc:  # noqa: BLE001
            errors.append({"row": i + 1, "error": str(exc).splitlines()[0][:200]})
            continue
        if payload.skip_duplicates:
            dup = find_duplicates(conn, data["name"], data["address"], data["postal_code"])
            if dup:
                skipped.append({"row": i + 1, "name": data["name"], "match": dup[0]["name"], "match_id": dup[0]["id"], "reasons": dup[0]["reasons"]})
                continue
        _sync_stage_and_relationship(data, None)
        cols = ", ".join(CLINIC_COLUMNS)
        marks = ", ".join("?" * len(CLINIC_COLUMNS))
        cur = conn.execute(f"INSERT INTO clinics ({cols}) VALUES ({marks})", [data.get(c) for c in CLINIC_COLUMNS])
        log_event(conn, cur.lastrowid, "created", "Clinic imported from CSV")
        created.append({"id": cur.lastrowid, "name": data["name"], "needs_geocode": data["lat"] is None and bool(data["address"])})
    return {"created": created, "skipped": skipped, "errors": errors}


# ---- Bulk geocoding (background job) ----------------------------------------

_geo_lock = threading.Lock()
_geo_state: dict = {"running": False, "total": 0, "done": 0, "updated": 0, "failed": [], "started_at": None, "finished_at": None}


def _geocode_one(q: str) -> tuple[float, float] | None:
    params = {"q": q, "format": "jsonv2", "limit": 1, "countrycodes": "ca", "viewbox": CALGARY_VIEWBOX, "bounded": 0}
    req = urllib.request.Request(f"{NOMINATIM_URL}?{urllib.parse.urlencode(params)}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            results = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not results:
        return None
    return float(results[0]["lat"]), float(results[0]["lon"])


def _bulk_geocode_worker(ids: list[int]) -> None:
    try:
        for cid in ids:
            with get_db() as conn:
                c = conn.execute("SELECT id, name, address, city, province, postal_code FROM clinics WHERE id = ?", (cid,)).fetchone()
            if not c:
                continue
            q = ", ".join(p for p in [c["address"], c["city"], c["province"], c["postal_code"]] if p)
            hit = _geocode_one(q) if q else None
            with _geo_lock:
                _geo_state["done"] += 1
                if hit:
                    with get_db() as conn:
                        conn.execute("UPDATE clinics SET lat = ?, lng = ?, updated_at = ? WHERE id = ?", (hit[0], hit[1], now_iso(), cid))
                    _geo_state["updated"] += 1
                else:
                    _geo_state["failed"].append({"id": c["id"], "name": c["name"], "address": q})
            time.sleep(1.1)  # Nominatim usage policy: max 1 request/second
    finally:
        with _geo_lock:
            _geo_state["running"] = False
            _geo_state["finished_at"] = now_iso()


@router.post("/geocode/bulk", status_code=202)
def start_bulk_geocode(payload: BulkGeocodeRequest | None = None, conn: sqlite3.Connection = Depends(db_dependency)):
    with _geo_lock:
        if _geo_state["running"]:
            raise HTTPException(status_code=409, detail="A geocoding run is already in progress")
        sql = "SELECT id FROM clinics WHERE (lat IS NULL OR lng IS NULL) AND address IS NOT NULL AND address <> ''"
        params: list = []
        if payload and payload.clinic_ids:
            sql += " AND id IN (%s)" % ",".join("?" * len(payload.clinic_ids))
            params += payload.clinic_ids
        ids = [r[0] for r in conn.execute(sql, params).fetchall()]
        _geo_state.update({"running": bool(ids), "total": len(ids), "done": 0, "updated": 0, "failed": [],
                           "started_at": now_iso(), "finished_at": None if ids else now_iso()})
    if ids:
        threading.Thread(target=_bulk_geocode_worker, args=(ids,), daemon=True).start()
    return dict(_geo_state)


@router.get("/geocode/bulk")
def bulk_geocode_status():
    with _geo_lock:
        return dict(_geo_state)


# ---- Settings (server-side key/value; used for the OpenAI key) --------------

def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_setting(conn: sqlite3.Connection, key: str, value: str | None) -> None:
    if value is None or value == "":
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))
    else:
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


def _mask(key: str | None) -> str | None:
    if not key:
        return None
    return key[:3] + "…" + key[-4:] if len(key) > 8 else "…"


@router.get("/settings")
def read_settings(conn: sqlite3.Connection = Depends(db_dependency)):
    from ..logic import DEFAULT_ONBOARDING_TASKS

    key = get_setting(conn, "openai_api_key")
    tpl_raw = get_setting(conn, "onboarding_template")
    onboarding_template = None
    if tpl_raw:
        try:
            onboarding_template = json.loads(tpl_raw)
        except ValueError:
            onboarding_template = None
    if not onboarding_template:
        onboarding_template = [{"title": t, "offset_days": d, "priority": p} for t, d, p in DEFAULT_ONBOARDING_TASKS]
    threshold = get_setting(conn, "ai_import_warning_threshold")
    return {
        "ai_configured": bool(key),
        "openai_api_key_masked": _mask(key),
        "openai_model": get_setting(conn, "openai_model") or DEFAULT_OPENAI_MODEL,
        "onboarding_enabled": get_setting(conn, "onboarding_enabled") != "0",
        "onboarding_template": onboarding_template,
        "ai_clinic_import_enabled": get_setting(conn, "ai_clinic_import_enabled") != "0",
        "ai_clinic_model": get_setting(conn, "ai_clinic_model") or None,
        "ai_import_warning_threshold": int(threshold) if threshold and threshold.isdigit() else None,
        "ai_import_month_count": int(get_setting(conn, f"ai_import_count_{datetime.utcnow():%Y%m}") or 0),
    }


@router.put("/settings")
def write_settings(payload: SettingsIn, conn: sqlite3.Connection = Depends(db_dependency)):
    if payload.openai_api_key is not None:
        set_setting(conn, "openai_api_key", payload.openai_api_key.strip())
    if payload.openai_model is not None:
        set_setting(conn, "openai_model", payload.openai_model.strip() or None)
    for k in ("company_name", "company_contact", "quote_terms", "quote_tax_pct", "quote_valid_days"):
        v = getattr(payload, k, None)
        if v is not None:
            set_setting(conn, k, str(v).strip())
    if payload.onboarding_enabled is not None:
        set_setting(conn, "onboarding_enabled", "1" if payload.onboarding_enabled else "0")
    if payload.ai_clinic_import_enabled is not None:
        set_setting(conn, "ai_clinic_import_enabled", "1" if payload.ai_clinic_import_enabled else "0")
    if payload.ai_clinic_model is not None:
        set_setting(conn, "ai_clinic_model", payload.ai_clinic_model.strip() or None)
    if payload.ai_import_warning_threshold is not None:
        set_setting(conn, "ai_import_warning_threshold", str(payload.ai_import_warning_threshold) if payload.ai_import_warning_threshold > 0 else None)
    if payload.onboarding_template is not None:
        cleaned = [
            {"title": str(i.get("title", "")).strip(),
             "offset_days": int(i.get("offset_days", 0) or 0),
             "priority": i.get("priority") if i.get("priority") in ("high", "medium", "low") else "medium"}
            for i in payload.onboarding_template if str(i.get("title", "")).strip()
        ]
        set_setting(conn, "onboarding_template", json.dumps(cleaned) if cleaned else None)
    return read_settings(conn)


# ---- Business card scanner (OpenAI vision) -----------------------------------

CARD_PROMPT = (
    "You read business cards for a CRM. Extract the person's details and reply with ONLY a JSON object with these keys: "
    "first_name, last_name, title, phone, extension, mobile, fax, email, website, company, address, notes. "
    "Use null for anything not on the card. 'phone' is the main office line, 'mobile' a cell number. "
    "Put any extension (e.g. 'ext. 204', 'x204') in 'extension' as digits only. Keep values exactly as printed."
)

ROLE_HINTS = [
    ("manager", ("manager", "administrator", "director", "coordinator", "supervisor")),
    ("doctor", ("dr.", "dr ", "md", "physician", "doctor", "dds", "dmd", "surgeon", "specialist")),
    ("nurse", ("nurse", "rn", "lpn", "np")),
    ("receptionist", ("reception", "front desk", "medical office assistant", "moa")),
    ("owner", ("owner", "president", "ceo", "founder", "partner", "principal")),
    ("it", ("it ", "technology", "systems", "network")),
]


def guess_role(title: str | None) -> str:
    t = (title or "").lower()
    for role, hints in ROLE_HINTS:
        if any(h in t for h in hints):
            return role
    return "staff"


_UNSUPPORTED_RE = re.compile(r"Unsupported (?:parameter|value)[^']*'([a-zA-Z_.]+)'")


def openai_chat(key: str, body: dict, _attempt: int = 0) -> dict:
    """POST to chat/completions. If the model rejects a parameter (older/newer models differ,
    e.g. max_tokens vs max_completion_tokens, or temperature on reasoning models), drop it and retry."""
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}", "User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "ignore")[:600]
        try:
            detail = json.loads(raw).get("error", {}).get("message", raw)
        except Exception:  # noqa: BLE001
            detail = raw
        m = _UNSUPPORTED_RE.search(detail or "")
        if exc.code == 400 and m and _attempt < 3:
            param = m.group(1).split(".")[0]
            if param in body:
                body = {k: v for k, v in body.items() if k != param}
                if param == "max_tokens" and "max_completion_tokens" not in body:
                    body["max_completion_tokens"] = 800
                return openai_chat(key, body, _attempt + 1)
        raise HTTPException(status_code=502, detail=f"OpenAI error ({exc.code}): {detail}") from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Could not reach OpenAI: {exc}") from exc


@router.post("/contacts/scan-card")
async def scan_business_card(file: UploadFile = File(...), conn: sqlite3.Connection = Depends(db_dependency)):
    key = get_setting(conn, "openai_api_key")
    if not key:
        raise HTTPException(status_code=400, detail="Add your OpenAI API key under Settings → AI to scan business cards.")
    model = get_setting(conn, "openai_model") or DEFAULT_OPENAI_MODEL
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="Empty image")
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image is larger than 20 MB")
    mime = file.content_type if (file.content_type or "").startswith("image/") else "image/jpeg"
    b64 = base64.b64encode(data).decode("ascii")
    body = {
        "model": model,
        "max_completion_tokens": 800,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": CARD_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": "Extract the contact details from this business card."},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"}},
            ]},
        ],
    }
    result = openai_chat(key, body)
    try:
        text = result["choices"][0]["message"]["content"]
        parsed = json.loads(text)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="OpenAI returned an unexpected response") from exc

    def clean(v):
        if v is None:
            return None
        v = str(v).strip()
        return v or None

    contact = {k: clean(parsed.get(k)) for k in ("first_name", "last_name", "title", "phone", "extension", "mobile", "fax", "email", "website", "company", "address", "notes")}
    if contact["extension"]:
        contact["extension"] = re.sub(r"\D", "", contact["extension"]) or None
    contact["role"] = guess_role(contact["title"])
    # Try to match the company to an existing clinic
    match = None
    if contact["company"]:
        from .clinics import find_duplicates

        dups = find_duplicates(conn, contact["company"], contact["address"], None)
        if dups:
            match = {"id": dups[0]["id"], "name": dups[0]["name"]}
    return {"contact": contact, "clinic_match": match, "model": model}


# ---- AI clinic import from a website (OpenAI, server-side) --------------------

CLINIC_DRAFT_PROMPT = (
    "You build clinic records for a medical-IT sales CRM in Calgary, Canada, from a clinic's public website. "
    "Use ONLY information present in the provided page text; never invent details. Reply with ONLY a JSON object with these keys:\n"
    "clinic: {name, address, city, province, postal_code, phone, fax, email, website, clinic_type, provider_count, notes}\n"
    "hours: an object keyed by mon,tue,wed,thu,fri,sat,sun; each value is either null (unknown), the string \"closed\", "
    "or {\"open\":\"HH:MM\",\"close\":\"HH:MM\"} in 24-hour time.\n"
    "sites: a list of ADDITIONAL physical locations (branches) as {name, address}; empty list if only one location.\n"
    "contacts: a list of named people as {first_name, last_name, title, phone, email}; empty list if none are named.\n"
    "confidence: an object mapping each clinic field you filled to an integer 0-100 for how sure you are.\n"
    "Use null for anything not on the site. 'clinic_type' is a short descriptor like 'Family practice' or 'Dental'. "
    "'provider_count' is the number of doctors/practitioners if stated, else null. Keep phone and address exactly as written. "
    "Put a one or two sentence summary of the clinic in clinic.notes."
)

_TAG_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.I | re.S)
_ANGLE_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")


def _fetch_url_text(url: str) -> str:
    """Fetch a public web page server-side and reduce it to visible text."""
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=422, detail="Enter a valid website URL, e.g. https://clinic-example.ca")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            ctype = resp.headers.get("Content-Type", "")
            raw = resp.read(2_000_000)
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Could not open that website ({exc.code}).") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Could not open that website: {exc}") from exc
    charset = "utf-8"
    if "charset=" in ctype:
        charset = ctype.split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
    html = raw.decode(charset, "ignore")
    text = _ANGLE_RE.sub(" ", _TAG_RE.sub(" ", html))
    text = _WS_RE.sub(" ", text.replace("\xa0", " "))
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if len(text) < 40:
        raise HTTPException(status_code=422, detail="That page had no readable text to work from.")
    return text[:12000]


def _draft_clean(v):
    if v is None:
        return None
    v = str(v).strip()
    return v or None


@router.post("/clinics/ai-draft")
def ai_clinic_draft(payload: AiDraftIn, conn: sqlite3.Connection = Depends(db_dependency)):
    if get_setting(conn, "ai_clinic_import_enabled") == "0":
        raise HTTPException(status_code=403, detail={"code": "disabled", "message": "AI clinic import is turned off under Settings → AI."})
    key = get_setting(conn, "openai_api_key")
    if not key:
        raise HTTPException(status_code=400, detail={"code": "no_key", "message": "AI clinic import requires an OpenAI API key."})
    model = get_setting(conn, "ai_clinic_model") or get_setting(conn, "openai_model") or DEFAULT_OPENAI_MODEL
    text = _fetch_url_text(payload.url)
    domain = urllib.parse.urlparse(payload.url if re.match(r"^https?://", payload.url, re.I) else "https://" + payload.url).netloc
    body = {
        "model": model,
        "max_completion_tokens": 1400,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": CLINIC_DRAFT_PROMPT},
            {"role": "user", "content": f"Website: {payload.url}\n\nPage text:\n{text}"},
        ],
    }
    result = openai_chat(key, body)
    try:
        parsed = json.loads(result["choices"][0]["message"]["content"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="OpenAI returned an unexpected response") from exc

    raw_clinic = parsed.get("clinic") or {}
    fields = ["name", "address", "city", "province", "postal_code", "phone", "fax", "email", "website", "clinic_type", "provider_count", "notes"]
    clinic = {k: _draft_clean(raw_clinic.get(k)) for k in fields}
    clinic["website"] = clinic["website"] or (payload.url if re.match(r"^https?://", payload.url, re.I) else "https://" + payload.url)
    try:
        clinic["provider_count"] = int(clinic["provider_count"]) if clinic["provider_count"] else None
    except (TypeError, ValueError):
        clinic["provider_count"] = None

    hours = {}
    for day, val in (parsed.get("hours") or {}).items():
        d = str(day).lower()[:3]
        if d not in ("mon", "tue", "wed", "thu", "fri", "sat", "sun") or val is None:
            continue
        if isinstance(val, str) and val.strip().lower() == "closed":
            hours[d] = {"closed": True, "open": "", "close": ""}
        elif isinstance(val, dict) and (val.get("open") or val.get("close")):
            hours[d] = {"closed": False, "open": _draft_clean(val.get("open")) or "", "close": _draft_clean(val.get("close")) or ""}

    sites = [{"name": _draft_clean(s.get("name")) or "Additional site", "address": _draft_clean(s.get("address"))}
             for s in (parsed.get("sites") or []) if isinstance(s, dict) and (s.get("name") or s.get("address"))][:8]
    contacts = []
    for ct in (parsed.get("contacts") or [])[:12]:
        if not isinstance(ct, dict):
            continue
        first = _draft_clean(ct.get("first_name"))
        if not first:
            continue
        contacts.append({"first_name": first, "last_name": _draft_clean(ct.get("last_name")),
                         "title": _draft_clean(ct.get("title")), "phone": _draft_clean(ct.get("phone")),
                         "email": _draft_clean(ct.get("email")), "role": guess_role(ct.get("title"))})

    raw_conf = parsed.get("confidence") or {}
    meta = {}
    for k in fields:
        if clinic[k] is None:
            continue
        try:
            conf = int(raw_conf.get(k)) if raw_conf.get(k) is not None else None
        except (TypeError, ValueError):
            conf = None
        meta[k] = {"source": domain or "website", "confidence": conf}

    duplicates = find_duplicates(conn, clinic["name"], clinic["address"], clinic["postal_code"])[:5]

    month_key = f"ai_import_count_{datetime.utcnow():%Y%m}"
    count = int(get_setting(conn, month_key) or 0) + 1
    set_setting(conn, month_key, str(count))
    threshold = get_setting(conn, "ai_import_warning_threshold")
    threshold = int(threshold) if threshold and threshold.isdigit() else None

    return {"clinic": clinic, "hours": hours, "sites": sites, "contacts": contacts, "meta": meta,
            "duplicates": [{"id": d["id"], "name": d["name"], "reasons": d.get("reasons")} for d in duplicates],
            "source": domain, "model": model,
            "usage": {"month_count": count, "threshold": threshold, "over": bool(threshold and count > threshold)}}


# ---- Call sheet (printable day plan) ----------------------------------------

@router.get("/call-sheet")
def call_sheet(ids: str | None = None, date: str | None = None, conn: sqlite3.Connection = Depends(db_dependency)):
    """Clinics to visit, in order, with contacts and recent notes. Either explicit ids (route order)
    or every clinic with an appointment on a date (appointment order)."""
    items = []
    appts_by_clinic: dict[int, list[dict]] = defaultdict(list)
    if ids:
        id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    elif date:
        rows = rows_to_list(conn.execute(
            """SELECT a.*, c.first_name AS contact_first_name, c.last_name AS contact_last_name
               FROM appointments a LEFT JOIN contacts c ON c.id = a.contact_id
               WHERE a.status = 'scheduled' AND substr(a.start_time, 1, 10) = ? ORDER BY a.start_time""", (date,)))
        id_list = []
        for a in rows:
            appts_by_clinic[a["clinic_id"]].append(a)
            if a["clinic_id"] not in id_list:
                id_list.append(a["clinic_id"])
    else:
        raise HTTPException(status_code=422, detail="Pass ids= or date=")
    for cid in id_list:
        row = row_to_dict(conn.execute("SELECT * FROM clinics WHERE id = ?", (cid,)).fetchone())
        if not row:
            continue
        c = enrich_clinic(conn, row)
        contacts = rows_to_list(conn.execute(
            """SELECT c.*, cl.phone AS clinic_phone FROM contacts c LEFT JOIN clinics cl ON cl.id = c.clinic_id
               WHERE c.clinic_id = ? OR (c.group_id IS NOT NULL AND c.group_id = ?)
               ORDER BY c.is_primary DESC, c.last_name COLLATE NOCASE""", (cid, c.get("group_id"))))
        for ct in contacts:
            if ct.get("use_main_line") and c.get("phone"):
                ct["phone"] = c["phone"]
            ct["phone_display"] = (ct.get("phone") or "") + (f" ext. {ct['extension']}" if ct.get("extension") else "")
        notes = rows_to_list(conn.execute(
            "SELECT body, created_at, kind FROM clinic_notes WHERE clinic_id = ? ORDER BY created_at DESC LIMIT 3", (cid,)))
        tasks = rows_to_list(conn.execute(
            "SELECT title, due_date, priority FROM tasks WHERE clinic_id = ? AND done = 0 ORDER BY due_date IS NULL, due_date LIMIT 5", (cid,)))
        last_visit = row_to_dict(conn.execute(
            """SELECT title, start_time, outcome FROM appointments WHERE clinic_id = ? AND status NOT IN ('cancelled','no_show')
               AND start_time <= ? ORDER BY start_time DESC LIMIT 1""", (cid, now_iso())).fetchone())
        items.append({
            "clinic": c, "contacts": contacts, "recent_notes": notes, "open_tasks": tasks,
            "appointments": appts_by_clinic.get(cid, []), "last_appointment": last_visit,
            "locations": rows_to_list(conn.execute("SELECT name, address, phone FROM clinic_locations WHERE clinic_id = ?", (cid,))),
        })
    return {"date": date, "items": items, "generated_at": now_iso()}
