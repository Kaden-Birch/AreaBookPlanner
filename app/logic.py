"""Derived clinic attributes: last visit, next appointment, map colour."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

# Appointment types that count as physically going to the clinic.
IN_PERSON_TYPES = ("visit", "demo", "install", "support")
RECENT_VISIT_DAYS = 90

# Map colour keys are semantic; the actual hues live in the stylesheet / ui.js.
#   client      green          current client
#   interested  dark blue      interested
#   recent      very pale blue prospect visited in the last 3 months
#   stale       grey           prospect visited, but not in the last 3 months
#   new         white          prospect never visited
#   dnc         red            do not contact
COLOR_LABELS = {
    "client": "Current client",
    "interested": "Interested",
    "recent": "Visited recently (last 3 months)",
    "stale": "Visited before (not in last 3 months)",
    "new": "Not yet visited",
    "dnc": "Do not contact",
}
LEGACY_COLOR_KEYS = {"yellow": "client", "green": "interested", "blue": "recent", "grey": "stale", "white": "new", "red": "dnc"}

STAGE_LABELS = {
    "lead": "Lead",           # added to the system but not contacted yet — NOT on the pipeline board
    "prospect": "Interested",
    "contacted": "Contacted",
    "demo": "In negotiations",
    "proposal": "Quote sent",
    "won": "Won",
    "lost": "Lost",
}
# Stages shown on the pipeline board, in order (leads are pre-pipeline, so excluded).
PIPELINE_STAGES = ("prospect", "contacted", "demo", "proposal", "won", "lost")
OPEN_STAGES = ("prospect", "contacted", "demo", "proposal")
CLOSED_STAGES = ("won", "lost")

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

# Equipment / network devices. prefix feeds the naming template {SHORTHAND}-{PREFIX}{NNN}.
DEVICE_TYPES = {
    "firewall":     {"label": "Firewall",        "prefix": "FW", "icon": "🛡",  "network": True},
    "router":       {"label": "Router",          "prefix": "R",  "icon": "📡", "network": True},
    "switch":       {"label": "Switch",          "prefix": "SW", "icon": "🔀", "network": True},
    "access_point": {"label": "Access point",    "prefix": "AP", "icon": "📶", "network": True},
    "server":       {"label": "Server",          "prefix": "S",  "icon": "🗄",  "network": False},
    "vm":           {"label": "Virtual machine",  "prefix": "VM", "icon": "🧊", "network": False, "vm": True},
    "workstation":  {"label": "Workstation",     "prefix": "W",  "icon": "🖥",  "network": False},
    "laptop":       {"label": "Laptop",          "prefix": "L",  "icon": "💻", "network": False},
    "wireless":     {"label": "Wireless device", "prefix": "M",  "icon": "📱", "network": False},
    "voip":         {"label": "VoIP phone",      "prefix": "V",  "icon": "☎",  "network": False},
    "printer":      {"label": "Printer",         "prefix": "P",  "icon": "🖨",  "network": False},
    "patch_panel":  {"label": "Patch panel",      "prefix": "PP", "icon": "🎛", "network": False, "passive": True},
    "shelf":        {"label": "Shelf",            "prefix": "SH", "icon": "🗂", "network": False, "shelf": True},
    "nvr":          {"label": "Network video recorder", "prefix": "NVR", "icon": "📹", "network": False, "security": True},
    "camera":       {"label": "Security camera",  "prefix": "CAM", "icon": "📷", "network": False, "security": True},
    "security":     {"label": "Security device",  "prefix": "SEC", "icon": "🔒", "network": False, "security": True},
    "other":        {"label": "Other",           "prefix": "O",  "icon": "📦", "network": False},
}
DEVICE_DESIGNATIONS = {
    "server": ["Windows Server", "Linux", "Hypervisor / host", "Domain controller", "File / storage", "Backup", "Database", "EMR server", "NAS", "Other"],
    "vm": ["Windows Server", "Linux", "Domain controller", "File / storage", "Application", "Database", "EMR server", "Terminal server", "Backup", "Other"],
    "wireless": ["Cell phone", "Tablet", "Laptop (wireless only)", "Other"],
    "voip": ["Desk phone", "Cordless", "Conference phone", "Reception console"],
    "printer": ["Multifunction", "Laser", "Label printer", "Scanner"],
    "workstation": ["Front desk", "Exam room", "Office", "Nursing station", "Lab"],
    "laptop": ["Provider", "Admin", "Loaner"],
    "firewall": ["Edge firewall", "UTM"],
    "router": ["ISP modem/router", "Edge router", "VPN router"],
    "switch": ["Core switch", "Access switch", "PoE switch"],
    "access_point": ["Ceiling AP", "Guest Wi-Fi", "Mesh node"],
    "nvr": ["NVR", "DVR", "VMS / camera server", "Cloud recorder"],
    "camera": ["Dome", "Bullet", "PTZ", "Turret", "Doorbell / video intercom", "Fisheye"],
    "security": ["Access control panel", "Door controller", "Alarm panel", "Card reader", "Intercom", "Motion / door sensor", "Keypad"],
    "patch_panel": ["24-port Cat6", "48-port Cat6", "Fibre / LC", "Voice / 66 block", "Coax"],
    "shelf": ["Fixed shelf", "Sliding shelf", "Vented shelf", "Cantilever shelf"],
    "other": ["UPS", "NAS", "Smart TV", "Digital signage"],
}
DEVICE_STATUSES = {"active": "Active", "spare": "Spare", "retired": "Retired"}
LINK_TYPES_NET = {"ethernet": "Wired (Ethernet)", "wireless": "Wireless"}
# Types whose "user" field makes sense
USER_DEVICE_TYPES = ("workstation", "laptop", "wireless", "voip")
# Devices whose "operating system" field is meaningful.
OS_DEVICE_TYPES = ("workstation", "laptop", "server", "vm", "wireless", "other")
# Typical rack height (in rack units) by device type, used as the default when adding to a rack.
DEFAULT_RACK_UNITS = {
    "server": 2, "switch": 1, "router": 1, "firewall": 1, "access_point": 1, "nvr": 2, "security": 1,
    "patch_panel": 1, "shelf": 2, "other": 1,
}
# Device types that are never physically rack-mounted (a VM lives on its host, etc.).
NON_RACKABLE_TYPES = ("vm", "wireless", "laptop", "camera")
# Passive physical fixtures that belong in the rack view but not the network topology.
NON_TOPOLOGY_TYPES = ("patch_panel", "shelf")


def clinic_shorthand(clinic: dict) -> str:
    """Shorthand for naming; falls back to initials of the clinic name."""
    sh = (clinic.get("shorthand") or "").strip().upper()
    if sh:
        return sh
    words = [w for w in (clinic.get("name") or "").replace("-", " ").split() if w[0].isalnum()]
    initials = "".join(w[0] for w in words)[:3].upper()
    return initials or "CLN"

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
        return "dnc"
    if relationship == "current_client":
        return "client"
    if relationship == "interested":
        return "interested"
    # prospect: colour depends on visit recency
    if not last_visit:
        return "new"
    now = now or datetime.now()
    try:
        visited = datetime.fromisoformat(last_visit)
    except ValueError:
        return "new"
    if now - visited <= timedelta(days=RECENT_VISIT_DAYS):
        return "recent"
    return "stale"


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
    today = now_iso()[:10]
    clinic["follow_up_overdue"] = bool(clinic.get("next_follow_up")) and clinic["next_follow_up"] < today and clinic["relationship"] != "do_not_contact"
    clinic["relationship_label"] = RELATIONSHIP_LABELS.get(clinic["relationship"], clinic["relationship"])
    clinic["tag_list"] = [t.strip() for t in (clinic.get("tags") or "").split(",") if t.strip()]
    clinic["archived"] = bool(clinic.get("archived"))
    clinic["is_client"] = clinic["relationship"] == "current_client"
    stage = clinic.get("stage") or "lead"
    clinic["stage"] = stage
    clinic["stage_label"] = STAGE_LABELS.get(stage, stage)
    clinic["in_pipeline"] = stage != "lead"
    # Won/Lost stay on the board only for the calendar month they closed in.
    clinic["closed_recent"] = bool(
        stage in CLOSED_STAGES and clinic.get("outcome_date") and clinic["outcome_date"][:7] == now_iso()[:7]
    )
    value = clinic.get("deal_value") or 0
    prob = clinic.get("win_probability")
    if prob is None:
        prob = DEFAULT_PROBABILITY.get(stage, 0)
    clinic["effective_probability"] = prob
    clinic["weighted_value"] = round(value * prob / 100, 2) if stage in OPEN_STAGES else 0
    return clinic


# Used when no explicit win probability is set on a clinic.
DEFAULT_PROBABILITY = {"lead": 0, "prospect": 10, "contacted": 20, "demo": 40, "proposal": 60, "won": 100, "lost": 0}


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


# ---- Quoting ------------------------------------------------------------------

QUOTE_CATEGORIES = {
    "plan": "Managed IT plan",
    "infra": "Infrastructure",
    "backup": "Backup & recovery",
    "emr": "EMR",
    "extras": "Add-ons",
    "rates": "Support rates",
    "onetime": "One-time",
}

# Units drive both the label and where the quantity comes from (see QTY_SOURCES).
UNIT_LABELS = {
    "per_device": "per managed device / month",
    "per_user": "per user / month",
    "per_vm": "per VM / month",
    "per_server": "per physical server / month",
    "per_server_all": "per server or VM / month",
    "per_firewall": "per firewall / month",
    "per_switch": "per switch / month",
    "per_ap": "per access point / month",
    "per_site": "per site / month",
    "per_phone": "per phone / month",
    "per_printer": "per printer / month",
    "per_month": "flat / month",
    "per_hour": "per hour",
    "one_time": "one-time",
}

PRICE_BOOK_DEFAULTS = [
    {"key": "plan_basic", "label": "Basic monitoring / light managed IT", "category": "plan", "unit": "per_device", "alt_unit": "per_user", "mode_group": "plan",
     "description": "Monitoring, patching and remote helpdesk during business hours."},
    {"key": "plan_standard", "label": "Standard fully managed IT", "category": "plan", "unit": "per_device", "alt_unit": "per_user", "mode_group": "plan",
     "description": "Unlimited remote support, patching, monitoring, vendor management."},
    {"key": "plan_healthcare", "label": "Healthcare-focused managed IT", "category": "plan", "unit": "per_device", "alt_unit": "per_user", "mode_group": "plan",
     "description": "Standard plan plus EMR vendor liaison, privacy/compliance support and clinic-hours priority."},
    {"key": "plan_security", "label": "High-security / 24×7 SOC / multi-site healthcare", "category": "plan", "unit": "per_device", "alt_unit": "per_user", "mode_group": "plan",
     "description": "Healthcare plan plus 24×7 security operations, EDR/MDR and multi-site coverage."},
    {"key": "vm", "label": "Windows/Linux VM", "category": "infra", "unit": "per_vm"},
    {"key": "server", "label": "Physical server / hypervisor", "category": "infra", "unit": "per_server"},
    {"key": "firewall", "label": "Firewall", "category": "infra", "unit": "per_firewall"},
    {"key": "switch", "label": "Managed switch", "category": "infra", "unit": "per_switch"},
    {"key": "ap", "label": "Wireless AP", "category": "infra", "unit": "per_ap"},
    {"key": "site", "label": "General network/site management", "category": "infra", "unit": "per_site"},
    {"key": "backup_basic", "label": "Basic server backup", "category": "backup", "unit": "per_server_all"},
    {"key": "backup_bdr", "label": "Proper BDR / rapid-recovery backup", "category": "backup", "unit": "per_server_all"},
    {"key": "backup_m365", "label": "M365 backup", "category": "backup", "unit": "per_user"},
    {"key": "primeemr", "label": "PrimeEMR", "category": "emr", "unit": "per_month", "alt_unit": "per_user", "mode_group": "emr",
     "description": "Our EMR: flat monthly rate, or per user."},
    {"key": "edr", "label": "Endpoint protection / EDR", "category": "extras", "unit": "per_device"},
    {"key": "email_security", "label": "Email security & spam filtering", "category": "extras", "unit": "per_user"},
    {"key": "m365_license", "label": "Microsoft 365 licensing", "category": "extras", "unit": "per_user"},
    {"key": "voip", "label": "VoIP phone service", "category": "extras", "unit": "per_phone"},
    {"key": "printer_mgmt", "label": "Printer management", "category": "extras", "unit": "per_printer"},
    {"key": "breakfix", "label": "Break/fix support", "category": "rates", "unit": "per_hour"},
    {"key": "project", "label": "Project / senior engineering / emergency work", "category": "rates", "unit": "per_hour"},
    {"key": "onsite", "label": "On-site technician", "category": "rates", "unit": "per_hour"},
    {"key": "onboarding", "label": "Onboarding / setup fee", "category": "onetime", "unit": "one_time"},
]

# Which count fills the quantity for a unit.
QTY_SOURCES = {
    "per_device": "devices_managed", "per_user": "users", "per_vm": "vms", "per_server": "servers_physical",
    "per_server_all": "servers_all", "per_firewall": "firewalls", "per_switch": "switches", "per_ap": "aps",
    "per_site": "sites", "per_phone": "phones", "per_printer": "printers", "per_month": "one", "one_time": "one", "per_hour": "zero",
}
# Items included by default when a quote is generated.
DEFAULT_INCLUDED = {"plan_standard", "vm", "server", "firewall", "switch", "ap", "site", "backup_basic", "backup_m365", "primeemr", "breakfix", "project", "onsite", "onboarding"}
DEFAULT_QUOTE_TERMS = (
    "Monthly services are billed in advance and require 30 days' notice to cancel. Hourly work is billed in "
    "15-minute increments. Hardware, licensing and third-party costs are passed through at cost unless listed. "
    "Prices exclude GST unless shown."
)
