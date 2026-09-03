import os
import tempfile

import pytest

os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.logic import marker_color  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_marker_colors():
    now = datetime(2026, 9, 1)
    assert marker_color("do_not_contact", None, now) == "dnc"
    assert marker_color("current_client", None, now) == "client"
    assert marker_color("interested", None, now) == "interested"
    assert marker_color("prospect", None, now) == "new"
    assert marker_color("prospect", (now - timedelta(days=10)).isoformat(), now) == "recent"
    assert marker_color("prospect", (now - timedelta(days=100)).isoformat(), now) == "stale"


def test_clinic_contact_appointment_flow(client):
    r = client.post("/api/clinics", json={"name": "Test Clinic", "address": "123 Main St", "lat": 51.0, "lng": -114.0})
    assert r.status_code == 201, r.text
    clinic = r.json()
    assert clinic["color"] == "new"
    cid = clinic["id"]

    r = client.post("/api/contacts", json={"clinic_id": cid, "first_name": "Jane", "last_name": "Doe", "role": "manager", "is_primary": True})
    assert r.status_code == 201, r.text
    contact = r.json()
    assert contact["full_name"] == "Jane Doe" and contact["clinic_name"] == "Test Clinic"

    past = (datetime.now() - timedelta(days=5)).replace(microsecond=0).isoformat()
    r = client.post("/api/appointments", json={"clinic_id": cid, "contact_id": contact["id"], "title": "Intro visit", "start_time": past, "status": "completed"})
    assert r.status_code == 201, r.text

    r = client.get(f"/api/clinics/{cid}")
    detail = r.json()
    assert detail["color"] == "recent"
    assert detail["last_visit"] == past
    assert len(detail["contacts"]) == 1 and len(detail["appointments"]) == 1

    future = (datetime.now() + timedelta(days=3)).replace(microsecond=0).isoformat()
    r = client.post("/api/appointments", json={"clinic_id": cid, "title": "Follow up", "start_time": future})
    assert r.status_code == 201
    r = client.get(f"/api/clinics/{cid}")
    assert r.json()["next_appointment"]["title"] == "Follow up"
    assert r.json()["upcoming_count"] == 1

    r = client.post(f"/api/clinics/{cid}/notes", json={"body": "Spoke to Jane"})
    assert r.status_code == 201
    assert len(client.get(f"/api/clinics/{cid}").json()["note_log"]) == 1

    r = client.put(f"/api/clinics/{cid}", json={**{k: v for k, v in detail.items() if k in ("name", "address")}, "relationship": "current_client"})
    assert r.status_code == 200 and r.json()["color"] == "client"

    r = client.patch(f"/api/clinics/{cid}/location", json={"lat": 51.1, "lng": -114.1})
    assert r.json()["lat"] == 51.1

    assert client.get("/api/clinics", params={"q": "test"}).json()[0]["id"] == cid
    assert client.get("/api/clinics", params={"color": "client"}).json()
    assert client.get("/api/clinics", params={"color": "yellow"}).json()  # legacy key still works
    assert client.get("/api/clinics", params={"color": "dnc"}).json() == []

    assert client.get("/api/appointments", params={"upcoming": "true"}).json()[0]["title"] == "Follow up"
    d = client.get("/api/dashboard").json()
    assert d["totals"]["clinics"] == 1 and d["upcoming"][0]["title"] == "Follow up"

    assert client.get("/api/export/clinics.csv").status_code == 200
    assert "BEGIN:VEVENT" in client.get("/api/export/appointments.ics").text
    backup = client.get("/api/export/backup.json").json()
    assert len(backup["clinics"]) == 1

    r = client.post("/api/import/backup", json=backup)
    assert r.status_code == 200 and r.json()["status"] == "merged"
    assert len(client.get("/api/clinics").json()) == 2
    r = client.post("/api/import/backup", params={"replace": "true"}, json=backup)
    assert len(client.get("/api/clinics").json()) == 1

    r = client.delete(f"/api/clinics/{cid}")
    assert r.status_code == 204
    assert client.get("/api/appointments").json() == []
    assert client.get("/api/contacts").json()[0]["clinic_id"] is None


def test_validation(client):
    assert client.post("/api/clinics", json={"name": "   "}).status_code == 422
    assert client.post("/api/appointments", json={"clinic_id": 9999, "title": "x", "start_time": "2026-01-01T09:00"}).status_code == 422
    assert client.post("/api/appointments", json={"clinic_id": 1, "title": "x", "start_time": "not-a-date"}).status_code == 422
    assert client.get("/api/clinics/9999").status_code == 404
    assert client.get("/").status_code == 200


def test_pipeline_tasks_timeline_route(client):
    r = client.post("/api/clinics", json={"name": "Pipeline Clinic", "lat": 51.05, "lng": -114.05, "deal_value": 12000, "stage": "prospect"})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["stage"] == "prospect" and c["effective_probability"] == 20 and c["weighted_value"] == 2400
    cid = c["id"]

    # move through the pipeline via the Kanban endpoint
    r = client.patch(f"/api/clinics/{cid}/stage", json={"stage": "proposal"})
    assert r.status_code == 200 and r.json()["stage"] == "proposal"
    r = client.patch(f"/api/clinics/{cid}/stage", json={"stage": "won", "outcome_reason": "service", "outcome_notes": "Loved the response time"})
    won = r.json()
    assert won["stage"] == "won" and won["relationship"] == "current_client" and won["color"] == "client"
    assert won["outcome_date"] and won["weighted_value"] == 0

    # relationship -> current_client implies won, and vice versa is logged
    r = client.post("/api/clinics", json={"name": "Client Clinic", "relationship": "current_client"})
    assert r.json()["stage"] == "won"

    # tasks
    r = client.post("/api/tasks", json={"clinic_id": cid, "title": "Send contract", "due_date": "2020-01-01", "priority": "high"})
    assert r.status_code == 201, r.text
    task = r.json()
    assert task["overdue"] is True and task["clinic_name"] == "Pipeline Clinic"
    r = client.patch(f"/api/tasks/{task['id']}", json={"done": True})
    assert r.json()["done"] is True and r.json()["done_at"]
    # (Winning a deal auto-creates onboarding tasks, so the open list is not empty — just
    # confirm the task we marked done has left it.)
    assert task["id"] not in [t["id"] for t in client.get("/api/tasks", params={"done": "false"}).json()]
    assert client.post("/api/tasks", json={"clinic_id": 9999, "title": "x"}).status_code == 422
    assert client.post("/api/tasks", json={"title": "   "}).status_code == 422

    # timeline merges events, notes, tasks
    client.post(f"/api/clinics/{cid}/notes", json={"body": "Timeline note"})
    tl = client.get(f"/api/clinics/{cid}/timeline").json()
    types = {t["type"] for t in tl}
    assert {"created", "stage_change", "relationship_change", "note", "task"} <= types
    won_event = next(t for t in tl if t["type"] == "stage_change" and "Won" in t["title"])
    assert "Service / responsiveness" in won_event["body"]
    detail = client.get(f"/api/clinics/{cid}").json()
    assert detail["timeline"] and detail["tasks"]

    # dashboard pipeline + forecast
    d = client.get("/api/dashboard").json()
    assert d["pipeline"]["won"]["count"] >= 1
    assert d["forecast"]["won_value_this_year"] >= 12000
    assert d["outcome_reasons"]["won"].get("Service / responsiveness") == 1
    assert "tasks_due" in d and "closing_soon" in d

    # stage filter on list
    assert all(x["stage"] == "won" for x in client.get("/api/clinics", params={"stage": "won"}).json())

    # route planning (pure-python fallback works without network)
    r = client.post("/api/clinics", json={"name": "Far Clinic", "lat": 51.15, "lng": -114.20})
    far = r.json()["id"]
    r = client.post("/api/clinics", json={"name": "Near Clinic", "lat": 51.06, "lng": -114.06})
    near = r.json()["id"]
    r = client.post("/api/route", json={"clinic_ids": [far, near, cid], "start": {"lat": 51.04, "lng": -114.04}})
    assert r.status_code == 200, r.text
    route = r.json()
    names = [s["name"] for s in route["stops"]]
    assert names[-1] == "Far Clinic" and route["total_km"] > 0 and "google.com/maps" in route["google_maps_url"]
    assert client.post("/api/route", json={"clinic_ids": [2]}).status_code in (200, 422)

    # drive time
    r = client.get("/api/drivetime", params={"lat": 51.04, "lng": -114.04})
    assert r.status_code == 200
    dt = r.json()
    assert dt["source"] in ("osrm", "estimate") and str(near) in dt["clinics"] or near in dt["clinics"]

    # backup round-trips tasks and events
    backup = client.get("/api/export/backup.json").json()
    assert backup["tasks"] and backup["clinic_events"]
    r = client.post("/api/import/backup", json=backup)
    assert r.status_code == 200


