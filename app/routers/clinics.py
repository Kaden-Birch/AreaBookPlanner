"""Clinic CRUD, clinic notes, and clinic detail (with contacts + appointments)."""
from __future__ import annotations

import sqlite3

import difflib
import re
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from ..database import db_dependency, row_to_dict, rows_to_list
from ..logic import (
    LEGACY_COLOR_KEYS, LINK_TYPES, LOST_REASONS, QUICK_LOGS, RELATIONSHIP_LABELS, STAGE_LABELS, WON_REASONS,
    enrich_clinic, hours_to_json, log_event, normalize_address, normalize_name, now_iso,
)
from ..schemas import ArchiveIn, ClinicIn, ClinicTicketIn, LinkIn, LocationIn, NoteIn, QuickLogIn, StageChange

router = APIRouter(prefix="/api/clinics", tags=["clinics"])

CLINIC_COLUMNS = [
    "name", "address", "display_address", "city", "province", "postal_code", "hours",
    "phone", "fax", "email", "website",
    "lat", "lng", "relationship", "clinic_type", "emr_system", "it_provider", "provider_count",
    "priority", "tags", "notes", "next_follow_up",
    "stage", "deal_value", "expected_close", "win_probability",
    "outcome_reason", "outcome_notes", "outcome_date", "shorthand", "group_id",
    "mrr", "contract_start", "contract_end", "contract_term_months", "auto_renew",
    "renewal_reminder_days", "competitor_contract_end", "churned_at",
]

LOCATION_COLUMNS = ["name", "address", "city", "province", "postal_code", "phone", "lat", "lng", "notes"]

# @-mentions embedded in note bodies as @[Display Name](c:<contact_id>).
MENTION_RE = re.compile(r"@\[([^\]]+)\]\(c:(\d+)\)")


def _mentionable_contact_ids(conn: sqlite3.Connection, clinic_id: int) -> set[int]:
    """Contacts a clinic's notes may mention: its own contacts + contacts shared across its group.

    Contacts are never mentionable across unrelated clinics, so two people with the same name
    at different clinics stay distinct.
    """
    row = conn.execute("SELECT group_id FROM clinics WHERE id = ?", (clinic_id,)).fetchone()
    gid = row["group_id"] if row else None
    ids = {r[0] for r in conn.execute("SELECT id FROM contacts WHERE clinic_id = ?", (clinic_id,))}
    if gid:
        ids |= {r[0] for r in conn.execute("SELECT id FROM contacts WHERE group_id = ?", (gid,))}
    return ids


def _sanitize_mentions(conn: sqlite3.Connection, clinic_id: int, body: str) -> str:
    """Downgrade any @mention token whose contact isn't mentionable from this clinic to plain text."""
    allowed = _mentionable_contact_ids(conn, clinic_id)
    return MENTION_RE.sub(lambda m: m.group(0) if int(m.group(2)) in allowed else "@" + m.group(1), body or "")


def _parse_mentions(body: str | None) -> list[dict]:
    seen: dict[int, str] = {}
    for m in MENTION_RE.finditer(body or ""):
        seen[int(m.group(2))] = m.group(1)
    return [{"id": k, "name": v} for k, v in seen.items()]


def _note_context(conn: sqlite3.Connection, note: dict) -> dict | None:
    if note.get("appointment_id"):
        r = conn.execute("SELECT title FROM appointments WHERE id = ?", (note["appointment_id"],)).fetchone()
        return {"type": "appointment", "id": note["appointment_id"], "label": r["title"] if r else "appointment"}
    if note.get("task_id"):
        r = conn.execute("SELECT title FROM tasks WHERE id = ?", (note["task_id"],)).fetchone()
        return {"type": "task", "id": note["task_id"], "label": r["title"] if r else "task"}
    if note.get("attachment_id"):
        return {"type": "photo", "id": note["attachment_id"], "label": "photo"}
    if note.get("service_id"):
        r = conn.execute("SELECT name FROM device_services WHERE id = ?", (note["service_id"],)).fetchone()
        return {"type": "service", "id": note["service_id"], "label": r["name"] if r else "service"}
    return None


