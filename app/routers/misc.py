"""Geocoding, dashboard, metadata, and import/export endpoints."""
from __future__ import annotations

import csv
import io
import json
import math
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response

from ..database import db_dependency, rows_to_list
from ..logic import (
    COLOR_LABELS, DEFAULT_PROBABILITY, LEGACY_COLOR_KEYS, LINK_TYPES, LOST_REASONS, OPEN_STAGES, PIPELINE_STAGES,
    QUICK_LOGS, RELATIONSHIP_LABELS, REMINDER_OPTIONS, STAGE_LABELS, WON_REASONS, enrich_clinic, now_iso,
)
from ..schemas import RouteRequest
from .appointments import STATUS_LABELS, TYPE_LABELS
from .contacts import ROLE_LABELS

router = APIRouter(prefix="/api", tags=["misc"])

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "AreaBookPlanner/1.0 (local clinic planner)"

# Calgary bounding box (west, south, east, north) used to bias geocoding results.
CALGARY_VIEWBOX = "-114.32,50.84,-113.86,51.22"

CLINIC_TYPES = [
    "Family practice", "Walk-in clinic", "Medical centre", "Specialist", "Dental",
    "Physiotherapy", "Chiropractic", "Optometry", "Pharmacy", "Mental health",
    "Veterinary", "Other",
]


@router.get("/meta")
def meta():
    return {
        "relationships": RELATIONSHIP_LABELS,
        "colors": COLOR_LABELS,
        "legacy_colors": LEGACY_COLOR_KEYS,
        "contact_roles": ROLE_LABELS,
        "appointment_types": TYPE_LABELS,
        "appointment_statuses": STATUS_LABELS,
        "clinic_types": CLINIC_TYPES,
        "stages": STAGE_LABELS,
        "pipeline_stages": list(PIPELINE_STAGES),
        "open_stages": list(OPEN_STAGES),
        "default_probability": DEFAULT_PROBABILITY,
        "won_reasons": WON_REASONS,
        "lost_reasons": LOST_REASONS,
        "link_types": LINK_TYPES,
        "quick_logs": QUICK_LOGS,
        "reminder_options": REMINDER_OPTIONS,
        "map_default": {"lat": 51.0447, "lng": -114.0719, "zoom": 11},
    }


@router.get("/geocode")
def geocode(q: str = Query(min_length=3)):
    """Look up an address via OpenStreetMap Nominatim. Biased toward Calgary."""
    params = {
        "q": q,
        "format": "jsonv2",
        "limit": 5,
        "addressdetails": 1,
        "countrycodes": "ca",
        "viewbox": CALGARY_VIEWBOX,
        "bounded": 0,
    }
    url = f"{NOMINATIM_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            results = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"Geocoding service unavailable: {exc.reason}") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Geocoding failed: {exc}") from exc

    out = []
    for r in results:
        addr = r.get("address", {})
        out.append(
            {
                "display_name": r.get("display_name"),
                "lat": float(r["lat"]),
                "lng": float(r["lon"]),
                "postal_code": addr.get("postcode"),
                "city": addr.get("city") or addr.get("town") or addr.get("municipality"),
                "street": " ".join(p for p in [addr.get("house_number"), addr.get("road")] if p) or None,
            }
        )
    return out