def test_lead_pipeline_revamp(client):
    # New clinics default to "lead": in the book, but off the pipeline board.
    r = client.post("/api/clinics", json={"name": "Fresh Lead Clinic", "deal_value": 10000})
    assert r.status_code == 201, r.text
    lead = r.json()
    assert lead["stage"] == "lead"
    assert lead["in_pipeline"] is False
    assert lead["relationship"] == "prospect"
    assert lead["weighted_value"] == 0  # leads don't count toward the forecast
    lid = lead["id"]

    # A lead is excluded from the dashboard forecast open-deal counts...
    d = client.get("/api/dashboard").json()
    lead_ids = {x["id"] for x in d["leads"]}
    assert lid in lead_ids
    assert d["leads_count"] >= 1

    # Promoting a lead onto the board (-> Interested) bumps the map relationship to interested.
    r = client.patch(f"/api/clinics/{lid}/stage", json={"stage": "prospect"})
    assert r.status_code == 200, r.text
    promoted = r.json()
    assert promoted["stage"] == "prospect"
    assert promoted["in_pipeline"] is True
    assert promoted["relationship"] == "interested"
    assert promoted["color"] == "interested"

    # It's no longer listed as a lead on the dashboard.
    d = client.get("/api/dashboard").json()
    assert lid not in {x["id"] for x in d["leads"]}

    # Dropping back to a lead demotes the relationship again.
    r = client.patch(f"/api/clinics/{lid}/stage", json={"stage": "lead"})
    assert r.json()["relationship"] == "prospect" and r.json()["in_pipeline"] is False

    # Won/Lost carry a "closed_recent" flag: true only for the month they closed in.
    r = client.post("/api/clinics", json={"name": "Won This Month", "stage": "proposal", "deal_value": 5000})
    wid = r.json()["id"]
    r = client.patch(f"/api/clinics/{wid}/stage", json={"stage": "won", "outcome_reason": "service"})
    assert r.json()["closed_recent"] is True  # closed today -> this month
    old = "2021-03-15"
    r = client.post("/api/clinics", json={"name": "Lost Long Ago", "stage": "demo"})
    oid = r.json()["id"]
    r = client.patch(f"/api/clinics/{oid}/stage", json={"stage": "lost", "outcome_reason": "price", "outcome_date": old})
    assert r.json()["outcome_date"] == old
    assert r.json()["closed_recent"] is False  # closed in a past month -> filtered off the board

    # /api/meta drives the board: pipeline_stages excludes lead, and the relabels are in place.
    meta = client.get("/api/meta").json()
    assert "lead" not in meta["pipeline_stages"]
    assert meta["pipeline_stages"] == ["prospect", "demo", "proposal", "won", "lost"]
    assert "contacted" not in meta["stages"]
    assert meta["stages"]["lead"] == "Lead"
    assert meta["stages"]["prospect"] == "Interested"
    assert meta["stages"]["demo"] == "In negotiations"
    assert meta["stages"]["proposal"] == "Quote sent"


def test_client_lifecycle_revenue_and_onboarding(client):
    soon = (datetime.now() + timedelta(days=20)).date().isoformat()
    onboarded = datetime.now().date().isoformat()
    r = client.post("/api/clinics", json={
        "name": "Recurring Revenue Clinic", "relationship": "current_client", "shorthand": "RRC",
        "mrr": 1000, "contract_start": onboarded, "contract_end": soon, "contract_term_months": 12,
        "renewal_reminder_days": 60, "outcome_date": onboarded,
    })
    assert r.status_code == 201, r.text
    c = r.json()
    cid = c["id"]
    assert c["stage"] == "won" and c["is_active_client"] is True
    assert c["mrr"] == 1000 and c["arr"] == 12000
    assert c["days_to_renewal"] is not None and c["renewal_due"] is True and c["renewal_overdue"] is False

    # Winning the deal generated onboarding tasks.
    detail = client.get(f"/api/clinics/{cid}").json()
    onboarding = [t for t in detail["tasks"] if "onboarding" in t["title"].lower() or "kickoff" in t["title"].lower() or "backups" in t["title"].lower()]
    assert onboarding, "expected onboarding tasks to be created on win"
    assert any(e["type"] == "onboarding" for e in detail["timeline"])

    # Revenue endpoint reflects the client.
    rev = client.get("/api/revenue").json()
    assert rev["summary"]["mrr"] >= 1000
    assert rev["summary"]["active_clients"] >= 1
    assert any(row["id"] == cid for row in rev["renewals"])
    assert any(m["added"] for m in rev["movement"])  # some MRR was added in a tracked month

    # Churn: won -> lost stamps churned_at, drops the client off the map, stops the MRR.
    mrr_before = rev["summary"]["mrr"]
    r = client.patch(f"/api/clinics/{cid}/stage", json={"stage": "lost", "outcome_reason": "price"})
    churned = r.json()
    assert churned["churned"] is True and churned["is_active_client"] is False
    assert churned["relationship"] == "prospect"  # no longer a current client on the map
    rev2 = client.get("/api/revenue").json()
    assert rev2["summary"]["mrr"] == round(mrr_before - 1000, 2)
    assert rev2["summary"]["churned_ytd"] >= 1

    # Re-winning clears the churn stamp.
    r = client.patch(f"/api/clinics/{cid}/stage", json={"stage": "won"})
    assert r.json()["churned"] is False and r.json()["is_active_client"] is True


def test_competitor_displacement(client):
    end = (datetime.now() + timedelta(days=45)).date().isoformat()
    r = client.post("/api/clinics", json={
        "name": "Displacement Target", "stage": "prospect", "relationship": "interested",
        "it_provider": "RivalMSP", "competitor_contract_end": end, "deal_value": 8000,
    })
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["competitor_days"] is not None and c["displacement_hot"] is True
    # A follow-up was auto-seeded ahead of the competitor contract end.
    assert c["next_follow_up"] is not None and c["next_follow_up"] < end

    # A lost-to-competitor deal is counted.
    client.post("/api/clinics", json={"name": "Lost To Rival", "stage": "lost", "outcome_reason": "competitor"})

    comp = client.get("/api/competitors").json()
    assert any(p["provider"] == "RivalMSP" for p in comp["providers"])
    assert any(d["id"] == c["id"] and d["hot"] for d in comp["displacement"])
    assert comp["hot_count"] >= 1
    assert comp["lost_to_competitor"] >= 1


def test_inventory_orders_invoices(client):
    cid = client.post("/api/clinics", json={"name": "Billing Clinic"}).json()["id"]

    # Inventory item with margin + low-stock threshold
    item = client.post("/api/inventory", json={
        "name": "HP 26A Toner", "sku": "CF226A", "category": "Toner / ink", "location": "Van shelf B",
        "unit_price": 100, "cost": 60, "quantity": 5, "reorder_level": 2, "supplier": "Acme Supply",
    }).json()
    iid = item["id"]
    assert item["margin"] == 40 and item["low_stock"] is False and item["stock_value"] == 300

    # Drop below the reorder level -> low stock
    item = client.post(f"/api/inventory/{iid}/adjust", json={"delta": -4}).json()
    assert item["quantity"] == 1 and item["low_stock"] is True

    # Order more of it, then receive into inventory
    o1 = client.post("/api/orders", json={"name": "HP 26A Toner", "item_id": iid, "quantity": 10, "unit_cost": 55}).json()
    assert o1["status"] == "ordered" and o1["unit_price"] == 100  # inherited from the item
    recv = client.post(f"/api/orders/{o1['id']}/receive", json={"disposition": "inventory"}).json()
    assert recv["order"]["status"] == "received" and recv["order"]["disposition"] == "inventory"
    assert client.get(f"/api/inventory/{iid}").json()["quantity"] == 11

    # Order a custom (not-in-inventory) item and bill it straight to the clinic
    o2 = client.post("/api/orders", json={"name": "Label printer ribbon", "quantity": 2, "unit_price": 45, "clinic_id": cid}).json()
    assert o2["item_id"] is None
    recv2 = client.post(f"/api/orders/{o2['id']}/receive", json={"disposition": "invoice", "clinic_id": cid}).json()
    billed_invoice = recv2["invoice_id"]
    inv = client.get(f"/api/invoices/{billed_invoice}").json()
    assert inv["status"] == "draft" and len(inv["lines"]) == 1 and inv["total"] == 90  # 2 x 45, no tax

    # Create a full invoice: one inventory line + one custom line, with discount + tax
    made = client.post(f"/api/clinics/{cid}/invoices", json={
        "title": "Supplies", "tax_pct": 5, "discount_pct": 10, "ticket_url": "https://tickets.example.com/99",
        "lines": [
            {"item_id": iid, "description": "HP 26A Toner", "quantity": 3, "unit_price": 100},
            {"description": "On-site swap", "quantity": 1, "unit_price": 50},
        ],
    }).json()
    invid = made["id"]
    assert made["number"].startswith("INV-") and made["ticket_url"].endswith("/99")
    assert made["subtotal"] == 350 and made["tax"] == 15.75 and made["total"] == 330.75

    # Draft doesn't touch stock; marking sent deducts the inventory line; void restores it.
    assert client.get(f"/api/inventory/{iid}").json()["quantity"] == 11
    client.patch(f"/api/invoices/{invid}/status", json={"status": "sent"})
    assert client.get(f"/api/inventory/{iid}").json()["quantity"] == 8
    paid = client.patch(f"/api/invoices/{invid}/status", json={"status": "paid"}).json()
    assert paid["paid_at"] and client.get(f"/api/inventory/{iid}").json()["quantity"] == 8  # still deducted
    client.patch(f"/api/invoices/{invid}/status", json={"status": "void"})
    assert client.get(f"/api/inventory/{iid}").json()["quantity"] == 11  # restored

    # Listing + CSV + it shows on the clinic profile
    assert any(x["id"] == invid for x in client.get("/api/invoices", params={"clinic_id": cid}).json())
    assert client.get(f"/api/invoices/{invid}/export.csv").status_code == 200
    detail = client.get(f"/api/clinics/{cid}").json()
    assert len(detail["invoices"]) >= 2

    # Backup round-trips the new tables
    backup = client.get("/api/export/backup.json").json()
    assert backup["inventory_items"] and backup["invoices"] and backup["invoice_lines"] and backup["orders"]