def _enrich_note(conn: sqlite3.Connection, note: dict) -> dict:
    note["mentions"] = _parse_mentions(note.get("body"))
    note["context"] = _note_context(conn, note)
    return note


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
    # Entering the pipeline (lead -> an open stage) makes the clinic "Interested" on the map;
    # dropping back to a lead demotes it to a plain prospect.
    if data["stage"] in ("prospect", "demo", "proposal") and data["stage"] != prev_stage \
            and data["relationship"] == "prospect":
        data["relationship"] = "interested"
    elif data["stage"] == "lead" and data["stage"] != prev_stage and data["relationship"] == "interested":
        data["relationship"] = "prospect"
    # Churn: a current client moving to Lost is no longer a client on the map.
    if data["stage"] == "lost" and prev_stage == "won" and data["relationship"] == "current_client":
        data["relationship"] = "prospect"
    if data["stage"] in ("won", "lost") and data["stage"] != prev_stage and not data.get("outcome_date"):
        data["outcome_date"] = now_iso()[:10]


def _churn_value(previous: dict | None, data: dict) -> str | None:
    """System-managed churned_at: set when a won client is marked lost, cleared on re-win."""
    if data["stage"] == "won":
        return None
    prev_stage = previous.get("stage") if previous else None
    if data["stage"] == "lost" and prev_stage == "won":
        return data.get("outcome_date") or now_iso()[:10]
    return previous.get("churned_at") if previous else None


def _apply_competitor_followup(data: dict, previous: dict | None) -> None:
    """When a prospect's competitor contract-end is set/changed, seed a follow-up ahead of it."""
    from ..logic import COMPETITOR_FOLLOWUP_LEAD_DAYS

    end = data.get("competitor_contract_end")
    prev_end = previous.get("competitor_contract_end") if previous else None
    if not end or end == prev_end or data.get("relationship") == "current_client":
        return
    today = now_iso()[:10]
    try:
        target = (date.fromisoformat(end[:10]) - timedelta(days=COMPETITOR_FOLLOWUP_LEAD_DAYS)).isoformat()
    except (ValueError, TypeError):
        return
    # If the renewal window has already opened (or the contract already ended), follow up now.
    target = max(target, today)
    # Only pull the follow-up earlier, never push an existing one out.
    if not data.get("next_follow_up") or data["next_follow_up"] > target:
        data["next_follow_up"] = target


def _maybe_create_onboarding(conn: sqlite3.Connection, clinic_id: int) -> int:
    """On the first win, generate the onboarding task checklist. Returns tasks created."""
    from ..logic import DEFAULT_ONBOARDING_TASKS

    enabled = conn.execute("SELECT value FROM settings WHERE key = 'onboarding_enabled'").fetchone()
    if enabled is not None and str(enabled[0]) == "0":
        return 0
    already = conn.execute(
        "SELECT 1 FROM clinic_events WHERE clinic_id = ? AND event_type = 'onboarding'", (clinic_id,)
    ).fetchone()
    if already:
        return 0
    template = _onboarding_template(conn)
    today = date.fromisoformat(now_iso()[:10])
    for title, offset, priority in template:
        due = (today + timedelta(days=int(offset))).isoformat()
        conn.execute(
            "INSERT INTO tasks (clinic_id, title, due_date, priority) VALUES (?, ?, ?, ?)",
            (clinic_id, title, due, priority if priority in ("high", "medium", "low") else "medium"),
        )
    log_event(conn, clinic_id, "onboarding", f"Onboarding checklist created ({len(template)} tasks)")
    return len(template)