@router.get("/dashboard")
def dashboard(conn: sqlite3.Connection = Depends(db_dependency)):
    clinics = [enrich_clinic(conn, c) for c in rows_to_list(conn.execute("SELECT * FROM clinics"))]
    today = date.today()
    now = now_iso()
    week_end = (datetime.now() + timedelta(days=7)).isoformat()

    by_color = {k: 0 for k in COLOR_LABELS}
    by_relationship = {k: 0 for k in RELATIONSHIP_LABELS}
    for c in clinics:
        by_color[c["color"]] += 1
        by_relationship[c["relationship"]] += 1

    upcoming = rows_to_list(
        conn.execute(
            """SELECT a.id, a.title, a.start_time, a.appt_type, a.clinic_id, cl.name AS clinic_name
               FROM appointments a JOIN clinics cl ON cl.id = a.clinic_id
               WHERE a.status = 'scheduled' AND a.start_time >= ? AND a.start_time < ?
               ORDER BY a.start_time ASC LIMIT 20""",
            (now, week_end),
        )
    )
    needs_outcome = rows_to_list(
        conn.execute(
            """SELECT a.id, a.title, a.start_time, a.appt_type, a.clinic_id, cl.name AS clinic_name
               FROM appointments a JOIN clinics cl ON cl.id = a.clinic_id
               WHERE a.status = 'scheduled' AND a.start_time < ?
               ORDER BY a.start_time DESC LIMIT 20""",
            (now,),
        )
    )
    follow_ups = [
        {
            "id": c["id"], "name": c["name"], "next_follow_up": c["next_follow_up"],
            "color": c["color"], "priority": c["priority"],
            "overdue": c["next_follow_up"] < today.isoformat(),
        }
        for c in clinics
        if c["next_follow_up"] and c["next_follow_up"] <= (today + timedelta(days=7)).isoformat()
        and c["relationship"] != "do_not_contact"
    ]
    follow_ups.sort(key=lambda x: x["next_follow_up"])

    # Clients are serviced, not "visited" - only prospects/interested show up here.
    stale = [
        {"id": c["id"], "name": c["name"], "last_visit": c["last_visit"], "color": c["color"], "priority": c["priority"]}
        for c in clinics
        if c["color"] == "stale" or (c["relationship"] == "interested" and (
            not c["last_visit"] or c["last_visit"] < (datetime.now() - timedelta(days=90)).isoformat()))
    ]
    stale.sort(key=lambda x: (x["last_visit"] or ""))

    unmapped = [{"id": c["id"], "name": c["name"]} for c in clinics if c["lat"] is None or c["lng"] is None]

    # Leads: added to the book but not yet contacted (pre-pipeline). Oldest first so the
    # ones that have been waiting longest surface at the top.
    leads = [
        {"id": c["id"], "name": c["name"], "color": c["color"], "priority": c["priority"],
         "created_at": c["created_at"], "next_follow_up": c["next_follow_up"]}
        for c in clinics
        if c["stage"] == "lead" and not c["archived"] and c["relationship"] != "do_not_contact"
    ]
    leads.sort(key=lambda x: (x["created_at"] or ""))

    pipeline = {s: {"count": 0, "value": 0.0, "weighted": 0.0} for s in STAGE_LABELS}
    for c in clinics:
        p = pipeline[c["stage"]]
        p["count"] += 1
        p["value"] += c["deal_value"] or 0
        p["weighted"] += c["weighted_value"]
    year = today.isoformat()[:4]
    won_this_year = sum((c["deal_value"] or 0) for c in clinics if c["stage"] == "won" and (c["outcome_date"] or "")[:4] == year)
    outcome_reasons = {"won": {}, "lost": {}}
    for c in clinics:
        if c["stage"] in ("won", "lost") and c["outcome_reason"]:
            labels = WON_REASONS if c["stage"] == "won" else LOST_REASONS
            label = labels.get(c["outcome_reason"], c["outcome_reason"])
            outcome_reasons[c["stage"]][label] = outcome_reasons[c["stage"]].get(label, 0) + 1

    tasks_due = rows_to_list(
        conn.execute(
            """SELECT t.id, t.title, t.due_date, t.priority, t.clinic_id, cl.name AS clinic_name
               FROM tasks t LEFT JOIN clinics cl ON cl.id = t.clinic_id
               WHERE t.done = 0 AND (t.due_date IS NULL OR t.due_date <= ?)
               ORDER BY t.due_date IS NULL, t.due_date ASC,
                        CASE t.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END LIMIT 25""",
            ((today + timedelta(days=7)).isoformat(),),
        )
    )
    for t in tasks_due:
        t["overdue"] = bool(t["due_date"]) and t["due_date"] < today.isoformat()
        t["due_today"] = t["due_date"] == today.isoformat()

    closing_soon = [
        {"id": c["id"], "name": c["name"], "stage": c["stage"], "stage_label": c["stage_label"],
         "deal_value": c["deal_value"], "expected_close": c["expected_close"], "color": c["color"]}
        for c in clinics
        if c["stage"] in OPEN_STAGES and c["expected_close"] and c["expected_close"] <= (today + timedelta(days=30)).isoformat()
    ]
    closing_soon.sort(key=lambda x: x["expected_close"])

    return {
        "archived_won": sum(1 for c in clinics if c["stage"] == "won" and c["archived"]),
        "pipeline": pipeline,
        "forecast": {
            "open_value": round(sum(p["value"] for s, p in pipeline.items() if s in OPEN_STAGES), 2),
            "weighted_value": round(sum(p["weighted"] for p in pipeline.values()), 2),
            "won_value_this_year": round(won_this_year, 2),
            "open_deals": sum(p["count"] for s, p in pipeline.items() if s in OPEN_STAGES),
        },
        "outcome_reasons": outcome_reasons,
        "tasks_due": tasks_due,
        "closing_soon": closing_soon,
        "totals": {
            "clinics": len(clinics),
            "contacts": conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0],
            "appointments_upcoming": conn.execute(
                "SELECT COUNT(*) FROM appointments WHERE status='scheduled' AND start_time >= ?", (now,)
            ).fetchone()[0],
            "tasks_open": conn.execute("SELECT COUNT(*) FROM tasks WHERE done = 0").fetchone()[0],
            "visits_this_month": conn.execute(
                """SELECT COUNT(*) FROM appointments WHERE status NOT IN ('cancelled','no_show')
                   AND appt_type IN ('visit','demo','install','support')
                   AND start_time >= ? AND start_time <= ?""",
                (today.replace(day=1).isoformat(), now),
            ).fetchone()[0],
        },
        "by_color": by_color,
        "by_relationship": by_relationship,
        "upcoming": upcoming,
        "needs_outcome": needs_outcome,
        "follow_ups": follow_ups,
        "overdue_follow_ups": sum(1 for c in clinics if c["follow_up_overdue"]),
        "stale": stale[:20],
        "unmapped": unmapped,
        "leads": leads[:20],
        "leads_count": len(leads),
    }


