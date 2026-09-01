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
    assert marker_color("do_not_contact", None, now) == "red"
    assert marker_color("current_client", None, now) == "yellow"
    assert marker_color("interested", None, now) == "green"
    assert marker_color("prospect", None, now) == "white"
    assert marker_color("prospect", (now - timedelta(days=10)).isoformat(), now) == "blue"
    assert marker_color("prospect", (now - timedelta(days=100)).isoformat(), now) == "grey"


def test_clinic_contact_appointment_flow(client):
    r = client.post("/api/clinics", json={"name": "Test Clinic", "address": "123 Main St", "lat": 51.0, "lng": -114.0})
    assert r.status_code == 201, r.text
    clinic = r.json()
    assert clinic["color"] == "white"
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
    assert detail["color"] == "blue"
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
    assert r.status_code == 200 and r.json()["color"] == "yellow"

    r = client.patch(f"/api/clinics/{cid}/location", json={"lat": 51.1, "lng": -114.1})
    assert r.json()["lat"] == 51.1

    assert client.get("/api/clinics", params={"q": "test"}).json()[0]["id"] == cid
    assert client.get("/api/clinics", params={"color": "yellow"}).json()
    assert client.get("/api/clinics", params={"color": "red"}).json() == []

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
    r = client.post("/api/clinics", json={"name": "Pipeline Clinic", "lat": 51.05, "lng": -114.05, "deal_value": 12000, "stage": "contacted"})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["stage"] == "contacted" and c["effective_probability"] == 20 and c["weighted_value"] == 2400
    cid = c["id"]

    # move through the pipeline via the Kanban endpoint
    r = client.patch(f"/api/clinics/{cid}/stage", json={"stage": "proposal"})
    assert r.status_code == 200 and r.json()["stage"] == "proposal"
    r = client.patch(f"/api/clinics/{cid}/stage", json={"stage": "won", "outcome_reason": "service", "outcome_notes": "Loved the response time"})
    won = r.json()
    assert won["stage"] == "won" and won["relationship"] == "current_client" and won["color"] == "yellow"
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
    assert client.get("/api/tasks", params={"done": "false"}).json() == []
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
    assert locs[0]["clinic_name"] == "SDI North" and locs[0]["color"] == "white"
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
    today = datetime.now().date().isoformat()
    t_time = (datetime.now() + timedelta(minutes=45)).strftime("%H:%M")
    client.post("/api/tasks", json={"clinic_id": cid, "title": "Timed task", "due_date": today, "due_time": t_time, "reminder_minutes": 30})
    rem = client.get("/api/reminders").json()
    kinds = {(i["kind"], i["title"]) for i in rem["items"]}
    assert ("appointment", "Reminder test") in kinds and ("task", "Timed task") in kinds
    assert rem["options"] == [15, 30, 45, 60]

    # analytics
    a = client.get("/api/analytics").json()
    assert len(a["visits_by_week"]) == 12 and len(a["visits_by_month"]) == 12
    assert a["conversion"]["won"] >= 1 and "rate" in a["conversion"]
    assert any(r["rep"] == "Kaden" for r in a["by_rep"])
    assert [t["stage"] for t in a["time_in_stage"]] == ["prospect", "contacted", "demo", "proposal"]

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
        {"name": "Imported Clinic A", "address": "10 Import St NE", "relationship": "interested", "stage": "contacted"},
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