def _onboarding_template(conn: sqlite3.Connection) -> list[tuple]:
    from ..logic import DEFAULT_ONBOARDING_TASKS

    row = conn.execute("SELECT value FROM settings WHERE key = 'onboarding_template'").fetchone()
    if row and row[0]:
        import json

        try:
            items = json.loads(row[0])
            out = [(str(i["title"]).strip(), int(i.get("offset_days", 0)), i.get("priority", "medium"))
                   for i in items if str(i.get("title", "")).strip()]
            if out:
                return out
        except (ValueError, KeyError, TypeError):
            pass
    return list(DEFAULT_ONBOARDING_TASKS)


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
            detail, from_value=before.get("stage"), to_value=after["stage"],
        )
    if before.get("relationship") != after.get("relationship"):
        log_event(
            conn, clinic_id, "relationship_change",
            f"Relationship: {RELATIONSHIP_LABELS.get(before.get('relationship'))} → {RELATIONSHIP_LABELS.get(after['relationship'])}",
            from_value=before.get("relationship"), to_value=after["relationship"],
        )


def find_duplicates(conn: sqlite3.Connection, name: str | None, address: str | None, postal_code: str | None,
                    exclude_id: int | None = None) -> list[dict]:
    """Clinics that look like the same place: similar name, or same normalised address."""
    n_name = normalize_name(name)
    n_addr = normalize_address(address)
    n_pc = (postal_code or "").replace(" ", "").upper()
    out = []
    for c in rows_to_list(conn.execute("SELECT id, name, address, postal_code, relationship FROM clinics")):
        if exclude_id is not None and c["id"] == exclude_id:
            continue
        reasons = []
        if n_name:
            ratio = difflib.SequenceMatcher(None, n_name, normalize_name(c["name"])).ratio()
            if ratio >= 0.8 or (len(n_name) >= 4 and (n_name in normalize_name(c["name"]) or normalize_name(c["name"]) in n_name)):
                reasons.append("similar name")
        if n_addr and n_addr == normalize_address(c["address"]):
            reasons.append("same address")
        if n_pc and n_pc == (c["postal_code"] or "").replace(" ", "").upper() and n_name and difflib.SequenceMatcher(None, n_name, normalize_name(c["name"])).ratio() >= 0.5:
            reasons.append("same postal code")
        if reasons:
            out.append({**c, "reasons": reasons})
    return out


@router.get("/duplicates")
def duplicates(
    name: str | None = None, address: str | None = None, postal_code: str | None = None,
    exclude_id: int | None = None, conn: sqlite3.Connection = Depends(db_dependency),
):
    if not name and not address:
        return []
    return find_duplicates(conn, name, address, postal_code, exclude_id)


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
    archived: bool | None = None,
    group_id: int | None = None,
    conn: sqlite3.Connection = Depends(db_dependency),
):
    sql = "SELECT * FROM clinics WHERE 1=1"
    params: list = []
    if q:
        like = f"%{q.strip()}%"
        sql += """ AND (name LIKE ? OR address LIKE ? OR postal_code LIKE ? OR tags LIKE ?
                   OR notes LIKE ? OR emr_system LIKE ? OR clinic_type LIKE ? OR shorthand LIKE ?)"""
        params += [like] * 8
    if archived is not None:
        sql += " AND archived = ?"
        params.append(int(archived))
    if group_id is not None:
        sql += " AND group_id = ?"
        params.append(group_id)
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
        wanted = {LEGACY_COLOR_KEYS.get(k, k) for k in color.split(",")}
        clinics = [c for c in clinics if c["color"] in wanted]
    return clinics