# ---- Export ----------------------------------------------------------------

def _csv_response(rows: list[dict], columns: list[str], filename: str) -> Response:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/clinics.csv")
def export_clinics(conn: sqlite3.Connection = Depends(db_dependency)):
    clinics = [enrich_clinic(conn, c) for c in rows_to_list(conn.execute("SELECT * FROM clinics ORDER BY name COLLATE NOCASE"))]
    cols = [
        "id", "name", "shorthand", "relationship_label", "color_label", "address", "city", "province", "postal_code",
        "phone", "fax", "email", "website", "clinic_type", "emr_system", "it_provider", "provider_count",
        "priority", "tags", "stage_label", "deal_value", "expected_close", "effective_probability",
        "outcome_reason", "outcome_date", "last_visit", "next_follow_up", "lat", "lng", "notes",
    ]
    return _csv_response(clinics, cols, "clinics.csv")


@router.get("/export/contacts.csv")
def export_contacts(conn: sqlite3.Connection = Depends(db_dependency)):
    rows = rows_to_list(
        conn.execute(
            """SELECT c.*, cl.name AS clinic_name FROM contacts c LEFT JOIN clinics cl ON cl.id = c.clinic_id
               ORDER BY c.last_name COLLATE NOCASE, c.first_name COLLATE NOCASE"""
        )
    )
    for r in rows:
        r["role"] = ROLE_LABELS.get(r["role"], r["role"])
    cols = ["id", "first_name", "last_name", "role", "title", "clinic_name", "phone", "mobile", "email", "is_primary", "notes"]
    return _csv_response(rows, cols, "contacts.csv")