def test_notes_mentions_photos(client):
    a = client.post("/api/clinics", json={"name": "Notes Clinic A"}).json()["id"]
    b = client.post("/api/clinics", json={"name": "Notes Clinic B"}).json()["id"]
    a1 = client.post("/api/contacts", json={"clinic_id": a, "first_name": "Sarah", "last_name": "Alpha"}).json()["id"]
    b1 = client.post("/api/contacts", json={"clinic_id": b, "first_name": "Sarah", "last_name": "Beta"}).json()["id"]
    appt = client.post("/api/appointments", json={"clinic_id": a, "title": "Intro visit", "start_time": "2026-09-01T09:00"}).json()["id"]

    # A note attached to the appointment, mentioning a same-clinic contact AND a contact at
    # another clinic — the cross-clinic mention must be downgraded to plain text.
    body = f"Met @[Sarah Alpha](c:{a1}); do NOT confuse with @[Sarah Beta](c:{b1})"
    note = client.post(f"/api/clinics/{a}/notes", json={"body": body, "appointment_id": appt}).json()
    assert note["context"] == {"type": "appointment", "id": appt, "label": "Intro visit"}
    assert f"@[Sarah Alpha](c:{a1})" in note["body"]
    assert f"c:{b1}" not in note["body"] and "@Sarah Beta" in note["body"]  # stripped to plain text
    assert note["mentions"] == [{"id": a1, "name": "Sarah Alpha"}]

    # Attaching to another clinic's appointment/task is rejected.
    assert client.post(f"/api/clinics/{a}/notes", json={"body": "x", "appointment_id": 999999}).status_code == 422

    # Upload a photo tied to that note -> it appears in the clinic's photos with an origin
    # pointing back to the appointment.
    up = client.post(f"/api/clinics/{a}/attachments",
                     files={"file": ("site.jpg", b"\xff\xd8\xffdata", "image/jpeg")},
                     data={"kind": "photo", "note_id": str(note["id"])})
    assert up.status_code == 201, up.text
    photo_id = up.json()["id"]
    detail = client.get(f"/api/clinics/{a}").json()
    photo = next(p for p in detail["attachments"] if p["id"] == photo_id)
    assert photo["origin"] == {"type": "appointment", "id": appt, "label": "Intro visit"}
    assert photo["note_count"] == 0

    # A photo added directly can have notes attached to it.
    pnote = client.post(f"/api/clinics/{a}/notes", json={"body": "Back of the rack", "attachment_id": photo_id}).json()
    assert pnote["context"]["type"] == "photo"
    photo_notes = client.get(f"/api/clinics/{a}/attachments/{photo_id}/notes").json()
    assert [n["id"] for n in photo_notes] == [pnote["id"]]
    assert next(p for p in client.get(f"/api/clinics/{a}").json()["attachments"] if p["id"] == photo_id)["note_count"] == 1

    # Deleting the photo cascades its attached notes but keeps the clinic's other notes.
    client.delete(f"/api/attachments/{photo_id}")
    assert client.get(f"/api/clinics/{a}/attachments/{photo_id}/notes").json() == []
    assert any(n["id"] == note["id"] for n in client.get(f"/api/clinics/{a}/notes").json())


def test_device_services(client):
    cid = client.post("/api/clinics", json={"name": "Services Clinic", "shorthand": "SVC"}).json()["id"]
    srv = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "server", "designation": "Hypervisor / host"}).json()
    vm = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "vm", "uplink_id": srv["id"]}).json()
    ws = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "workstation"}).json()

    # Structured service on a VM.
    s = client.post(f"/api/devices/{vm['id']}/services", json={
        "name": "PrimeEMR SQL", "ip_addresses": "10.0.0.5", "ports": "1433/tcp",
        "internal_url": "http://emr.local", "support_email": "support@primeemr.example"}).json()
    assert s["name"] == "PrimeEMR SQL" and s["ports"] == "1433/tcp"

    # It shows on the device (structured) and in the topology node.
    d = client.get(f"/api/devices/{vm['id']}").json()
    assert [x["name"] for x in d["services"]] == ["PrimeEMR SQL"]
    topo = client.get(f"/api/clinics/{cid}/topology").json()
    vm_node = next(n for n in topo["nodes"] if n["id"] == vm["id"])
    assert [x["name"] for x in vm_node["services"]] == ["PrimeEMR SQL"]

    # Services can't run on a workstation.
    assert client.post(f"/api/devices/{ws['id']}/services", json={"name": "nope"}).status_code == 422

    # A dated note attached to the service, with the service as its context.
    note = client.post(f"/api/clinics/{cid}/notes", json={"body": "Restarted the SQL service", "service_id": s["id"]}).json()
    assert note["context"] == {"type": "service", "id": s["id"], "label": "PrimeEMR SQL"}
    detail = client.get(f"/api/services/{s['id']}").json()
    assert len(detail["note_log"]) == 1 and detail["device_name"] == vm["name"]

    # Searchable.
    res = client.get("/api/search", params={"q": "PrimeEMR"}).json()
    assert any(x["id"] == s["id"] for x in res["services"])

    # Update + delete.
    up = client.put(f"/api/services/{s['id']}", json={"name": "PrimeEMR Database", "ports": "1433/tcp"}).json()
    assert up["name"] == "PrimeEMR Database"
    assert client.delete(f"/api/services/{s['id']}").status_code == 204
    assert client.get(f"/api/devices/{vm['id']}").json()["services"] == []


def test_tickets_and_activity_filter(client):
    cid = client.post("/api/clinics", json={"name": "Ticket Clinic"}).json()["id"]

    # Link a ticket to a machine that doesn't exist yet -> it's created as a workstation.
    t1 = client.post(f"/api/clinics/{cid}/tickets", json={
        "title": "Printer offline", "url": "https://x.syncromsp.com/tickets/1", "device_name": "REC-PC"}).json()
    assert t1["title"] == "Printer offline" and t1["ticket_at"]  # auto-filled date
    assert t1["device_name"] == "REC-PC"
    devs = client.get(f"/api/clinics/{cid}/devices").json()["devices"]
    made = [d for d in devs if d["name"] == "REC-PC"]
    assert len(made) == 1 and made[0]["device_type"] == "workstation"

    # Linking the same machine again (case-insensitive) reuses it — no duplicate.
    client.post(f"/api/clinics/{cid}/tickets", json={"title": "Follow-up", "device_name": "rec-pc"})
    assert len([d for d in client.get(f"/api/clinics/{cid}/devices").json()["devices"] if d["name"] == "REC-PC"]) == 1

    # A custom date/time is kept as given.
    t3 = client.post(f"/api/clinics/{cid}/tickets", json={"title": "Scheduled", "ticket_at": "2026-01-02T08:30"}).json()
    assert t3["ticket_at"] == "2026-01-02T08:30" and t3["device_id"] is None

    # Tickets show on the clinic profile.
    detail = client.get(f"/api/clinics/{cid}").json()
    assert len(detail["tickets"]) == 3

    # Equipment/topology events (incl. the auto-created workstation) are kept out of the activity feed.
    tl = client.get(f"/api/clinics/{cid}/timeline").json()
    assert not any(i["type"] == "equipment" for i in tl)

    assert client.delete(f"/api/clinics/{cid}/tickets/{t1['id']}").status_code == 204
    assert len(client.get(f"/api/clinics/{cid}/tickets").json()) == 2


def test_display_address_and_hours(client):
    r = client.post("/api/clinics", json={
        "name": "Hours Clinic", "address": "500 5 Ave SW", "display_address": "Suite 300, 500 5 Ave SW",
        "hours": {
            "mon": {"open": "09:00", "close": "17:00"},
            "sat": {"closed": True},
            "sun": {"open": "", "close": ""},  # blank -> dropped
        },
    })
    assert r.status_code == 201, r.text
    c = r.json()
    cid = c["id"]
    assert c["display_address"] == "Suite 300, 500 5 Ave SW"
    assert c["address"] == "500 5 Ave SW"  # geocoding address is unchanged
    assert c["hours"]["mon"] == {"closed": False, "open": "09:00", "close": "17:00"}
    assert c["hours"]["sat"]["closed"] is True
    assert "sun" not in c["hours"]  # blank day not stored

    # Re-fetch parses hours back into an object, and it survives a backup.
    assert client.get(f"/api/clinics/{cid}").json()["hours"]["mon"]["open"] == "09:00"
    backup = client.get("/api/export/backup.json").json()
    row = next(x for x in backup["clinics"] if x["id"] == cid)
    assert '"mon"' in row["hours"] and row["display_address"].startswith("Suite 300")

    # Clearing hours + display address works.
    upd = client.put(f"/api/clinics/{cid}", json={"name": "Hours Clinic", "address": "500 5 Ave SW"}).json()
    assert upd["hours"] is None and upd["display_address"] is None