@router.post("", status_code=201)
def create_clinic(payload: ClinicIn, conn: sqlite3.Connection = Depends(db_dependency)):
    data = payload.model_dump()
    data["hours"] = hours_to_json(data.get("hours"))
    _sync_stage_and_relationship(data, None)
    _apply_competitor_followup(data, None)
    data["churned_at"] = _churn_value(None, data)
    cols = ", ".join(CLINIC_COLUMNS)
    marks = ", ".join("?" * len(CLINIC_COLUMNS))
    cur = conn.execute(
        f"INSERT INTO clinics ({cols}) VALUES ({marks})", [data[c] for c in CLINIC_COLUMNS]
    )
    log_event(conn, cur.lastrowid, "created", "Clinic added",
              f"{STAGE_LABELS[data['stage']]} · {RELATIONSHIP_LABELS[data['relationship']]}")
    if data["stage"] == "won":
        _maybe_create_onboarding(conn, cur.lastrowid)
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
    clinic["note_log"] = [
        _enrich_note(conn, n) for n in rows_to_list(
            conn.execute(
                "SELECT * FROM clinic_notes WHERE clinic_id = ? ORDER BY created_at DESC, id DESC",
                (clinic_id,),
            )
        )
    ]
    clinic["tasks"] = rows_to_list(
        conn.execute(
            "SELECT * FROM tasks WHERE clinic_id = ? ORDER BY done ASC, due_date IS NULL, due_date ASC, id DESC",
            (clinic_id,),
        )
    )
    clinic["timeline"] = build_timeline(conn, clinic_id)
    clinic["locations"] = rows_to_list(
        conn.execute("SELECT * FROM clinic_locations WHERE clinic_id = ? ORDER BY name COLLATE NOCASE", (clinic_id,))
    )
    clinic["links"] = list_links_for(conn, clinic_id)
    clinic["attachments"] = rows_to_list(
        conn.execute("SELECT * FROM attachments WHERE clinic_id = ? ORDER BY created_at DESC, id DESC", (clinic_id,))
    )
    for a in clinic["attachments"]:
        a["note_count"] = conn.execute(
            "SELECT COUNT(*) FROM clinic_notes WHERE attachment_id = ?", (a["id"],)).fetchone()[0]
        a["origin"] = None
        if a.get("note_id"):
            n = row_to_dict(conn.execute("SELECT * FROM clinic_notes WHERE id = ?", (a["note_id"],)).fetchone())
            if n:
                a["origin"] = _note_context(conn, n) or {"type": "note", "id": n["id"], "label": "note"}
    from .devices import _summary as device_summary

    clinic["equipment"] = device_summary(conn, clinic_id)
    clinic["quotes"] = rows_to_list(conn.execute(
        "SELECT id, title, status, monthly_total, onetime_total, valid_until, created_at, pricing_mode FROM quotes WHERE clinic_id = ? ORDER BY created_at DESC, id DESC", (clinic_id,)))
    for q in clinic["quotes"]:
        q["number"] = f"Q-{(q['created_at'] or '')[:4]}-{q['id']:04d}"
    clinic["invoices"] = rows_to_list(conn.execute(
        "SELECT id, title, status, total, issue_date, due_date, ticket_url, created_at FROM invoices WHERE clinic_id = ? ORDER BY created_at DESC, id DESC", (clinic_id,)))
    for inv in clinic["invoices"]:
        inv["number"] = f"INV-{(inv['created_at'] or '')[:4]}-{inv['id']:04d}"
    clinic["tickets"] = rows_to_list(conn.execute(
        """SELECT t.*, d.name AS device_name FROM clinic_tickets t LEFT JOIN devices d ON d.id = t.device_id
           WHERE t.clinic_id = ? ORDER BY t.ticket_at DESC, t.id DESC""", (clinic_id,)))
    clinic["group"] = None
    clinic["group_members"] = []
    if clinic.get("group_id"):
        clinic["group"] = row_to_dict(conn.execute("SELECT * FROM clinic_groups WHERE id = ?", (clinic["group_id"],)).fetchone())
        clinic["group_members"] = [
            enrich_clinic(conn, m) for m in rows_to_list(conn.execute(
                "SELECT * FROM clinics WHERE group_id = ? AND id <> ? ORDER BY name COLLATE NOCASE", (clinic["group_id"], clinic_id)))
        ]
        # Contacts shared across the group show up on every member clinic.
        shared = rows_to_list(conn.execute(
            """SELECT c.*, cl.name AS clinic_name FROM contacts c LEFT JOIN clinics cl ON cl.id = c.clinic_id
               WHERE c.group_id = ? AND (c.clinic_id IS NULL OR c.clinic_id <> ?)
               ORDER BY c.last_name COLLATE NOCASE, c.first_name COLLATE NOCASE""", (clinic["group_id"], clinic_id)))
        for ct in shared:
            ct["shared"] = True
        clinic["contacts"] += shared
    for ct in clinic["contacts"]:
        ct.setdefault("shared", bool(ct.get("group_id")))
        if ct.get("use_main_line") and clinic.get("phone"):
            ct["phone"] = clinic["phone"]
        ct["phone_display"] = (ct.get("phone") or "") + (f" ext. {ct['extension']}" if ct.get("extension") else "")
    return clinic