def _ics_escape(s: str | None) -> str:
    return (s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_dt(value: str) -> str:
    return datetime.fromisoformat(value).strftime("%Y%m%dT%H%M%S")


@router.get("/export/appointments.ics")
def export_ics(conn: sqlite3.Connection = Depends(db_dependency)):
    """iCalendar feed so appointments can be imported into Outlook / Google Calendar."""
    rows = rows_to_list(
        conn.execute(
            """SELECT a.*, cl.name AS clinic_name, cl.address AS clinic_address
               FROM appointments a JOIN clinics cl ON cl.id = a.clinic_id
               WHERE a.status <> 'cancelled' ORDER BY a.start_time"""
        )
    )
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//AreaBookPlanner//EN", "CALSCALE:GREGORIAN"]
    for r in rows:
        start = _ics_dt(r["start_time"])
        end = _ics_dt(r["end_time"]) if r["end_time"] else _ics_dt(
            (datetime.fromisoformat(r["start_time"]) + timedelta(hours=1)).isoformat()
        )
        lines += [
            "BEGIN:VEVENT",
            f"UID:areabook-appt-{r['id']}@local",
            f"DTSTAMP:{_ics_dt(now_iso())}",
            f"DTSTART:{start}",
            f"DTEND:{end}",
            f"SUMMARY:{_ics_escape(r['title'] + ' - ' + r['clinic_name'])}",
            f"LOCATION:{_ics_escape(r['location'] or r['clinic_address'])}",
            f"DESCRIPTION:{_ics_escape(r['notes'])}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return PlainTextResponse(
        "\r\n".join(lines) + "\r\n",
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="appointments.ics"'},
    )


@router.get("/export/backup.json")
def export_backup(conn: sqlite3.Connection = Depends(db_dependency)):
    data = {
        "exported_at": now_iso(),
        "version": 1,
        "clinics": rows_to_list(conn.execute("SELECT * FROM clinics")),
        "contacts": rows_to_list(conn.execute("SELECT * FROM contacts")),
        "appointments": rows_to_list(conn.execute("SELECT * FROM appointments")),
        "clinic_notes": rows_to_list(conn.execute("SELECT * FROM clinic_notes")),
        "tasks": rows_to_list(conn.execute("SELECT * FROM tasks")),
        "clinic_events": rows_to_list(conn.execute("SELECT * FROM clinic_events")),
        "clinic_groups": rows_to_list(conn.execute("SELECT * FROM clinic_groups")),
        "clinic_locations": rows_to_list(conn.execute("SELECT * FROM clinic_locations")),
        "clinic_links": rows_to_list(conn.execute("SELECT * FROM clinic_links")),
        "attachments": rows_to_list(conn.execute("SELECT * FROM attachments")),
        "email_templates": rows_to_list(conn.execute("SELECT * FROM email_templates")),
        "saved_views": rows_to_list(conn.execute("SELECT * FROM saved_views")),
        "devices": rows_to_list(conn.execute("SELECT * FROM devices")),
        "device_tickets": rows_to_list(conn.execute("SELECT * FROM device_tickets")),
        "device_links": rows_to_list(conn.execute("SELECT * FROM device_links")),
        "quotes": rows_to_list(conn.execute("SELECT * FROM quotes")),
        "price_book": rows_to_list(conn.execute("SELECT * FROM price_book")),
    }
    return Response(
        content=json.dumps(data, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="areabook-backup.json"'},
    )


@router.post("/import/backup")
def import_backup(data: dict, replace: bool = False, conn: sqlite3.Connection = Depends(db_dependency)):
    """Restore a backup produced by /api/export/backup.json.

    With replace=true all existing data is wiped first and IDs are preserved.
    Otherwise records are appended with new IDs (relations are remapped).
    """
    if data.get("version") != 1:
        raise HTTPException(status_code=422, detail="Unrecognised backup format")
    tables = ["clinic_groups", "clinics", "contacts", "appointments", "clinic_notes", "tasks", "clinic_events",
              "clinic_locations", "clinic_links", "attachments", "email_templates", "saved_views", "devices", "device_links", "device_tickets", "quotes"]
    if replace:
        for t in reversed(tables):
            conn.execute(f"DELETE FROM {t}")
        if data.get("price_book"):
            conn.execute("DELETE FROM price_book")
            for row in data["price_book"]:
                cols = ", ".join(row.keys())
                marks = ", ".join("?" * len(row))
                conn.execute(f"INSERT INTO price_book ({cols}) VALUES ({marks})", list(row.values()))
        for t in tables:
            for row in data.get(t, []):
                cols = ", ".join(row.keys())
                marks = ", ".join("?" * len(row))
                conn.execute(f"INSERT INTO {t} ({cols}) VALUES ({marks})", list(row.values()))
        if conn.execute("SELECT COUNT(*) FROM email_templates").fetchone()[0] == 0:
            from ..database import DEFAULT_EMAIL_TEMPLATES

            conn.executemany("INSERT INTO email_templates (name, subject, body) VALUES (?, ?, ?)", DEFAULT_EMAIL_TEMPLATES)
        return {"status": "replaced", "counts": {t: len(data.get(t, [])) for t in tables}}

    clinic_map: dict[int, int] = {}
    contact_map: dict[int, int] = {}
    group_map: dict[int, int] = {}
    for row in data.get("clinic_groups", []):
        old_id = row.pop("id", None)
        cols = ", ".join(row.keys())
        marks = ", ".join("?" * len(row))
        cur = conn.execute(f"INSERT INTO clinic_groups ({cols}) VALUES ({marks})", list(row.values()))
        if old_id is not None:
            group_map[old_id] = cur.lastrowid
    for row in data.get("clinics", []):
        old_id = row.pop("id", None)
        if "group_id" in row:
            row["group_id"] = group_map.get(row.get("group_id"))
        cols = ", ".join(row.keys())
        marks = ", ".join("?" * len(row))
        cur = conn.execute(f"INSERT INTO clinics ({cols}) VALUES ({marks})", list(row.values()))
        if old_id is not None:
            clinic_map[old_id] = cur.lastrowid
    for row in data.get("contacts", []):
        old_id = row.pop("id", None)
        row["clinic_id"] = clinic_map.get(row.get("clinic_id"))
        if "group_id" in row:
            row["group_id"] = group_map.get(row.get("group_id"))
        cols = ", ".join(row.keys())
        marks = ", ".join("?" * len(row))
        cur = conn.execute(f"INSERT INTO contacts ({cols}) VALUES ({marks})", list(row.values()))
        if old_id is not None:
            contact_map[old_id] = cur.lastrowid
    for row in data.get("appointments", []):
        row.pop("id", None)
        if row.get("clinic_id") not in clinic_map:
            continue
        row["clinic_id"] = clinic_map[row["clinic_id"]]
        row["contact_id"] = contact_map.get(row.get("contact_id"))
        cols = ", ".join(row.keys())
        marks = ", ".join("?" * len(row))
        conn.execute(f"INSERT INTO appointments ({cols}) VALUES ({marks})", list(row.values()))
    for table in ("clinic_notes", "clinic_events", "tasks", "clinic_locations", "attachments"):
        for row in data.get(table, []):
            row.pop("id", None)
            if row.get("clinic_id") is not None and row.get("clinic_id") not in clinic_map:
                continue
            if row.get("clinic_id") is not None:
                row["clinic_id"] = clinic_map[row["clinic_id"]]
            if "contact_id" in row:
                row["contact_id"] = contact_map.get(row.get("contact_id"))
            cols = ", ".join(row.keys())
            marks = ", ".join("?" * len(row))
            conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(row.values()))
    for row in data.get("clinic_links", []):
        row.pop("id", None)
        if row.get("clinic_id") not in clinic_map or row.get("other_clinic_id") not in clinic_map:
            continue
        row["clinic_id"] = clinic_map[row["clinic_id"]]
        row["other_clinic_id"] = clinic_map[row["other_clinic_id"]]
        cols = ", ".join(row.keys())
        marks = ", ".join("?" * len(row))
        conn.execute(f"INSERT INTO clinic_links ({cols}) VALUES ({marks})", list(row.values()))
    for table in ("email_templates", "saved_views"):
        for row in data.get(table, []):
            row.pop("id", None)
            cols = ", ".join(row.keys())
            marks = ", ".join("?" * len(row))
            conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(row.values()))
    device_map: dict[int, int] = {}
    pending_uplinks: list[tuple[int, int]] = []
    for row in data.get("devices", []):
        old_id = row.pop("id", None)
        if row.get("clinic_id") not in clinic_map:
            continue
        row["clinic_id"] = clinic_map[row["clinic_id"]]
        row["location_id"] = None
        old_up = row.pop("uplink_id", None)
        cols = ", ".join(row.keys())
        marks = ", ".join("?" * len(row))
        cur = conn.execute(f"INSERT INTO devices ({cols}) VALUES ({marks})", list(row.values()))
        if old_id is not None:
            device_map[old_id] = cur.lastrowid
        if old_up is not None:
            pending_uplinks.append((cur.lastrowid, old_up))
    for new_id, old_up in pending_uplinks:
        if old_up in device_map:
            conn.execute("UPDATE devices SET uplink_id = ? WHERE id = ?", (device_map[old_up], new_id))
    for row in data.get("quotes", []):
        row.pop("id", None)
        if row.get("clinic_id") not in clinic_map:
            continue
        row["clinic_id"] = clinic_map[row["clinic_id"]]
        row["contact_id"] = contact_map.get(row.get("contact_id"))
        cols = ", ".join(row.keys())
        marks = ", ".join("?" * len(row))
        conn.execute(f"INSERT INTO quotes ({cols}) VALUES ({marks})", list(row.values()))
    for row in data.get("device_tickets", []):
        row.pop("id", None)
        if row.get("device_id") not in device_map:
            continue
        row["device_id"] = device_map[row["device_id"]]
        cols = ", ".join(row.keys())
        marks = ", ".join("?" * len(row))
        conn.execute(f"INSERT INTO device_tickets ({cols}) VALUES ({marks})", list(row.values()))
    for row in data.get("device_links", []):
        row.pop("id", None)
        if row.get("device_id") not in device_map or row.get("uplink_id") not in device_map:
            continue
        row["device_id"] = device_map[row["device_id"]]
        row["uplink_id"] = device_map[row["uplink_id"]]
        cols = ", ".join(row.keys())
        marks = ", ".join("?" * len(row))
        conn.execute(f"INSERT INTO device_links ({cols}) VALUES ({marks})", list(row.values()))
    return {"status": "merged", "counts": {t: len(data.get(t, [])) for t in tables}}


