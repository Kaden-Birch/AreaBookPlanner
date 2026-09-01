"""Geocoding, dashboard, metadata, and import/export endpoints."""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response

from ..database import db_dependency, rows_to_list
from ..logic import COLOR_LABELS, RELATIONSHIP_LABELS, enrich_clinic, now_iso
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
        "contact_roles": ROLE_LABELS,
        "appointment_types": TYPE_LABELS,
        "appointment_statuses": STATUS_LABELS,
        "clinic_types": CLINIC_TYPES,
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

    stale = [
        {"id": c["id"], "name": c["name"], "last_visit": c["last_visit"], "color": c["color"], "priority": c["priority"]}
        for c in clinics
        if c["color"] == "grey" or (c["relationship"] == "current_client" and (
            not c["last_visit"] or c["last_visit"] < (datetime.now() - timedelta(days=90)).isoformat()))
    ]
    stale.sort(key=lambda x: (x["last_visit"] or ""))

    unmapped = [{"id": c["id"], "name": c["name"]} for c in clinics if c["lat"] is None or c["lng"] is None]

    return {
        "totals": {
            "clinics": len(clinics),
            "contacts": conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0],
            "appointments_upcoming": conn.execute(
                "SELECT COUNT(*) FROM appointments WHERE status='scheduled' AND start_time >= ?", (now,)
            ).fetchone()[0],
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
        "stale": stale[:20],
        "unmapped": unmapped,
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
        "id", "name", "relationship_label", "color_label", "address", "city", "province", "postal_code",
        "phone", "fax", "email", "website", "clinic_type", "emr_system", "it_provider", "provider_count",
        "priority", "tags", "last_visit", "next_follow_up", "lat", "lng", "notes",
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
    tables = ["clinics", "contacts", "appointments", "clinic_notes"]
    if replace:
        for t in reversed(tables):
            conn.execute(f"DELETE FROM {t}")
        for t in tables:
            for row in data.get(t, []):
                cols = ", ".join(row.keys())
                marks = ", ".join("?" * len(row))
                conn.execute(f"INSERT INTO {t} ({cols}) VALUES ({marks})", list(row.values()))
        return {"status": "replaced", "counts": {t: len(data.get(t, [])) for t in tables}}

    clinic_map: dict[int, int] = {}
    contact_map: dict[int, int] = {}
    for row in data.get("clinics", []):
        old_id = row.pop("id", None)
        cols = ", ".join(row.keys())
        marks = ", ".join("?" * len(row))
        cur = conn.execute(f"INSERT INTO clinics ({cols}) VALUES ({marks})", list(row.values()))
        if old_id is not None:
            clinic_map[old_id] = cur.lastrowid
    for row in data.get("contacts", []):
        old_id = row.pop("id", None)
        row["clinic_id"] = clinic_map.get(row.get("clinic_id"))
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
    for row in data.get("clinic_notes", []):
        row.pop("id", None)
        if row.get("clinic_id") not in clinic_map:
            continue
        row["clinic_id"] = clinic_map[row["clinic_id"]]
        cols = ", ".join(row.keys())
        marks = ", ".join("?" * len(row))
        conn.execute(f"INSERT INTO clinic_notes ({cols}) VALUES ({marks})", list(row.values()))
    return {"status": "merged", "counts": {t: len(data.get(t, [])) for t in tables}}