def list_links_for(conn: sqlite3.Connection, clinic_id: int) -> list[dict]:
    rows = rows_to_list(conn.execute(
        """SELECT l.*, CASE WHEN l.clinic_id = ? THEN l.other_clinic_id ELSE l.clinic_id END AS other_id
           FROM clinic_links l WHERE l.clinic_id = ? OR l.other_clinic_id = ? ORDER BY l.id""",
        (clinic_id, clinic_id, clinic_id)))
    out = []
    for r in rows:
        other = row_to_dict(conn.execute("SELECT id, name, relationship, address, shorthand FROM clinics WHERE id = ?", (r["other_id"],)).fetchone())
        if not other:
            continue
        other = enrich_clinic(conn, {**other, "stage": "prospect", "tags": None, "deal_value": None, "win_probability": None})
        out.append({
            "id": r["id"], "link_type": r["link_type"], "link_label": LINK_TYPES.get(r["link_type"], r["link_type"]),
            "notes": r["notes"], "other": {"id": other["id"], "name": other["name"], "color": other["color"],
                                          "address": other["address"], "shorthand": other["shorthand"]},
        })
    return out


def build_timeline(conn: sqlite3.Connection, clinic_id: int) -> list[dict]:
    """Merge notes, appointments, tasks and status events into one dated feed."""
    items: list[dict] = []
    for n in rows_to_list(conn.execute("SELECT * FROM clinic_notes WHERE clinic_id = ?", (clinic_id,))):
        title = {"quick": "Quick log", "email": "Email sent"}.get(n.get("kind") or "note", "Note")
        if n.get("author"):
            title += f" · {n['author']}"
        items.append({"type": "note", "at": n["created_at"], "id": n["id"], "title": title, "body": n["body"],
                      "kind": n.get("kind") or "note", "context": _note_context(conn, n), "mentions": _parse_mentions(n["body"])})
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
        # Equipment/topology changes are their own section — keep them out of the activity feed.
        if e["event_type"] == "equipment":
            continue
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
        data["outcome_date"] = payload.outcome_date or now_iso()[:10]
    else:
        data["outcome_reason"] = None
        data["outcome_notes"] = None
        data["outcome_date"] = None
    _sync_stage_and_relationship(data, before)
    if data["stage"] != "won":
        data["archived"] = 0
        data["archived_at"] = None
    churned_at = _churn_value(before, data)
    conn.execute(
        """UPDATE clinics SET stage = ?, relationship = ?, outcome_reason = ?, outcome_notes = ?,
           outcome_date = ?, archived = ?, archived_at = ?, churned_at = ?, updated_at = ? WHERE id = ?""",
        (data["stage"], data["relationship"], data["outcome_reason"], data["outcome_notes"],
         data["outcome_date"], int(bool(data.get("archived"))), data.get("archived_at"), churned_at, now_iso(), clinic_id),
    )
    _log_changes(conn, clinic_id, before, data)
    if data["stage"] == "won" and before.get("stage") != "won":
        _maybe_create_onboarding(conn, clinic_id)
    if churned_at and not before.get("churned_at"):
        log_event(conn, clinic_id, "churn", "Client churned", payload.outcome_notes)
    return enrich_clinic(conn, _get_clinic_or_404(conn, clinic_id))