# ---- Routing -----------------------------------------------------------------

OSRM_URL = "https://router.project-osrm.org"
# Straight-line to road-distance fudge factor and an average city speed, used when OSRM is unreachable.
CIRCUITY = 1.3
CITY_SPEED_KMH = 35.0


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1 = map(math.radians, a)
    lat2, lng2 = map(math.radians, b)
    d = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(d))


def _osrm_table(source: tuple[float, float], dests: list[tuple[float, float]]) -> tuple[list[float], list[float]] | None:
    """Drive durations (min) and distances (km) from one point to many via OSRM. None on failure."""
    if not dests:
        return [], []
    coords = ";".join(f"{lng},{lat}" for lat, lng in [source, *dests])
    url = f"{OSRM_URL}/table/v1/driving/{coords}?sources=0&annotations=duration,distance"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if data.get("code") != "Ok":
        return None
    durations = data["durations"][0][1:]
    distances = data["distances"][0][1:]
    mins = [(d / 60.0) if d is not None else None for d in durations]
    kms = [(d / 1000.0) if d is not None else None for d in distances]
    return mins, kms


def _estimate(source: tuple[float, float], dests: list[tuple[float, float]]) -> tuple[list[float], list[float]]:
    kms = [haversine_km(source, d) * CIRCUITY for d in dests]
    mins = [k / CITY_SPEED_KMH * 60 for k in kms]
    return mins, kms


