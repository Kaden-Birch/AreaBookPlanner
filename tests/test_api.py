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
