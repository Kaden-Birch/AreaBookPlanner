#!/usr/bin/env python3
"""Seed a few demo clinics around Calgary so the app has something to show.

Usage:
    python scripts/seed_demo.py                       # writes straight to the SQLite DB
    python scripts/seed_demo.py --url http://localhost:8080   # uses the HTTP API instead
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLINICS = [
    {"name": "Crowfoot Medical Clinic", "address": "400 Crowfoot Cres NW", "postal_code": "T3G 5H6",
     "lat": 51.1235, "lng": -114.2065, "relationship": "current_client", "clinic_type": "Family practice",
     "emr_system": "Telus Wolf", "provider_count": 8, "tags": "NW, client", "phone": "403-555-0100",
     "stage": "won", "deal_value": 18000, "outcome_reason": "service", "outcome_notes": "Chose us for on-site response time.",
     "shorthand": "CMC", "outcome_date": "2024-02-12"},
    {"name": "Beltline Family Practice", "address": "1121 12 Ave SW", "postal_code": "T2R 0J3",
     "lat": 51.0413, "lng": -114.0794, "relationship": "interested", "clinic_type": "Family practice",
     "emr_system": "Accuro", "provider_count": 5, "tags": "downtown", "next_follow_up": (datetime.now() + timedelta(days=3)).date().isoformat(),
     "stage": "proposal", "deal_value": 12000, "win_probability": 65, "expected_close": (datetime.now() + timedelta(days=14)).date().isoformat()},
    {"name": "Marlborough Walk-In", "address": "1240 36 St NE", "postal_code": "T2A 6L1",
     "lat": 51.0552, "lng": -113.9836, "relationship": "prospect", "clinic_type": "Walk-in clinic",
     "it_provider": "In-house", "provider_count": 4, "tags": "NE, walk-in", "stage": "contacted", "deal_value": 6000},
    {"name": "Southcentre Dental", "address": "100 Anderson Rd SE", "postal_code": "T2J 3V1",
     "lat": 50.9615, "lng": -114.0715, "relationship": "prospect", "clinic_type": "Dental",
     "provider_count": 3, "tags": "SE, dental", "stage": "lost", "deal_value": 4500, "outcome_reason": "contract_locked",
     "outcome_notes": "3-year contract with current provider, ends spring 2028."},
    {"name": "Westbrook Physiotherapy", "address": "1200 37 St SW", "postal_code": "T3C 1S2",
     "lat": 51.0378, "lng": -114.1319, "relationship": "prospect", "clinic_type": "Physiotherapy",
     "provider_count": 2, "tags": "SW", "stage": "demo", "deal_value": 5000, "expected_close": (datetime.now() + timedelta(days=25)).date().isoformat()},
    {"name": "Bowness Medical Centre", "address": "6400 Bowness Rd NW", "postal_code": "T3B 0E3",
     "lat": 51.0867, "lng": -114.1855, "relationship": "do_not_contact", "clinic_type": "Medical centre",
     "notes": "Locked into a 5-year contract with another provider. Asked not to be contacted.", "tags": "NW"},
]

CONTACTS = [
    ("Crowfoot Medical Clinic", {"first_name": "Sarah", "last_name": "Nguyen", "role": "manager", "title": "Office Manager", "use_main_line": True, "extension": "204", "email": "sarah@example.com", "is_primary": True}),
    ("Crowfoot Medical Clinic", {"first_name": "Raj", "last_name": "Patel", "role": "doctor", "title": "MD, Lead Physician"}),
    ("Beltline Family Practice", {"first_name": "Emily", "last_name": "Chen", "role": "receptionist", "phone": "403-555-0202"}),
    ("Marlborough Walk-In", {"first_name": "Tom", "last_name": "Baker", "role": "owner", "mobile": "403-555-0303", "is_primary": True}),
]

def _dt(days: int, hour: int = 10) -> str:
    d = datetime.now() + timedelta(days=days)
    return d.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat(timespec="minutes")

APPOINTMENTS = [
    ("Crowfoot Medical Clinic", {"title": "Quarterly check-in", "appt_type": "visit", "start_time": _dt(-20), "status": "completed", "outcome": "All good, discussed adding a second server."}),
    ("Crowfoot Medical Clinic", {"title": "Server upgrade planning", "appt_type": "visit", "start_time": _dt(5, 9), "end_time": _dt(5, 10)}),
    ("Beltline Family Practice", {"title": "Intro visit", "appt_type": "visit", "start_time": _dt(-12), "status": "completed", "outcome": "Met Emily; manager wants a quote for managed backups."}),
    ("Beltline Family Practice", {"title": "Present quote", "appt_type": "demo", "start_time": _dt(3, 14), "end_time": _dt(3, 15), "notes": "Bring backup pricing sheet."}),
    ("Marlborough Walk-In", {"title": "Drop-in visit", "appt_type": "visit", "start_time": _dt(-40), "status": "completed", "outcome": "Tom was busy; left a card."}),
    ("Southcentre Dental", {"title": "Drop-in visit", "appt_type": "visit", "start_time": _dt(-150), "status": "completed", "outcome": "Not interested right now, revisit next year."}),
]

TASKS = [
    ("Beltline Family Practice", {"title": "Send revised backup quote", "due_date": (datetime.now() - timedelta(days=1)).date().isoformat(), "priority": "high"}),
    ("Beltline Family Practice", {"title": "Call Dana (office manager) re: decision", "due_date": (datetime.now() + timedelta(days=2)).date().isoformat()}),
    ("Marlborough Walk-In", {"title": "Drop off brochure for Tom", "due_date": datetime.now().date().isoformat()}),
    ("Westbrook Physiotherapy", {"title": "Prepare demo laptop", "due_date": (datetime.now() + timedelta(days=5)).date().isoformat(), "priority": "medium"}),
    (None, {"title": "Order more business cards", "priority": "low"}),
]

NOTES = [
    ("Beltline Family Practice", "Emily says the office manager (Dana) is in Tue-Thu mornings."),
    ("Marlborough Walk-In", "Their current IT person is retiring in the spring."),
]


LOCATIONS = [
    ("Crowfoot Medical Clinic", {"name": "CMC Tuscany", "address": "11 Tuscany Blvd NW", "postal_code": "T3L 2V7", "lat": 51.1258, "lng": -114.2426, "phone": "403-555-0110"}),
]


EQUIPMENT = [  # (temp key, payload, uplink temp key)
    ("fw", {"device_type": "firewall", "manufacturer": "Fortinet", "model": "FortiGate 60F", "ip_address": "192.168.10.1", "designation": "Edge firewall", "rack": "Rack A", "rack_room": "Server room", "rack_position": 12, "rack_units": 1}, None),
    ("sw", {"device_type": "switch", "manufacturer": "Ubiquiti", "model": "USW-24-PoE", "ip_address": "192.168.10.2", "designation": "PoE switch", "rack": "Rack A", "rack_room": "Server room", "rack_position": 11, "rack_units": 1}, "fw"),
    ("ap", {"device_type": "access_point", "manufacturer": "Ubiquiti", "model": "U6-Lite", "ip_address": "192.168.10.3", "rack": "Rack A", "rack_room": "Server room", "rack_position": 10, "rack_units": 1}, "sw"),
    ("srv", {"device_type": "server", "designation": "Hypervisor / host", "manufacturer": "Dell", "model": "PowerEdge T350", "ip_address": "192.168.10.10", "os": "VMware ESXi 8", "rack": "Rack A", "rack_room": "Server room", "rack_position": 4, "rack_units": 4}, "sw"),
    ("vm1", {"device_type": "vm", "designation": "Domain controller", "ip_address": "192.168.10.11", "os": "Windows Server 2022",
             "services": ["Active Directory", "DNS / DHCP", "File shares"]}, "srv"),
    ("vm2", {"device_type": "vm", "designation": "EMR server", "ip_address": "192.168.10.12", "os": "Windows Server 2022",
             "services": ["EMR (Telus Wolf) server", "SQL Server", "Backup agent"]}, "srv"),
    ("v1", {"device_type": "voip", "user_name": "Reception", "ip_address": "192.168.10.51", "designation": "Reception console"}, "sw"),
    ("w1", {"device_type": "workstation", "user_name": "Reception", "designation": "Front desk", "ip_address": "192.168.10.21", "os": "Windows 11 Pro", "manufacturer": "Dell", "model": "OptiPlex 7010"}, "v1"),
    ("v2", {"device_type": "voip", "user_name": "Sarah Nguyen", "ip_address": "192.168.10.52"}, "sw"),
    ("w2", {"device_type": "workstation", "user_name": "Sarah Nguyen", "designation": "Office", "ip_address": "192.168.10.22", "os": "Windows 11 Pro"}, "v2"),
    ("w3", {"device_type": "workstation", "user_name": "Dr. Patel", "designation": "Exam room 1", "ip_address": "192.168.10.23", "os": "Windows 11 Pro"}, "sw"),
    ("w4", {"device_type": "workstation", "designation": "Exam room 2", "ip_address": "192.168.10.24", "os": "Windows 11 Pro"}, "sw"),
    ("p1", {"device_type": "printer", "manufacturer": "HP", "model": "LaserJet M479", "ip_address": "192.168.10.40", "designation": "Multifunction"}, "sw"),
    ("l1", {"device_type": "laptop", "user_name": "Dr. Patel", "ip_address": "192.168.10.61", "os": "Windows 11 Pro", "link_type": "wireless"}, "ap"),
    ("m1", {"device_type": "wireless", "user_name": "Dr. Patel", "designation": "Cell phone", "link_type": "wireless"}, "ap"),
    ("old", {"device_type": "workstation", "designation": "Old lab PC", "status": "retired", "notes": "Replaced Jan 2026, kept as spare parts."}, None),
    ("home", {"device_type": "laptop", "user_name": "Dr. Patel", "designation": "Home office", "off_site": True, "os": "Windows 11 Pro", "notes": "Connects via VPN from home."}, None),
]
TICKETS = [("vm2", {"title": "Backup job failing on Sundays", "url": "https://tickets.example.com/4412", "ticket_date": "2026-06-14"}),
           ("p1", {"title": "Paper jams on tray 2", "ticket_date": "2026-07-02"})]


def _seed_equipment(post, clinic_id: int) -> None:
    ids = {}
    for key, payload, up in EQUIPMENT:
        body = dict(payload)
        if up:
            body["uplink_id"] = ids[up]
        ids[key] = post(f"/api/clinics/{clinic_id}/devices", body)["id"]
    for key, t in TICKETS:
        post(f"/api/devices/{ids[key]}/tickets", t)


def seed_via_api(base: str) -> None:
    def post(path, body):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    ids = {}
    for c in CLINICS:
        ids[c["name"]] = post("/api/clinics", c)["id"]
    for name, ct in CONTACTS:
        post("/api/contacts", {**ct, "clinic_id": ids[name]})
    for name, a in APPOINTMENTS:
        post("/api/appointments", {**a, "clinic_id": ids[name]})
    for name, body in NOTES:
        post(f"/api/clinics/{ids[name]}/notes", {"body": body})
    for name, t in TASKS:
        post("/api/tasks", {**t, "clinic_id": ids[name] if name else None})
    for name, loc in LOCATIONS:
        post(f"/api/clinics/{ids[name]}/locations", loc)
    post(f"/api/clinics/{ids['Beltline Family Practice']}/links", {"other_clinic_id": ids["Westbrook Physiotherapy"], "link_type": "same_owner", "notes": "Both owned by Dr. Chen"})
    _seed_equipment(post, ids["Crowfoot Medical Clinic"])
    print(f"Seeded {len(CLINICS)} clinics, {len(CONTACTS)} contacts, {len(APPOINTMENTS)} appointments, {len(TASKS)} tasks via {base}")


def seed_direct() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        ids = {}
        for c in CLINICS:
            ids[c["name"]] = client.post("/api/clinics", json=c).json()["id"]
        for name, ct in CONTACTS:
            client.post("/api/contacts", json={**ct, "clinic_id": ids[name]})
        for name, a in APPOINTMENTS:
            client.post("/api/appointments", json={**a, "clinic_id": ids[name]})
        for name, body in NOTES:
            client.post(f"/api/clinics/{ids[name]}/notes", json={"body": body})
        for name, t in TASKS:
            client.post("/api/tasks", json={**t, "clinic_id": ids[name] if name else None})
        for name, loc in LOCATIONS:
            client.post(f"/api/clinics/{ids[name]}/locations", json=loc)
        client.post(f"/api/clinics/{ids['Beltline Family Practice']}/links", json={"other_clinic_id": ids["Westbrook Physiotherapy"], "link_type": "same_owner", "notes": "Both owned by Dr. Chen"})
        _seed_equipment(lambda path, body: client.post(path, json=body).json(), ids["Crowfoot Medical Clinic"])
    print(f"Seeded {len(CLINICS)} clinics, {len(CONTACTS)} contacts, {len(APPOINTMENTS)} appointments, {len(TASKS)} tasks")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="Base URL of a running server, e.g. http://localhost:8080")
    args = ap.parse_args()
    if args.url:
        seed_via_api(args.url.rstrip("/"))
    else:
        seed_direct()