@router.get("/drivetime")
def drivetime(lat: float, lng: float, conn: sqlite3.Connection = Depends(db_dependency)):
    """Drive time and distance from a point to every mapped clinic.

    Uses the public OSRM demo router when reachable; otherwise a straight-line estimate.
    """
    clinics = rows_to_list(conn.execute("SELECT id, lat, lng FROM clinics WHERE lat IS NOT NULL AND lng IS NOT NULL"))
    dests = [(c["lat"], c["lng"]) for c in clinics]
    source = (lat, lng)
    result = None
    # OSRM table requests are capped at 100 coordinates on the demo server; chunk to stay under.
    if dests:
        mins_all: list = []
        kms_all: list = []
        ok = True
        for i in range(0, len(dests), 90):
            chunk = _osrm_table(source, dests[i:i + 90])
            if chunk is None:
                ok = False
                break
            mins_all += chunk[0]
            kms_all += chunk[1]
        if ok:
            result = ("osrm", mins_all, kms_all)
    if result is None:
        mins, kms = _estimate(source, dests)
        result = ("estimate", mins, kms)
    source_name, mins, kms = result
    est_mins, est_kms = _estimate(source, dests)
    out = {}
    for c, m, k, em, ek in zip(clinics, mins, kms, est_mins, est_kms):
        out[c["id"]] = {
            "minutes": round(m if m is not None else em, 1),
            "km": round(k if k is not None else ek, 2),
            "straight_km": round(ek / CIRCUITY, 2),
        }
    return {"source": source_name, "clinics": out}