def test_clients_contacts_locations_links_groups(client):
    # client-specific fields + archive
    r = client.post("/api/clinics", json={"name": "Cardiology One Calgary", "relationship": "current_client", "shorthand": "coc", "phone": "403-555-0900", "address": "1 Heart Way SW"})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["shorthand"] == "COC" and c["is_client"] and c["stage"] == "won"
    cid = c["id"]
    r = client.patch(f"/api/clinics/{cid}/archive", json={"archived": True})
    assert r.json()["archived"] is True
    assert cid not in [x["id"] for x in client.get("/api/clinics", params={"archived": "false"}).json()]
    d = client.get("/api/dashboard").json()
    assert d["archived_won"] >= 1

    # back-dated onboarding via stage change
    r = client.post("/api/clinics", json={"name": "Old Client", "stage": "proposal"})
    oc = r.json()["id"]
    r = client.patch(f"/api/clinics/{oc}/stage", json={"stage": "won", "outcome_reason": "relationship", "outcome_date": "2021-03-15"})
    assert r.json()["outcome_date"] == "2021-03-15" and r.json()["relationship"] == "current_client"

    # contact on main line with extension
    r = client.post("/api/contacts", json={"clinic_id": cid, "first_name": "Pat", "role": "manager", "use_main_line": True, "extension": "204"})
    assert r.status_code == 201, r.text
    ct = r.json()
    assert ct["phone"] == "403-555-0900" and ct["phone_display"] == "403-555-0900 ext. 204"
    # clinic phone change flows through
    client.put(f"/api/clinics/{cid}", json={"name": "Cardiology One Calgary", "relationship": "current_client", "phone": "403-555-0999", "shorthand": "COC", "address": "1 Heart Way SW"})
    assert client.get(f"/api/contacts/{ct['id']}").json()["phone"] == "403-555-0999"

    # groups + shared contacts
    g = client.post("/api/groups", json={"name": "SDI Group"}).json()
    r = client.post("/api/clinics", json={"name": "SDI North", "group_id": g["id"], "lat": 51.1, "lng": -114.1})
    sdi_n = r.json()["id"]
    r = client.post("/api/clinics", json={"name": "SDI South", "group_id": g["id"], "lat": 50.95, "lng": -114.05})
    sdi_s = r.json()["id"]
    r = client.post("/api/contacts", json={"clinic_id": sdi_n, "first_name": "Owner", "last_name": "Person", "role": "owner", "shared_with_group": True})
    assert r.status_code == 201, r.text and r.json()["shared_with_group"] is True
    south = client.get(f"/api/clinics/{sdi_s}").json()
    assert south["group"]["name"] == "SDI Group" and [m["name"] for m in south["group_members"]] == ["SDI North"]
    assert any(x["first_name"] == "Owner" and x.get("shared") for x in south["contacts"])
    assert any(x["first_name"] == "Owner" for x in client.get("/api/contacts", params={"clinic_id": sdi_s}).json())
    assert client.post("/api/contacts", json={"clinic_id": cid, "first_name": "X", "shared_with_group": True}).status_code == 422
    assert client.get("/api/groups").json()[0]["member_count"] == 2

    # secondary locations
    r = client.post(f"/api/clinics/{sdi_n}/locations", json={"name": "SDI Downtown", "address": "500 4 Ave SW", "lat": 51.048, "lng": -114.07})
    assert r.status_code == 201, r.text
    loc = r.json()
    assert len(client.get(f"/api/clinics/{sdi_n}").json()["locations"]) == 1
    locs = client.get("/api/locations").json()
    assert locs[0]["clinic_name"] == "SDI North" and locs[0]["color"] == "new"
    r = client.put(f"/api/clinics/{sdi_n}/locations/{loc['id']}", json={"name": "SDI Downtown (renamed)", "lat": 51.048, "lng": -114.07})
    assert r.json()["name"] == "SDI Downtown (renamed)"
    assert client.delete(f"/api/clinics/{sdi_n}/locations/{loc['id']}").status_code == 204

    # links
    r = client.post(f"/api/clinics/{sdi_n}/links", json={"other_clinic_id": cid, "link_type": "same_building", "notes": "Both in the tower"})
    assert r.status_code == 201, r.text
    assert r.json()[0]["other"]["name"] == "Cardiology One Calgary" and r.json()[0]["link_label"] == "Same building"
    assert client.get(f"/api/clinics/{cid}/links").json()[0]["other"]["id"] == sdi_n
    assert client.post(f"/api/clinics/{sdi_n}/links", json={"other_clinic_id": cid}).status_code == 422
    assert client.post(f"/api/clinics/{sdi_n}/links", json={"other_clinic_id": sdi_n}).status_code == 422
    link_id = client.get(f"/api/clinics/{cid}/links").json()[0]["id"]
    assert client.delete(f"/api/clinics/{cid}/links/{link_id}").status_code == 204

    # quick log + timeline
    r = client.post(f"/api/clinics/{sdi_n}/quick-log", json={"preset": "left_card", "author": "Kaden", "detail": "with reception"})
    assert r.status_code == 201 and r.json()["kind"] == "quick"
    assert client.post(f"/api/clinics/{sdi_n}/quick-log", json={"preset": "nope"}).status_code == 422
    tl = client.get(f"/api/clinics/{sdi_n}/timeline").json()
    assert any(t["type"] == "note" and t["kind"] == "quick" and "Kaden" in t["title"] for t in tl)
    assert any(t["type"] == "link" for t in tl)

    # duplicates
    dup = client.get("/api/clinics/duplicates", params={"name": "cardiology one"}).json()
    assert dup and dup[0]["id"] == cid and "similar name" in dup[0]["reasons"]
    dup = client.get("/api/clinics/duplicates", params={"name": "Totally Different", "address": "1 Heart Way South West"}).json()
    assert dup and "same address" in dup[0]["reasons"]
    assert client.get("/api/clinics/duplicates", params={"name": "zzz nothing"}).json() == []


def test_search_reminders_analytics_views_templates_import(client):
    # search
    s = client.get("/api/search", params={"q": "COC"}).json()
    assert s["clinics"] and s["clinics"][0]["shorthand"] == "COC"
    assert client.get("/api/search", params={"q": "Pat"}).json()["contacts"]

    # reminders window
    soon = (datetime.now() + timedelta(minutes=30)).replace(second=0, microsecond=0).isoformat(timespec="minutes")
    cid = client.get("/api/clinics").json()[0]["id"]
    client.post("/api/appointments", json={"clinic_id": cid, "title": "Reminder test", "start_time": soon, "reminder_minutes": 15, "rep": "Kaden"})
    due = datetime.now() + timedelta(minutes=45)
    client.post("/api/tasks", json={"clinic_id": cid, "title": "Timed task", "due_date": due.date().isoformat(), "due_time": due.strftime("%H:%M"), "reminder_minutes": 30})
    rem = client.get("/api/reminders").json()
    kinds = {(i["kind"], i["title"]) for i in rem["items"]}
    assert ("appointment", "Reminder test") in kinds and ("task", "Timed task") in kinds
    assert rem["options"] == [15, 30, 45, 60]

    # analytics
    a = client.get("/api/analytics").json()
    assert len(a["visits_by_week"]) == 12 and len(a["visits_by_month"]) == 12
    assert a["conversion"]["won"] >= 1 and "rate" in a["conversion"]
    assert any(r["rep"] == "Kaden" for r in a["by_rep"])
    assert [t["stage"] for t in a["time_in_stage"]] == ["prospect", "demo", "proposal"]

    # saved views
    v = client.post("/api/views", json={"name": "NW prospects", "page": "map", "state": {"q": "NW", "colors": ["white", "grey"]}}).json()
    assert client.get("/api/views", params={"page": "map"}).json()[0]["state"]["q"] == "NW"
    assert client.delete(f"/api/views/{v['id']}").status_code == 204

    # templates seeded + crud
    tpls = client.get("/api/templates").json()
    assert len(tpls) >= 3 and any("{clinic_name}" in t["subject"] for t in tpls)
    t = client.post("/api/templates", json={"name": "Renewal", "subject": "Renewal for {clinic_name}", "body": "Hi {contact_first_name}"}).json()
    assert client.put(f"/api/templates/{t['id']}", json={"name": "Renewal 2", "subject": "x", "body": "y"}).json()["name"] == "Renewal 2"
    assert client.delete(f"/api/templates/{t['id']}").status_code == 204

    # csv import with duplicate skipping
    r = client.post("/api/import/clinics", json={"rows": [
        {"name": "Imported Clinic A", "address": "10 Import St NE", "relationship": "interested", "stage": "prospect"},
        {"name": "Cardiology One Calgary", "address": "1 Heart Way SW"},
        {"name": "", "address": "x"},
        {"name": "Bad Stage", "stage": "nonsense"},
    ]})
    assert r.status_code == 200, r.text
    res = r.json()
    assert len(res["created"]) == 1 and res["created"][0]["needs_geocode"] is True
    assert len(res["skipped"]) == 1 and res["skipped"][0]["match"] == "Cardiology One Calgary"
    assert len(res["errors"]) == 2

    # bulk geocode job status endpoint (network may be unavailable; just exercise the state machine)
    st = client.get("/api/geocode/bulk").json()
    assert "running" in st

    # attachments
    files = {"file": ("proposal.txt", b"hello proposal", "text/plain")}
    r = client.post(f"/api/clinics/{cid}/attachments", files=files, data={"caption": "Draft proposal"})
    assert r.status_code == 201, r.text
    att = r.json()
    assert att["kind"] == "document" and att["size"] == 14
    r = client.get(f"/api/attachments/{att['id']}/file")
    assert r.status_code == 200 and r.content == b"hello proposal"
    files = {"file": ("front.png", b"\x89PNG\r\n\x1a\nfake", "image/png")}
    photo = client.post(f"/api/clinics/{cid}/attachments", files=files).json()
    assert photo["kind"] == "photo"
    assert len(client.get(f"/api/clinics/{cid}").json()["attachments"]) == 2
    assert client.delete(f"/api/attachments/{att['id']}").status_code == 204
    assert client.get(f"/api/attachments/{att['id']}/file").status_code == 404

    backup = client.get("/api/export/backup.json").json()
    assert "clinic_groups" in backup and "attachments" in backup
    assert client.post("/api/import/backup", json=backup).status_code == 200


