"""Derived clinic attributes: last visit, next appointment, map colour."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

# Appointment types that count as physically going to the clinic.
IN_PERSON_TYPES = ("visit", "demo", "install", "support")
RECENT_VISIT_DAYS = 90

COLOR_LABELS = {
    "yellow": "Current client",
    "green": "Interested",
    "blue": "Visited in last 3 months",
    "grey": "Visited, not in last 3 months",
    "white": "Not yet visited",
    "red": "Do not contact",
}

STAGE_LABELS = {
    "prospect": "Prospect",
    "contacted": "Contacted",
    "demo": "Demo",
    "proposal": "Proposal",
    "won": "Won",
    "lost": "Lost",
}
OPEN_STAGES = ("prospect", "contacted", "demo", "proposal")

WON_REASONS = {
    "price": "Competitive price",
    "service": "Service / responsiveness",
    "relationship": "Existing relationship",
    "referral": "Referral",
    "timing": "Good timing (contract ended)",
    "other": "Other",
}
LOST_REASONS = {
    "price": "Price too high",
    "competitor": "Chose a competitor",
    "contract_locked": "Locked into existing contract",
    "timing": "Bad timing",
    "no_need": "No need / in-house IT",
    "no_response": "Went quiet / no response",
    "other": "Other",
}

LINK_TYPES = {
    "referral": "Referral",
    "same_owner": "Same owner",
    "same_building": "Same building",
    "manager_moved": "Manager moved between",
    "shared_staff": "Shared staff",
    "other": "Other",
}

# One-tap note presets. Key -> note text.
QUICK_LOGS = {
    "left_card": "Left a business card",
    "left_voicemail": "Left a voicemail",
    "spoke_reception": "Spoke to reception",
    "spoke_manager": "Spoke to the clinic manager",
    "sent_quote": "Sent a quote",
    "sent_email": "Sent an email",
    "not_interested": "Not interested right now",
    "call_back": "Asked to call back later",
}

REMINDER_OPTIONS = [15, 30, 45, 60]

RELATIONSHIP_LABELS = {
    "current_client": "Current client",
    "interested": "Interested",
    "prospect": "Prospect",
    "do_not_contact": "Do not contact",
}


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def marker_color(relationship: str, last_visit: str | None, now: datetime | None = None) -> str:
    """Map colour per the ChinookIT relationship rules."""
    if relationship == "do_not_contact":
        return "red"
    if relationship == "current_client":
        return "yellow"
    if relationship == "interested":
        return "green"
    # prospect: colour depends on visit recency
    if not last_visit:
        return "white"
    now = now or datetime.now()
    try:
        visited = datetime.fromisoformat(last_visit)
    except ValueError:
        return "white"
    if now - visited <= timedelta(days=RECENT_VISIT_DAYS):
        return "blue"
    return "grey"


def visit_stats(conn: sqlite3.Connection, clinic_id: int) -> dict:
    """Last in-person visit, next scheduled appointment, counts."""
    now = now_iso()
    placeholders = ",".join("?" * len(IN_PERSON_TYPES))
    last = conn.execute(
        f"""SELECT MAX(start_time) FROM appointments
            WHERE clinic_id = ? AND appt_type IN ({placeholders})
              AND status NOT IN ('cancelled','no_show') AND start_time <= ?""",
        (clinic_id, *IN_PERSON_TYPES, now),
    ).fetchone()[0]
    nxt = conn.execute(
        """SELECT id, title, start_time, appt_type FROM appointments
           WHERE clinic_id = ? AND status = 'scheduled' AND start_time >= ?
           ORDER BY start_time ASC LIMIT 1""",
        (clinic_id, now),
    ).fetchone()
    counts = conn.execute(
        """SELECT
             (SELECT COUNT(*) FROM contacts WHERE clinic_id = ?) AS contact_count,
             (SELECT COUNT(*) FROM appointments WHERE clinic_id = ?) AS appointment_count,
             (SELECT COUNT(*) FROM appointments WHERE clinic_id = ? AND status='scheduled' AND start_time >= ?) AS upcoming_count""",
        (clinic_id, clinic_id, clinic_id, now),
    ).fetchone()
    return {
        "last_visit": last,
        "next_appointment": dict(nxt) if nxt else None,
        "contact_count": counts["contact_count"],
        "appointment_count": counts["appointment_count"],
        "upcoming_count": counts["upcoming_count"],
    }


def enrich_clinic(conn: sqlite3.Connection, clinic: dict) -> dict:
    stats = visit_stats(conn, clinic["id"])
    clinic.update(stats)
    clinic["color"] = marker_color(clinic["relationship"], stats["last_visit"])
    clinic["color_label"] = COLOR_LABELS[clinic["color"]]
    clinic["relationship_label"] = RELATIONSHIP_LABELS.get(clinic["relationship"], clinic["relationship"])
    clinic["tag_list"] = [t.strip() for t in (clinic.get("tags") or "").split(",") if t.strip()]
    clinic["archived"] = bool(clinic.get("archived"))
    clinic["is_client"] = clinic["relationship"] == "current_client"
    stage = clinic.get("stage") or "prospect"
    clinic["stage"] = stage
    clinic["stage_label"] = STAGE_LABELS.get(stage, stage)
    value = clinic.get("deal_value") or 0
    prob = clinic.get("win_probability")
    if prob is None:
        prob = DEFAULT_PROBABILITY.get(stage, 0)
    clinic["effective_probability"] = prob
    clinic["weighted_value"] = round(value * prob / 100, 2) if stage in OPEN_STAGES else 0
    return clinic


# Used when no explicit win probability is set on a clinic.
DEFAULT_PROBABILITY = {"prospect": 10, "contacted": 20, "demo": 40, "proposal": 60, "won": 100, "lost": 0}


def log_event(
    conn: sqlite3.Connection, clinic_id: int, event_type: str, title: str, detail: str | None = None,
    from_value: str | None = None, to_value: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO clinic_events (clinic_id, event_type, title, detail, from_value, to_value) VALUES (?, ?, ?, ?, ?, ?)",
        (clinic_id, event_type, title, detail, from_value, to_value),
    )


def normalize_name(s: str | None) -> str:
    """Lower-case, strip punctuation and filler words so 'The Crowfoot Medical Clinic' ~ 'crowfoot medical'."""
    import re

    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    words = [w for w in s.split() if w not in _FILLER]
    return " ".join(words)


_FILLER = {"the", "clinic", "medical", "centre", "center", "family", "practice", "ltd", "inc", "and", "of", "dr", "office"}


def normalize_address(s: str | None) -> str:
    import re

    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\b(north|south)\s*(east|west)\b", lambda m: m.group(1)[0] + m.group(2)[0], s)
    repl = {"street": "st", "avenue": "ave", "road": "rd", "drive": "dr", "crescent": "cres", "trail": "tr",
            "boulevard": "blvd", "northwest": "nw", "northeast": "ne", "southwest": "sw", "southeast": "se", "suite": "", "unit": ""}
    words = [repl.get(w, w) for w in s.split()]
    return " ".join(w for w in words if w)