def _route_order(points: list[tuple[float, float]], start: tuple[float, float] | None, loop: bool) -> list[int]:
    """Nearest-neighbour tour followed by 2-opt improvement. Returns indices into points."""
    n = len(points)
    if n <= 1:
        return list(range(n))
    dist = [[haversine_km(points[i], points[j]) for j in range(n)] for i in range(n)]
    if start is not None:
        start_d = [haversine_km(start, p) for p in points]
        first = min(range(n), key=lambda i: start_d[i])
    else:
        first = 0
    order = [first]
    remaining = set(range(n)) - {first}
    while remaining:
        last = order[-1]
        nxt = min(remaining, key=lambda i: dist[last][i])
        order.append(nxt)
        remaining.remove(nxt)

    def tour_len(o: list[int]) -> float:
        total = sum(dist[o[i]][o[i + 1]] for i in range(len(o) - 1))
        if start is not None:
            total += start_d[o[0]]
            if loop:
                total += start_d[o[-1]]
        elif loop:
            total += dist[o[-1]][o[0]]
        return total

    improved = True
    best = tour_len(order)
    while improved:
        improved = False
        for i in range(0, n - 1):
            for j in range(i + 1, n):
                cand = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                if start is None and i == 0 and not loop:
                    pass  # reversing from the head is allowed when there is no fixed start
                length = tour_len(cand)
                if length + 1e-9 < best:
                    order, best, improved = cand, length, True
    return order


@router.post("/route")
def plan_route(payload: RouteRequest, conn: sqlite3.Connection = Depends(db_dependency)):
    """Order a set of clinics into an efficient driving route."""
    ids = payload.clinic_ids
    marks = ",".join("?" * len(ids))
    rows = rows_to_list(conn.execute(f"SELECT id, name, address, lat, lng FROM clinics WHERE id IN ({marks})", ids))
    by_id = {r["id"]: r for r in rows}
    clinics = [by_id[i] for i in ids if i in by_id and by_id[i]["lat"] is not None and by_id[i]["lng"] is not None]
    if not clinics:
        raise HTTPException(status_code=422, detail="None of the selected clinics are on the map")
    points = [(c["lat"], c["lng"]) for c in clinics]
    start = (payload.start.lat, payload.start.lng) if payload.start else None
    order = _route_order(points, start, payload.return_to_start and start is not None)

    stops = []
    prev = start
    cum = 0.0
    for idx in order:
        c = clinics[idx]
        leg = haversine_km(prev, (c["lat"], c["lng"])) * CIRCUITY if prev else 0.0
        cum += leg
        stops.append({**c, "leg_km": round(leg, 1), "cum_km": round(cum, 1), "leg_minutes": round(leg / CITY_SPEED_KMH * 60)})
        prev = (c["lat"], c["lng"])
    total = cum
    if payload.return_to_start and start:
        total += haversine_km(prev, start) * CIRCUITY

    # Try to get real drive legs from OSRM for the chosen order.
    coords = [start] if start else []
    coords += [(s["lat"], s["lng"]) for s in stops]
    if payload.return_to_start and start:
        coords.append(start)
    osrm_geometry = None
    osrm_total_min = None
    if len(coords) >= 2:
        url = f"{OSRM_URL}/route/v1/driving/" + ";".join(f"{lng},{lat}" for lat, lng in coords) + "?overview=full&geometries=geojson"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("code") == "Ok" and data.get("routes"):
                r = data["routes"][0]
                osrm_geometry = [[lat, lng] for lng, lat in r["geometry"]["coordinates"]]
                osrm_total_min = round(r["duration"] / 60)
                total = r["distance"] / 1000
                legs = r["legs"]
                cum = 0.0
                for s, leg in zip(stops, legs):
                    s["leg_km"] = round(leg["distance"] / 1000, 1)
                    s["leg_minutes"] = round(leg["duration"] / 60)
                    cum += s["leg_km"]
                    s["cum_km"] = round(cum, 1)
        except Exception:  # noqa: BLE001
            pass

    # Google Maps directions link (origin/destination + up to 9 waypoints supported by the URL API).
    g_points = [f"{s['lat']},{s['lng']}" for s in stops]
    origin = f"{start[0]},{start[1]}" if start else g_points[0]
    rest = g_points if start else g_points[1:]
    destination = origin if (payload.return_to_start and start) else (rest[-1] if rest else origin)
    waypoints = rest[:-1] if not (payload.return_to_start and start) else rest
    gmaps = f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={destination}&travelmode=driving"
    if waypoints:
        gmaps += "&waypoints=" + "|".join(waypoints[:9])

    return {
        "stops": stops,
        "total_km": round(total, 1),
        "total_minutes": osrm_total_min if osrm_total_min is not None else round(total / CITY_SPEED_KMH * 60),
        "source": "osrm" if osrm_geometry else "estimate",
        "geometry": osrm_geometry,
        "google_maps_url": gmaps,
        "skipped": [i for i in ids if i not in by_id or by_id[i]["lat"] is None],
    }