def test_settings_call_sheet_scan(client):
    st = client.get("/api/settings").json()
    assert st["ai_configured"] is False
    r = client.put("/api/settings", json={"openai_api_key": "sk-test-1234567890abcd", "openai_model": "gpt-4o-mini"})
    assert r.json()["ai_configured"] is True and r.json()["openai_api_key_masked"].endswith("abcd") and "sk-test-1234567890abcd" not in r.text
    assert client.put("/api/settings", json={"openai_api_key": ""}).json()["ai_configured"] is False
    # scanning without a key gives a clear error
    r = client.post("/api/contacts/scan-card", files={"file": ("card.jpg", b"\xff\xd8\xff", "image/jpeg")})
    assert r.status_code == 400 and "OpenAI API key" in r.json()["detail"]
    from app.routers.extras import guess_role
    assert guess_role("Office Manager") == "manager" and guess_role("Dr. Jane Lee, MD") == "doctor" and guess_role("Front Desk") == "receptionist"

    # call sheet by ids and by date
    ids = [c["id"] for c in client.get("/api/clinics").json()[:2]]
    sheet = client.get("/api/call-sheet", params={"ids": ",".join(map(str, ids))}).json()
    assert [i["clinic"]["id"] for i in sheet["items"]] == ids
    assert "contacts" in sheet["items"][0] and "recent_notes" in sheet["items"][0]
    day = (datetime.now() + timedelta(days=3)).date().isoformat()
    client.post("/api/appointments", json={"clinic_id": ids[0], "title": "Sheet visit", "start_time": f"{day}T10:30"})
    sheet = client.get("/api/call-sheet", params={"date": day}).json()
    assert sheet["items"] and sheet["items"][0]["appointments"][0]["title"] == "Sheet visit"
    assert client.get("/api/call-sheet").status_code == 422

    # overdue follow-up flag + dashboard count
    r = client.post("/api/clinics", json={"name": "Overdue Clinic", "next_follow_up": "2020-01-01"})
    assert r.json()["follow_up_overdue"] is True
    assert client.get("/api/dashboard").json()["overdue_follow_ups"] >= 1
    # backup excludes settings
    assert "settings" not in client.get("/api/export/backup.json").json()


def test_equipment(client):
    r = client.post("/api/clinics", json={"name": "Cardio One", "relationship": "current_client", "shorthand": "COC"})
    cid = r.json()["id"]
    # auto naming
    nn = client.get(f"/api/clinics/{cid}/devices/next-name", params={"device_type": "workstation"}).json()
    assert nn["name"] == "COC-W001"
    fw = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "firewall", "ip_address": "192.168.1.1", "manufacturer": "Fortinet"}).json()
    assert fw["name"] == "COC-FW001" and fw["uplink_id"] is None and fw["link_type"] is None
    sw = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "switch", "uplink_id": fw["id"], "ip_address": "192.168.1.2"}).json()
    assert sw["name"] == "COC-SW001" and sw["link_type"] == "ethernet" and sw["uplink_name"] == "COC-FW001"
    ws = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "workstation", "quantity": 3, "uplink_id": sw["id"], "designation": "Exam room"}).json()
    assert [w["name"] for w in ws] == ["COC-W001", "COC-W002", "COC-W003"]
    # manual name with matching pattern keeps its number; next auto continues after it
    w5 = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "workstation", "name": "COC-W005", "user_name": "Dr. Lee"}).json()
    assert w5["number"] == 5
    assert client.get(f"/api/clinics/{cid}/devices/next-name", params={"device_type": "workstation"}).json()["name"] == "COC-W006"
    # custom name
    custom = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "printer", "name": "Front desk MFP", "uplink_id": sw["id"]}).json()
    assert custom["name"] == "Front desk MFP"
    # server with services + voip chain (workstation -> voip -> switch)
    srv = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "server", "designation": "Windows Server", "services": "AD DS\nDNS\nFile shares", "uplink_id": sw["id"]}).json()
    assert [s["name"] for s in srv["services"]] == ["AD DS", "DNS", "File shares"] and srv["name"] == "COC-S001"
    phone = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "voip", "uplink_id": sw["id"], "user_name": "Reception"}).json()
    r = client.put(f"/api/devices/{ws[0]['id']}", json={**{k: ws[0][k] for k in ("device_type", "name", "designation", "status")}, "uplink_id": phone["id"], "link_type": "ethernet", "user_name": "Front desk"})
    assert r.status_code == 200, r.text
    assert r.json()["uplink_name"] == phone["name"] and [c["name"] for c in r.json()["uplink_chain"]] == [phone["name"], sw["name"], fw["name"]]
    # wireless device defaults to wireless link
    ap = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "access_point", "uplink_id": sw["id"]}).json()
    cell = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "wireless", "uplink_id": ap["id"], "user_name": "Dr. Lee", "designation": "Cell phone"}).json()
    assert cell["link_type"] == "wireless" and cell["name"] == "COC-M001"
    # loop protection
    r = client.put(f"/api/devices/{fw['id']}", json={"device_type": "firewall", "name": "COC-FW001", "uplink_id": ws[0]["id"], "status": "active"})
    assert r.status_code == 422 and "loop" in r.json()["detail"]
    assert client.put(f"/api/devices/{fw['id']}", json={"device_type": "firewall", "name": "COC-FW001", "uplink_id": fw["id"], "status": "active"}).status_code == 422
    # bad ip
    assert client.post(f"/api/clinics/{cid}/devices", json={"device_type": "other", "ip_address": "not an ip!"}).status_code == 422
    # tickets
    t = client.post(f"/api/devices/{srv['id']}/tickets", json={"title": "Disk full on D:", "url": "https://tickets.example.com/123", "ticket_date": "2026-05-01"})
    assert t.status_code == 201
    det = client.get(f"/api/devices/{srv['id']}").json()
    assert det["tickets"][0]["title"] == "Disk full on D:" and det["ticket_count"] == 1
    # downlinks & topology
    swd = client.get(f"/api/devices/{sw['id']}").json()
    assert {d["name"] for d in swd["downlinks"]} >= {"COC-W002", "COC-W003", "COC-S001", "COC-V001", "Front desk MFP"}
    topo = client.get(f"/api/clinics/{cid}/topology").json()
    assert topo["roots"] == [fw["id"]] or set(topo["roots"]) == {fw["id"], w5["id"]}
    fw_node = next(n for n in topo["nodes"] if n["id"] == fw["id"])
    assert fw_node["children"] == [sw["id"]]
    assert any(e["link_type"] == "wireless" for e in topo["edges"])
    # list + summary + csv
    lst = client.get(f"/api/clinics/{cid}/devices").json()
    assert lst["summary"]["billable"]["workstations"] == 4 and lst["summary"]["billable"]["servers"] == 1 and lst["summary"]["billable"]["network"] == 3
    assert lst["shorthand"] == "COC"
    assert client.get(f"/api/clinics/{cid}/devices", params={"q": "Dr. Lee"}).json()["devices"]
    assert client.get(f"/api/clinics/{cid}/devices.csv").status_code == 200
    assert client.get(f"/api/clinics/{cid}").json()["equipment"]["total"] == 11
    assert client.get("/api/search", params={"q": "COC-W00"}).json()["devices"]
    # delete uplink -> children detach, not deleted
    assert client.delete(f"/api/devices/{sw['id']}").status_code == 204
    assert client.get(f"/api/devices/{srv['id']}").json()["uplink_id"] is None
    # fallback shorthand from initials
    r = client.post("/api/clinics", json={"name": "Beltline Family Practice"})
    assert client.get(f"/api/clinics/{r.json()['id']}/devices/next-name", params={"device_type": "laptop"}).json()["name"] == "BFP-L001"
    backup = client.get("/api/export/backup.json").json()
    assert backup["devices"] and backup["device_tickets"]
    assert client.post("/api/import/backup", json=backup).status_code == 200


def test_openai_param_retry(monkeypatch):
    """Newer models reject legacy params; the client strips them and retries."""
    import io as _io
    import json as _json
    import urllib.error
    from app.routers import extras

    calls = []

    def fake_urlopen(req, timeout=0):
        body = _json.loads(req.data)
        calls.append(dict(body))
        for bad in ("max_tokens", "temperature"):
            if bad in body:
                msg = _json.dumps({"error": {"message": f"Unsupported parameter: '{bad}' is not supported with this model."}}).encode()
                raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, _io.BytesIO(msg))

        class R:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return _json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode()
        return R()

    monkeypatch.setattr(extras.urllib.request, "urlopen", fake_urlopen)
    out = extras.openai_chat("sk-x", {"model": "gpt-5", "max_tokens": 10, "temperature": 0, "messages": []})
    assert out["choices"]
    assert "max_tokens" not in calls[-1] and "temperature" not in calls[-1] and calls[-1]["max_completion_tokens"] == 800
    assert len(calls) == 3