@router.patch("/{clinic_id}/archive")
def archive_clinic(clinic_id: int, payload: ArchiveIn, conn: sqlite3.Connection = Depends(db_dependency)):
    """Dismiss a won clinic from the pipeline board (it stays a client everywhere else)."""
    _get_clinic_or_404(conn, clinic_id)
    conn.execute(
        "UPDATE clinics SET archived = ?, archived_at = ?, updated_at = ? WHERE id = ?",
        (int(payload.archived), now_iso() if payload.archived else None, now_iso(), clinic_id),
    )
    return enrich_clinic(conn, _get_clinic_or_404(conn, clinic_id))


# ---- Quick log ------------------------------------------------------------

@router.post("/{clinic_id}/quick-log", status_code=201)
def quick_log(clinic_id: int, payload: QuickLogIn, conn: sqlite3.Connection = Depends(db_dependency)):
    _get_clinic_or_404(conn, clinic_id)
    text = QUICK_LOGS.get(payload.preset)
    if text is None:
        raise HTTPException(status_code=422, detail="Unknown quick-log preset")
    if payload.detail:
        text += f" — {payload.detail}"
    cur = conn.execute(
        "INSERT INTO clinic_notes (clinic_id, body, author, kind) VALUES (?, ?, ?, 'quick')",
        (clinic_id, text, payload.author),
    )
    conn.execute("UPDATE clinics SET updated_at = ? WHERE id = ?", (now_iso(), clinic_id))
    return row_to_dict(conn.execute("SELECT * FROM clinic_notes WHERE id = ?", (cur.lastrowid,)).fetchone())


# ---- Locations (sister / secondary sites) ---------------------------------

@router.get("/{clinic_id}/locations")
def list_locations(clinic_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    _get_clinic_or_404(conn, clinic_id)
    return rows_to_list(conn.execute("SELECT * FROM clinic_locations WHERE clinic_id = ? ORDER BY name COLLATE NOCASE", (clinic_id,)))


@router.post("/{clinic_id}/locations", status_code=201)
def add_location(clinic_id: int, payload: LocationIn, conn: sqlite3.Connection = Depends(db_dependency)):
    _get_clinic_or_404(conn, clinic_id)
    data = payload.model_dump()
    cols = ", ".join(["clinic_id", *LOCATION_COLUMNS])
    marks = ", ".join("?" * (len(LOCATION_COLUMNS) + 1))
    cur = conn.execute(f"INSERT INTO clinic_locations ({cols}) VALUES ({marks})", [clinic_id] + [data[c] for c in LOCATION_COLUMNS])
    log_event(conn, clinic_id, "location", f"Location added: {data['name']}", data.get("address"))
    return row_to_dict(conn.execute("SELECT * FROM clinic_locations WHERE id = ?", (cur.lastrowid,)).fetchone())


@router.put("/{clinic_id}/locations/{loc_id}")
def update_location_site(clinic_id: int, loc_id: int, payload: LocationIn, conn: sqlite3.Connection = Depends(db_dependency)):
    data = payload.model_dump()
    sets = ", ".join(f"{c} = ?" for c in LOCATION_COLUMNS)
    cur = conn.execute(f"UPDATE clinic_locations SET {sets} WHERE id = ? AND clinic_id = ?", [data[c] for c in LOCATION_COLUMNS] + [loc_id, clinic_id])
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Location not found")
    return row_to_dict(conn.execute("SELECT * FROM clinic_locations WHERE id = ?", (loc_id,)).fetchone())


@router.delete("/{clinic_id}/locations/{loc_id}", status_code=204)
def delete_location(clinic_id: int, loc_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    cur = conn.execute("DELETE FROM clinic_locations WHERE id = ? AND clinic_id = ?", (loc_id, clinic_id))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Location not found")
    return None


# ---- Links (referral / network) --------------------------------------------

@router.get("/{clinic_id}/links")
def list_links(clinic_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    _get_clinic_or_404(conn, clinic_id)
    return list_links_for(conn, clinic_id)


@router.post("/{clinic_id}/links", status_code=201)
def add_link(clinic_id: int, payload: LinkIn, conn: sqlite3.Connection = Depends(db_dependency)):
    _get_clinic_or_404(conn, clinic_id)
    other = _get_clinic_or_404(conn, payload.other_clinic_id)
    if payload.other_clinic_id == clinic_id:
        raise HTTPException(status_code=422, detail="A clinic cannot be linked to itself")
    if payload.link_type not in LINK_TYPES:
        raise HTTPException(status_code=422, detail="Unknown link type")
    exists = conn.execute(
        "SELECT 1 FROM clinic_links WHERE (clinic_id = ? AND other_clinic_id = ?) OR (clinic_id = ? AND other_clinic_id = ?)",
        (clinic_id, payload.other_clinic_id, payload.other_clinic_id, clinic_id)).fetchone()
    if exists:
        raise HTTPException(status_code=422, detail="These clinics are already linked")
    conn.execute(
        "INSERT INTO clinic_links (clinic_id, other_clinic_id, link_type, notes) VALUES (?, ?, ?, ?)",
        (clinic_id, payload.other_clinic_id, payload.link_type, payload.notes))
    label = LINK_TYPES[payload.link_type]
    log_event(conn, clinic_id, "link", f"Linked to {other['name']} ({label})", payload.notes)
    log_event(conn, payload.other_clinic_id, "link", f"Linked to {_get_clinic_or_404(conn, clinic_id)['name']} ({label})", payload.notes)
    return list_links_for(conn, clinic_id)


@router.delete("/{clinic_id}/links/{link_id}", status_code=204)
def delete_link(clinic_id: int, link_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    cur = conn.execute("DELETE FROM clinic_links WHERE id = ? AND (clinic_id = ? OR other_clinic_id = ?)", (link_id, clinic_id, clinic_id))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Link not found")
    return None


@router.put("/{clinic_id}")
def update_clinic(clinic_id: int, payload: ClinicIn, conn: sqlite3.Connection = Depends(db_dependency)):
    before = _get_clinic_or_404(conn, clinic_id)
    data = payload.model_dump()
    data["hours"] = hours_to_json(data.get("hours"))
    _sync_stage_and_relationship(data, before)
    _apply_competitor_followup(data, before)
    data["churned_at"] = _churn_value(before, data)
    sets = ", ".join(f"{c} = ?" for c in CLINIC_COLUMNS)
    conn.execute(
        f"UPDATE clinics SET {sets}, updated_at = ? WHERE id = ?",
        [data[c] for c in CLINIC_COLUMNS] + [now_iso(), clinic_id],
    )
    _log_changes(conn, clinic_id, before, data)
    if data["stage"] == "won" and before.get("stage") != "won":
        _maybe_create_onboarding(conn, clinic_id)
    if data["churned_at"] and not before.get("churned_at"):
        log_event(conn, clinic_id, "churn", "Client churned", data.get("outcome_notes"))
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
    return [
        _enrich_note(conn, n) for n in rows_to_list(
            conn.execute(
                "SELECT * FROM clinic_notes WHERE clinic_id = ? ORDER BY created_at DESC, id DESC",
                (clinic_id,),
            )
        )
    ]


@router.post("/{clinic_id}/notes", status_code=201)
def add_note(clinic_id: int, payload: NoteIn, conn: sqlite3.Connection = Depends(db_dependency)):
    _get_clinic_or_404(conn, clinic_id)
    # A note may be attached to an appointment, task or photo of THIS clinic.
    if payload.appointment_id and conn.execute(
            "SELECT 1 FROM appointments WHERE id = ? AND clinic_id = ?", (payload.appointment_id, clinic_id)).fetchone() is None:
        raise HTTPException(status_code=422, detail="Appointment does not belong to this clinic")
    if payload.task_id and conn.execute(
            "SELECT 1 FROM tasks WHERE id = ? AND clinic_id = ?", (payload.task_id, clinic_id)).fetchone() is None:
        raise HTTPException(status_code=422, detail="Task does not belong to this clinic")
    if payload.attachment_id and conn.execute(
            "SELECT 1 FROM attachments WHERE id = ? AND clinic_id = ?", (payload.attachment_id, clinic_id)).fetchone() is None:
        raise HTTPException(status_code=422, detail="Photo does not belong to this clinic")
    if payload.service_id and conn.execute(
            """SELECT 1 FROM device_services s JOIN devices d ON d.id = s.device_id
               WHERE s.id = ? AND d.clinic_id = ?""", (payload.service_id, clinic_id)).fetchone() is None:
        raise HTTPException(status_code=422, detail="Service does not belong to this clinic")
    body = _sanitize_mentions(conn, clinic_id, payload.body.strip())
    cur = conn.execute(
        "INSERT INTO clinic_notes (clinic_id, body, author, kind, appointment_id, task_id, attachment_id, service_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (clinic_id, body, payload.author, payload.kind if payload.kind in ("note", "quick", "email", "call") else "note",
         payload.appointment_id, payload.task_id, payload.attachment_id, payload.service_id),
    )
    conn.execute("UPDATE clinics SET updated_at = ? WHERE id = ?", (now_iso(), clinic_id))
    return _enrich_note(conn, row_to_dict(conn.execute("SELECT * FROM clinic_notes WHERE id = ?", (cur.lastrowid,)).fetchone()))


@router.get("/{clinic_id}/attachments/{att_id}/notes")
def list_photo_notes(clinic_id: int, att_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    """Notes attached directly to one photo (for the photo detail view)."""
    return [
        _enrich_note(conn, n) for n in rows_to_list(conn.execute(
            "SELECT * FROM clinic_notes WHERE clinic_id = ? AND attachment_id = ? ORDER BY created_at ASC, id ASC",
            (clinic_id, att_id)))
    ]


@router.delete("/{clinic_id}/notes/{note_id}", status_code=204)
def delete_note(clinic_id: int, note_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    cur = conn.execute("DELETE FROM clinic_notes WHERE id = ? AND clinic_id = ?", (note_id, clinic_id))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Note not found")
    return None


# ---- Tickets (e.g. SyncroMSP) ---------------------------------------------

def _ticket_detail(conn: sqlite3.Connection, ticket_id: int) -> dict:
    return row_to_dict(conn.execute(
        """SELECT t.*, d.name AS device_name FROM clinic_tickets t LEFT JOIN devices d ON d.id = t.device_id
           WHERE t.id = ?""", (ticket_id,)).fetchone())


@router.get("/{clinic_id}/tickets")
def list_tickets(clinic_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    _get_clinic_or_404(conn, clinic_id)
    return rows_to_list(conn.execute(
        """SELECT t.*, d.name AS device_name FROM clinic_tickets t LEFT JOIN devices d ON d.id = t.device_id
           WHERE t.clinic_id = ? ORDER BY t.ticket_at DESC, t.id DESC""", (clinic_id,)))


@router.post("/{clinic_id}/tickets", status_code=201)
def add_ticket(clinic_id: int, payload: ClinicTicketIn, conn: sqlite3.Connection = Depends(db_dependency)):
    _get_clinic_or_404(conn, clinic_id)
    device_id = payload.device_id
    if device_id is not None and conn.execute(
            "SELECT 1 FROM devices WHERE id = ? AND clinic_id = ?", (device_id, clinic_id)).fetchone() is None:
        device_id = None
    if device_id is None and payload.device_name:
        from .devices import ensure_device_by_name
        device_id = ensure_device_by_name(conn, clinic_id, payload.device_name)
    at = payload.ticket_at or now_iso()
    cur = conn.execute(
        "INSERT INTO clinic_tickets (clinic_id, device_id, title, url, ticket_at, notes) VALUES (?, ?, ?, ?, ?, ?)",
        (clinic_id, device_id, payload.title, payload.url, at, payload.notes))
    return _ticket_detail(conn, cur.lastrowid)


@router.delete("/{clinic_id}/tickets/{ticket_id}", status_code=204)
def delete_ticket(clinic_id: int, ticket_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    cur = conn.execute("DELETE FROM clinic_tickets WHERE id = ? AND clinic_id = ?", (ticket_id, clinic_id))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return None