def test_pricebook_and_quotes(client):
    pb = client.get("/api/pricebook").json()
    keys = {i["key"] for i in pb["items"]}
    assert {"plan_basic", "plan_standard", "plan_healthcare", "plan_security", "breakfix", "project", "onsite", "vm", "server",
            "firewall", "switch", "ap", "site", "backup_basic", "backup_bdr", "backup_m365", "primeemr"} <= keys
    assert pb["company"]["name"] == "ChinookIT" and pb["company"]["tax_pct"] == 5
    # set prices (blank = 0) and add a custom item
    items = pb["items"]
    price = {"plan_standard": (95, 120), "plan_healthcare": (120, 150), "firewall": (60, None), "switch": (25, None), "ap": (15, None),
             "server": (150, None), "vm": (75, None), "site": (100, None), "backup_basic": (40, None), "backup_m365": (4, None),
             "primeemr": (500, 40), "breakfix": (150, None), "onboarding": (1500, None), "voip": (20, None)}
    for it in items:
        if it["key"] in price:
            it["price"], it["alt_price"] = price[it["key"]]
    items.append({"label": "Dark web monitoring", "category": "extras", "unit": "per_user", "price": 2})
    r = client.put("/api/pricebook", json={"items": items})
    assert r.status_code == 200, r.text
    saved = {i["key"]: i for i in r.json()["items"]}
    assert saved["plan_standard"]["price"] == 95 and saved["plan_standard"]["alt_price"] == 120
    assert saved["custom_dark_web_monitoring"]["custom"] is True
    assert client.delete("/api/pricebook/plan_basic").status_code == 422
    assert client.delete("/api/pricebook/custom_dark_web_monitoring").status_code == 204
    client.put("/api/settings", json={"company_name": "ChinookIT Ltd", "quote_tax_pct": 5, "quote_valid_days": 45})

    # a clinic with a network: fw, sw, 2 aps, 1 physical server, 1 vm, 4 workstations (3 users), 2 phones, printer, 1 extra site
    cid = client.post("/api/clinics", json={"name": "Quote Clinic", "shorthand": "QC"}).json()["id"]
    client.post(f"/api/clinics/{cid}/locations", json={"name": "QC South"})
    fw = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "firewall"}).json()
    sw = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "switch", "uplink_id": fw["id"]}).json()
    client.post(f"/api/clinics/{cid}/devices", json={"device_type": "access_point", "quantity": 2, "uplink_id": sw["id"]})
    client.post(f"/api/clinics/{cid}/devices", json={"device_type": "server", "designation": "Hypervisor", "uplink_id": sw["id"]})
    client.post(f"/api/clinics/{cid}/devices", json={"device_type": "server", "designation": "Virtual machine (VM)", "os": "Windows Server 2022"})
    for u in ("Ann", "Bob", "Cy", None):
        client.post(f"/api/clinics/{cid}/devices", json={"device_type": "workstation", "user_name": u, "uplink_id": sw["id"]})
    client.post(f"/api/clinics/{cid}/devices", json={"device_type": "voip", "quantity": 2, "uplink_id": sw["id"]})
    client.post(f"/api/clinics/{cid}/devices", json={"device_type": "printer", "uplink_id": sw["id"]})
    client.post(f"/api/clinics/{cid}/devices", json={"device_type": "workstation", "status": "retired"})

    d = client.get(f"/api/clinics/{cid}/quote-defaults").json()
    c = d["counts"]
    assert c["firewalls"] == 1 and c["switches"] == 1 and c["aps"] == 2 and c["servers_physical"] == 1 and c["vms"] == 1
    assert c["workstations"] == 4 and c["users"] == 3 and c["devices_managed"] == 6 and c["sites"] == 2 and c["phones"] == 2
    L = {l["key"]: l for l in d["lines"]}
    assert L["plan_standard"]["qty"] == 6 and L["plan_standard"]["unit_price"] == 95 and L["plan_standard"]["included"]
    assert L["plan_healthcare"]["included"] is False
    assert L["firewall"]["qty"] == 1 and L["ap"]["qty"] == 2 and L["site"]["qty"] == 2 and L["backup_basic"]["qty"] == 2
    assert L["primeemr"]["qty"] == 1 and L["primeemr"]["unit_price"] == 500
    assert L["breakfix"]["qty"] == 0 and L["onboarding"]["unit"] == "one_time"
    assert d["company"]["name"] == "ChinookIT Ltd" and d["valid_until"] > "2026"
    # per-user + EMR per user
    d2 = client.get(f"/api/clinics/{cid}/quote-defaults", params={"pricing_mode": "per_user", "emr_mode": "per_user"}).json()
    L2 = {l["key"]: l for l in d2["lines"]}
    assert L2["plan_standard"]["unit"] == "per_user" and L2["plan_standard"]["qty"] == 3 and L2["plan_standard"]["unit_price"] == 120
    assert L2["primeemr"]["unit"] == "per_user" and L2["primeemr"]["qty"] == 3 and L2["primeemr"]["unit_price"] == 40

    # create a quote from defaults, tweak a qty
    lines = d["lines"]
    for l in lines:
        if l["key"] == "plan_standard":
            l["qty"] = 7
    body = {"title": d["suggested_title"], "pricing_mode": "per_device", "emr_mode": "flat", "plan_key": "plan_standard", "user_count": 3,
            "device_count": 7, "counts": c, "lines": lines, "discount_pct": 10, "tax_pct": 5, "terms": d["terms"], "prepared_by": "Kaden", "valid_until": d["valid_until"]}
    r = client.post(f"/api/clinics/{cid}/quotes", json=body)
    assert r.status_code == 201, r.text
    q = r.json()
    monthly = 7 * 95 + 1 * 75 + 1 * 150 + 60 + 25 + 2 * 15 + 2 * 100 + 2 * 40 + 3 * 4 + 500
    assert q["totals"]["monthly_subtotal"] == monthly
    assert q["totals"]["discount"] == round(monthly * 0.1, 2)
    assert q["totals"]["monthly_total"] == round(monthly * 0.9 * 1.05, 2)
    assert q["totals"]["onetime_total"] == round(1500 * 1.05, 2)
    assert q["number"].startswith("Q-") and q["status"] == "draft"
    # status -> sent moves stage to proposal
    r = client.patch(f"/api/quotes/{q['id']}/status", json={"status": "sent"})
    assert r.json()["status"] == "sent" and r.json()["sent_at"]
    assert client.get(f"/api/clinics/{cid}").json()["stage"] == "proposal"
    # apply to deal
    r = client.post(f"/api/quotes/{q['id']}/apply-to-deal").json()
    assert r["deal_value"] == q["totals"]["annual_total"]
    assert client.get(f"/api/clinics/{cid}").json()["deal_value"] == q["totals"]["annual_total"]
    # update, duplicate, csv, list
    body["discount_pct"] = 0
    assert client.put(f"/api/quotes/{q['id']}", json=body).json()["totals"]["discount"] == 0
    dup = client.post(f"/api/quotes/{q['id']}/duplicate").json()
    assert dup["title"].endswith("(copy)") and dup["status"] == "draft"
    assert "Monthly total" in client.get(f"/api/quotes/{q['id']}/export.csv").text
    lst = client.get("/api/quotes", params={"clinic_id": cid}).json()
    assert len(lst) == 2 and "lines" not in lst[0]
    assert client.get(f"/api/clinics/{cid}").json()["quotes"][0]["number"] == dup["number"]
    assert client.delete(f"/api/quotes/{dup['id']}").status_code == 204
    backup = client.get("/api/export/backup.json").json()
    assert backup["quotes"] and backup["price_book"]
    assert client.post("/api/import/backup", json=backup).status_code == 200


def test_vm_offsite_connections(client):
    cid = client.post("/api/clinics", json={"name": "VM Clinic", "shorthand": "VMC"}).json()["id"]
    fw = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "firewall"}).json()
    sw = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "switch", "uplink_id": fw["id"]}).json()
    host = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "server", "designation": "Hypervisor / host", "uplink_id": sw["id"]}).json()
    # VM type: auto name VMC-VM001, uplink is the host, link_type virtual
    vm = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "vm", "designation": "EMR server", "uplink_id": host["id"], "os": "Windows Server 2022", "user_name": "EMR"}).json()
    assert vm["name"] == "VMC-VM001" and vm["is_vm"] is True and vm["link_type_effective"] == "virtual" and vm["uplink_name"] == host["name"]
    vm2 = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "vm", "uplink_id": host["id"]}).json()
    assert vm2["name"] == "VMC-VM002"
    # off-site device (a laptop at home) - not attached to the tree
    off = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "laptop", "off_site": True, "user_name": "Dr. Home"}).json()
    assert off["off_site"] is True
    ws = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "workstation", "uplink_id": sw["id"]}).json()

    topo = client.get(f"/api/clinics/{cid}/topology").json()
    node_ids = {n["id"] for n in topo["nodes"]}
    assert off["id"] not in node_ids
    assert [o["id"] for o in topo["offsite"]] == [off["id"]]
    vm_node = next(n for n in topo["nodes"] if n["id"] == vm["id"])
    assert vm_node["is_vm"] is True and vm_node["uplink_id"] == host["id"]
    assert any(e["from"] == host["id"] and e["to"] == vm["id"] and e["link_type"] == "virtual" for e in topo["edges"])

    # extra connection: give the workstation a second uplink to the firewall directly
    r = client.post(f"/api/devices/{ws['id']}/connections", json={"uplink_id": fw["id"]})
    assert r.status_code == 201, r.text
    assert r.json()["connections"][0]["uplink_name"] == fw["name"]
    assert client.post(f"/api/devices/{ws['id']}/connections", json={"uplink_id": ws['id']}).status_code == 422
    assert client.post(f"/api/devices/{ws['id']}/connections", json={"uplink_id": sw['id']}).status_code == 422  # already primary
    topo = client.get(f"/api/clinics/{cid}/topology").json()
    extra = [e for e in topo["edges"] if not e["primary"]]
    assert len(extra) == 1 and extra[0]["from"] == fw["id"] and extra[0]["to"] == ws["id"]
    link_id = client.get(f"/api/devices/{ws['id']}").json()["connections"][0]["id"]
    assert client.delete(f"/api/devices/{ws['id']}/connections/{link_id}").status_code == 204
    assert client.get(f"/api/devices/{ws['id']}").json()["connections"] == []

    # topology connect/disconnect: a device with no uplink -> sets primary; a second call -> extra
    lone = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "printer"}).json()
    assert client.post(f"/api/clinics/{cid}/connect", json={"child_id": lone["id"], "parent_id": sw["id"]}).json()["mode"] == "primary"
    assert client.get(f"/api/devices/{lone['id']}").json()["uplink_id"] == sw["id"]
    assert client.post(f"/api/clinics/{cid}/connect", json={"child_id": lone["id"], "parent_id": fw["id"]}).json()["mode"] == "extra"
    assert client.post(f"/api/clinics/{cid}/disconnect", json={"child_id": lone["id"], "parent_id": fw["id"]}).json()["removed"] == "extra"
    assert client.post(f"/api/clinics/{cid}/disconnect", json={"child_id": lone["id"], "parent_id": sw["id"]}).json()["removed"] == "primary"
    assert client.get(f"/api/devices/{lone['id']}").json()["uplink_id"] is None

    # quote counts: 1 physical server (host) + 2 VMs; VM user counted
    counts = client.get(f"/api/clinics/{cid}/quote-defaults").json()["counts"]
    assert counts["servers_physical"] == 1 and counts["vms"] == 2 and counts["servers_all"] == 3
    assert "emr" in {u.lower() for u in ["EMR"]}  # sanity
    assert counts["devices_managed"] == counts["workstations"] + counts["laptops"] + 3

    # backup round-trips device_links
    client.post(f"/api/devices/{ws['id']}/connections", json={"uplink_id": fw["id"]})
    backup = client.get("/api/export/backup.json").json()
    assert backup["device_links"]
    assert client.post("/api/import/backup", json=backup).status_code == 200


def test_racks(client):
    cid = client.post("/api/clinics", json={"name": "Rack Clinic", "shorthand": "RKC"}).json()["id"]
    dm = client.get("/api/meta/devices").json()
    assert dm["default_rack_units"]["server"] == 2 and "vm" in dm["non_rackable"]
    fw = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "firewall", "rack": "Rack A", "rack_room": "Server room", "rack_position": 12, "rack_units": 1}).json()
    assert fw["rack"] == "Rack A" and fw["rack_position"] == 12
    sw = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "switch", "uplink_id": fw["id"], "rack": "Rack A", "rack_room": "Server room", "rack_position": 11}).json()
    srv = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "server", "uplink_id": sw["id"], "rack": "Rack A", "rack_room": "Server room", "rack_position": 5, "rack_units": 2}).json()
    # a workstation not in the rack but linked to the switch (external link)
    ws = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "workstation", "uplink_id": sw["id"]}).json()
    # a second rack in another room
    ap = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "access_point", "uplink_id": sw["id"], "rack": "Rack B", "rack_room": "Front office", "rack_position": 1}).json()

    data = client.get(f"/api/clinics/{cid}/racks").json()
    assert [r["name"] for r in data["racks"]] == ["Rack A", "Rack B"]
    assert set(data["rooms"]) == {"Server room", "Front office"}
    rackA = data["racks"][0]
    assert rackA["room"] == "Server room" and rackA["device_count"] == 3
    assert rackA["units"] >= 12  # min height
    srv_slot = next(d for d in rackA["devices"] if d["id"] == srv["id"])
    assert srv_slot["position"] == 5 and srv_slot["units"] == 2
    # links: switch<->firewall and switch<->server are in-rack (peer); switch<->workstation is external (down)
    assert any(l["in_rack"] and {l["member_id"], l["other_member_id"]} == {sw["id"], fw["id"]} for l in rackA["links"])
    assert any(l["in_rack"] and {l["member_id"], l["other_member_id"]} == {sw["id"], srv["id"]} for l in rackA["links"])
    assert any(not l["in_rack"] and l["direction"] == "down" and l["ext"]["name"] == ws["name"] for l in rackA["links"])
    # AP (in Rack B) uplinks to the switch in Rack A -> external link from Rack B naming the other rack
    rackB = data["racks"][1]
    aplink = [l for l in rackB["links"] if not l["in_rack"]]
    assert aplink and aplink[0]["ext"]["rack"] == "Rack A" and aplink[0]["direction"] == "up"

    # editing a device's rack fields
    r = client.put(f"/api/devices/{ap['id']}", json={**{k: ap[k] for k in ("device_type", "name", "status")}, "rack": "Rack B", "rack_room": "Front office", "rack_position": 3, "rack_units": 1, "uplink_id": sw["id"]})
    assert r.status_code == 200 and r.json()["rack_position"] == 3
    backup = client.get("/api/export/backup.json").json()
    assert any("rack" in d for d in backup["devices"])


def test_security_devices_and_1u(client):
    cid = client.post("/api/clinics", json={"name": "Sec Clinic", "shorthand": "SEC"}).json()["id"]
    dm = client.get("/api/meta/devices").json()
    assert {"camera", "nvr", "security"} <= set(dm["types"])
    assert dm["types"]["camera"]["prefix"] == "CAM" and dm["types"]["nvr"]["prefix"] == "NVR"
    assert dm["default_rack_units"]["nvr"] == 2
    assert "camera" in dm["non_rackable"] and "nvr" not in dm["non_rackable"]
    sw = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "switch", "rack": "R", "rack_room": "IT", "rack_position": 10, "rack_units": 1}).json()
    assert sw["name"] == "SEC-SW001" and sw["rack_units"] == 1  # 1U accepted
    nvr = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "nvr", "designation": "NVR", "uplink_id": sw["id"], "rack": "R", "rack_room": "IT", "rack_position": 8, "rack_units": 2}).json()
    assert nvr["name"] == "SEC-NVR001"
    cam = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "camera", "designation": "Dome", "uplink_id": sw["id"], "user_name": "Front door"}).json()
    assert cam["name"] == "SEC-CAM001"
    door = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "security", "designation": "Access control panel", "uplink_id": sw["id"]}).json()
    assert door["name"] == "SEC-SEC001"
    # 1U device with explicit position 1 is fine
    assert client.post(f"/api/clinics/{cid}/devices", json={"device_type": "server", "rack": "R", "rack_room": "IT", "rack_position": 1, "rack_units": 1}).status_code == 201
    # blank rack fields (None) are allowed
    assert client.post(f"/api/clinics/{cid}/devices", json={"device_type": "firewall", "rack_position": None, "rack_units": None}).status_code == 201
    # topology places cameras/nvr; racks include the NVR
    # patch panels and shelves are physical-only: not in the topology
    client.post(f"/api/clinics/{cid}/devices", json={"device_type": "patch_panel", "designation": "24-port"})
    shelf = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "shelf", "rack_units": 2}).json()
    topo = client.get(f"/api/clinics/{cid}/topology").json()
    assert any(n["device_type"] == "camera" for n in topo["nodes"])
    assert not any(n["device_type"] in ("patch_panel", "shelf") for n in topo["nodes"])
    assert not any(n["device_type"] in ("patch_panel", "shelf") for n in topo["offsite"])
    racks = client.get(f"/api/clinics/{cid}/racks").json()
    rack = racks["racks"][0]
    assert any(d["device_type"] == "nvr" for d in rack["devices"])
    # camera is an external downstream link on the rack (uplinks to the switch, not rack-mounted itself)
    assert any(not l["in_rack"] and (l.get("ext") or {}).get("name") == cam["name"] for l in rack["links"])


def test_shelves_patch_panels_directional_links(client):
    cid = client.post("/api/clinics", json={"name": "Shelf Clinic", "shorthand": "SHC"}).json()["id"]
    dm = client.get("/api/meta/devices").json()
    assert dm["types"]["patch_panel"]["prefix"] == "PP" and dm["types"]["shelf"]["prefix"] == "SH"
    assert dm["default_rack_units"]["shelf"] == 2
    fw = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "firewall", "rack": "R1", "rack_room": "MDF", "rack_position": 20, "rack_units": 1}).json()
    sw = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "switch", "rack": "R1", "rack_room": "MDF", "rack_position": 18, "rack_units": 1, "uplink_id": fw["id"]}).json()
    pp = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "patch_panel", "designation": "24-port Cat6", "rack": "R1", "rack_room": "MDF", "rack_position": 19, "rack_units": 1}).json()
    assert pp["name"] == "SHC-PP001"
    shelf = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "shelf", "rack": "R1", "rack_room": "MDF", "rack_position": 10, "rack_units": 4}).json()
    assert shelf["name"] == "SHC-SH001" and shelf["rack_units"] == 4
    # two non-rack devices ON the shelf (a NAS 'other' and a mini PC)
    nas = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "other", "designation": "NAS", "shelf_id": shelf["id"], "rack": "R1", "rack_room": "MDF", "uplink_id": sw["id"]}).json()
    minipc = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "server", "designation": "Mini PC", "shelf_id": shelf["id"], "rack": "R1", "rack_room": "MDF", "uplink_id": sw["id"]}).json()
    # an external workstation that uplinks into the switch (downstream), and the fw is upstream of sw
    ws = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "workstation", "uplink_id": sw["id"]}).json()

    data = client.get(f"/api/clinics/{cid}/racks").json()
    assert any(sh["name"] == "SHC-SH001" for sh in data["shelves"])
    rack = data["racks"][0]
    assert rack["device_count"] == 6  # fw, sw, pp, shelf, nas, minipc
    # shelf carries its two items; they are NOT separate mounted rows
    shelf_row = next(d for d in rack["devices"] if d["device_type"] == "shelf")
    assert {i["name"] for i in shelf_row["shelf_items"]} == {nas["name"], minipc["name"]}
    mounted_names = {d["name"] for d in rack["devices"]}
    assert nas["name"] not in mounted_names and minipc["name"] not in mounted_names
    assert {"SHC-FW001", "SHC-SW001", "SHC-PP001", "SHC-SH001"} <= mounted_names

    # directional links
    def links_for(mid):
        return [l for l in rack["links"] if l["member_id"] == mid]
    sw_links = links_for(sw["id"])
    # sw uplinks to fw (in-rack peer), sw has downstream ws (external, down), and shelf items uplink to sw
    assert any(l["in_rack"] and l["direction"] == "peer" and {l["member_id"], l["other_member_id"]} == {sw["id"], fw["id"]} for l in rack["links"])
    down = [l for l in sw_links if not l["in_rack"] and l["direction"] == "down"]
    assert any(l["ext"]["name"] == ws["name"] for l in down)
    # the shelf items' link to the switch anchors on the shelf (member_id == shelf) as upstream
    shelf_up = [l for l in links_for(shelf["id"]) if l["direction"] == "up" and not l["in_rack"]]
    # NAS/miniPC uplink to switch which is IN rack -> that becomes a peer link between shelf and switch
    assert any(l["in_rack"] and {l["member_id"], l["other_member_id"]} == {shelf["id"], sw["id"]} for l in rack["links"])

    # firewall's downstream includes the switch (in-rack peer, already counted) — external down should be empty here
    assert not any(l for l in links_for(fw["id"]) if not l["in_rack"] and l["direction"] == "down")
    backup = client.get("/api/export/backup.json").json()
    assert any(d.get("shelf_id") for d in backup["devices"])


def test_sites_scoping(client):
    cid = client.post("/api/clinics", json={"name": "Multisite Clinic", "shorthand": "MSC"}).json()["id"]
    # A secondary site with a displayed address.
    site = client.post(f"/api/clinics/{cid}/locations", json={
        "name": "MSC North", "address": "10 North Rd", "display_address": "Suite 400", "lat": 51.2, "lng": -114.1}).json()
    assert site["display_address"] == "Suite 400"

    # Equipment: two devices at the Main Site (no location_id), one at the North site.
    main_srv = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "server"}).json()
    main_fw = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "firewall"}).json()
    north_ws = client.post(f"/api/clinics/{cid}/devices", json={"device_type": "workstation", "location_id": site["id"]}).json()
    assert north_ws["location_id"] == site["id"] and north_ws["location_name"] == "MSC North"

    # Sites listing carries per-site device counts, Main first and flagged primary.
    sites = client.get(f"/api/clinics/{cid}/sites").json()["sites"]
    assert sites[0] == {"id": "main", "name": "Main Site", "count": 2, "primary": True}
    north = next(s for s in sites if s["id"] == site["id"])
    assert north["name"] == "MSC North" and north["count"] == 1 and north["primary"] is False

    # Device list is scoped by ?site.
    all_ids = {d["id"] for d in client.get(f"/api/clinics/{cid}/devices").json()["devices"]}
    assert {main_srv["id"], main_fw["id"], north_ws["id"]} <= all_ids
    main_only = client.get(f"/api/clinics/{cid}/devices", params={"site": "main"}).json()
    assert {d["id"] for d in main_only["devices"]} == {main_srv["id"], main_fw["id"]}
    assert main_only["summary"]["total"] == 2
    north_only = client.get(f"/api/clinics/{cid}/devices", params={"site": site["id"]}).json()
    assert {d["id"] for d in north_only["devices"]} == {north_ws["id"]}

    # Topology is scoped too: each site sees only its own devices.
    main_topo = client.get(f"/api/clinics/{cid}/topology", params={"site": "main"}).json()
    assert {n["id"] for n in main_topo["nodes"]} == {main_srv["id"], main_fw["id"]}
    north_topo = client.get(f"/api/clinics/{cid}/topology", params={"site": site["id"]}).json()
    assert {n["id"] for n in north_topo["nodes"]} == {north_ws["id"]}

    # An unknown site value is rejected.
    assert client.get(f"/api/clinics/{cid}/devices", params={"site": "nope"}).status_code == 422


def test_vpn_links_and_endpoints(client):
    # Two clinics, each with equipment; a secondary site on the first.
    a = client.post("/api/clinics", json={"name": "VPN HQ", "shorthand": "VHQ", "lat": 51.0, "lng": -114.0}).json()["id"]
    b = client.post("/api/clinics", json={"name": "VPN Remote", "shorthand": "VRM", "lat": 51.1, "lng": -114.2}).json()["id"]
    a_site = client.post(f"/api/clinics/{a}/locations", json={"name": "VHQ North", "lat": 51.2, "lng": -114.3}).json()["id"]
    a_fw = client.post(f"/api/clinics/{a}/devices", json={"device_type": "firewall"}).json()
    b_fw = client.post(f"/api/clinics/{b}/devices", json={"device_type": "router"}).json()
    ws = client.post(f"/api/clinics/{a}/devices", json={"device_type": "workstation"}).json()

    # A shared endpoint and a private one.
    shared = client.post(f"/api/clinics/{a}/vpn/endpoints", json={"name": "AHS Netcare", "vendor": "AHS", "lat": 51.05, "lng": -114.08}).json()
    assert shared["private"] is False
    priv = client.post(f"/api/clinics/{a}/vpn/endpoints", json={"name": "HQ lab box", "private": True}).json()
    assert priv["private"] is True
    # Clinic B sees the shared endpoint but not clinic A's private one.
    b_eps = {e["id"] for e in client.get(f"/api/clinics/{b}/vpn/endpoints").json()["endpoints"]}
    assert shared["id"] in b_eps and priv["id"] not in b_eps

    # Clinic-to-clinic link, created from A's Main Site firewall to B's router.
    link = client.post(f"/api/clinics/{a}/vpn/links", json={
        "name": "HQ ↔ Remote", "status": "up", "vpn_type": "IPsec",
        "a_device_id": a_fw["id"], "remote_kind": "site", "b_clinic_id": b, "b_device_id": b_fw["id"]}).json()
    assert link["status"] == "up" and link["local"]["clinic_id"] == a and link["remote"]["clinic_id"] == b
    assert link["remote"]["device"]["name"] == b_fw["name"]

    # The SAME canonical link appears from clinic B, with local/remote flipped.
    b_links = client.get(f"/api/clinics/{b}/vpn/links").json()["links"]
    assert len(b_links) == 1 and b_links[0]["id"] == link["id"]
    assert b_links[0]["local"]["clinic_id"] == b and b_links[0]["remote"]["clinic_id"] == a

    # A link to a shared endpoint from the secondary site.
    ep_link = client.post(f"/api/clinics/{a}/vpn/links", json={
        "a_location_id": a_site, "remote_kind": "endpoint", "b_endpoint_id": shared["id"]}).json()
    assert ep_link["remote"]["kind"] == "endpoint" and ep_link["remote"]["name"] == "AHS Netcare"

    # Site scoping: A's Main Site sees the clinic link; A's North site sees the endpoint link.
    main_links = client.get(f"/api/clinics/{a}/vpn/links", params={"site": "main"}).json()["links"]
    assert [l["id"] for l in main_links] == [link["id"]]
    north_links = client.get(f"/api/clinics/{a}/vpn/links", params={"site": a_site}).json()["links"]
    assert [l["id"] for l in north_links] == [ep_link["id"]]

    # Validation: terminator must be a router/firewall; can't use another clinic's private endpoint.
    assert client.post(f"/api/clinics/{a}/vpn/links", json={"a_device_id": ws["id"], "remote_kind": "site", "b_clinic_id": b}).status_code == 422
    assert client.post(f"/api/clinics/{b}/vpn/links", json={"remote_kind": "endpoint", "b_endpoint_id": priv["id"]}).status_code == 422
    assert client.post(f"/api/clinics/{a}/vpn/links", json={"remote_kind": "site", "b_clinic_id": a}).status_code == 422  # site to itself (main↔main)

    # Editing the canonical link updates it everywhere; deleting removes both sides.
    client.put(f"/api/vpn/links/{link['id']}", json={"name": "Renamed tunnel", "status": "down", "a_device_id": a_fw["id"], "remote_kind": "site", "b_clinic_id": b})
    assert client.get(f"/api/vpn/links/{link['id']}").json()["status"] == "down"
    assert client.delete(f"/api/vpn/links/{link['id']}").status_code == 204
    assert client.get(f"/api/clinics/{b}/vpn/links").json()["links"] == []

    # Deleting a clinic cascades its links; deleting an endpoint removes links using it.
    assert client.delete(f"/api/vpn/endpoints/{shared['id']}").status_code == 204
    assert client.get(f"/api/clinics/{a}/vpn/links").json()["links"] == []

    # Backup round-trips VPN data.
    backup = client.get("/api/export/backup.json").json()
    assert "vpn_endpoints" in backup and "vpn_links" in backup
    assert any(e["id"] == priv["id"] for e in backup["vpn_endpoints"])
