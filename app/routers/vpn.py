"""Canonical VPN links between clinic sites, plus a reusable directory of external endpoints.

A VPN link is ONE two-sided record. Side A is always a clinic site (the side the link was
created from); side B is either another clinic site or a custom/external endpoint. Because a
single record backs both sides, creating a clinic-to-clinic link from one clinic makes it
appear on the other clinic too, and editing or deleting it updates both views at once.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ..database import db_dependency, row_to_dict, rows_to_list
from ..logic import DEVICE_TYPES, log_event, now_iso
from ..schemas import VpnEndpointIn, VpnLinkIn

router = APIRouter(prefix="/api", tags=["vpn"])

VPN_STATUSES = {"unknown": "Unknown", "up": "Up", "down": "Down", "disabled": "Disabled"}
ENDPOINT_COLUMNS = ["name", "description", "address", "display_address", "lat", "lng", "vendor", "support_info"]
SECRETS_NOTICE = ("Do not store passwords, pre-shared keys, private keys, VPN configuration exports "
                  "containing secrets, or recovery codes here. Store them in the approved password manager.")


def _clinic_or_404(conn: sqlite3.Connection, clinic_id: int) -> dict:
    row = row_to_dict(conn.execute("SELECT * FROM clinics WHERE id = ?", (clinic_id,)).fetchone())
    if row is None:
        raise HTTPException(status_code=404, detail="Clinic not found")
    return row


# ---- Custom endpoints -----------------------------------------------------------

def _endpoint_row(conn: sqlite3.Connection, endpoint_id: int) -> dict:
    row = row_to_dict(conn.execute("SELECT * FROM vpn_endpoints WHERE id = ?", (endpoint_id,)).fetchone())
    if row is None:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    row["private"] = row["private_clinic_id"] is not None
    return row


def _accessible_endpoint(conn: sqlite3.Connection, endpoint_id: int, clinic_id: int) -> dict:
    ep = _endpoint_row(conn, endpoint_id)
    if ep["private_clinic_id"] is not None and ep["private_clinic_id"] != clinic_id:
        raise HTTPException(status_code=422, detail="That endpoint is private to another clinic")
    return ep


@router.get("/clinics/{clinic_id}/vpn/endpoints")
def list_endpoints(clinic_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    """Endpoints available to this clinic: everything shared, plus its own private ones."""
    _clinic_or_404(conn, clinic_id)
    rows = rows_to_list(conn.execute(
        "SELECT * FROM vpn_endpoints WHERE private_clinic_id IS NULL OR private_clinic_id = ? ORDER BY name COLLATE NOCASE",
        (clinic_id,)))
    for r in rows:
        r["private"] = r["private_clinic_id"] is not None
    return {"endpoints": rows, "secrets_notice": SECRETS_NOTICE}


@router.post("/clinics/{clinic_id}/vpn/endpoints", status_code=201)
def create_endpoint(clinic_id: int, payload: VpnEndpointIn, conn: sqlite3.Connection = Depends(db_dependency)):
    _clinic_or_404(conn, clinic_id)
    data = payload.model_dump()
    private_id = clinic_id if data.pop("private", False) else None
    cols = ", ".join([*ENDPOINT_COLUMNS, "private_clinic_id"])
    marks = ", ".join("?" * (len(ENDPOINT_COLUMNS) + 1))
    cur = conn.execute(f"INSERT INTO vpn_endpoints ({cols}) VALUES ({marks})",
                       [data[c] for c in ENDPOINT_COLUMNS] + [private_id])
    return _endpoint_row(conn, cur.lastrowid)


@router.put("/vpn/endpoints/{endpoint_id}")
def update_endpoint(endpoint_id: int, payload: VpnEndpointIn, conn: sqlite3.Connection = Depends(db_dependency)):
    existing = _endpoint_row(conn, endpoint_id)
    data = payload.model_dump()
    # `private` toggles scope: private pins to the current owner (or nothing if it was shared).
    make_private = data.pop("private", False)
    private_id = existing["private_clinic_id"] if make_private else None
    if make_private and private_id is None:
        raise HTTPException(status_code=422, detail="A shared endpoint has no owning clinic to make it private to")
    sets = ", ".join(f"{c} = ?" for c in ENDPOINT_COLUMNS)
    conn.execute(f"UPDATE vpn_endpoints SET {sets}, private_clinic_id = ?, updated_at = ? WHERE id = ?",
                 [data[c] for c in ENDPOINT_COLUMNS] + [private_id, now_iso(), endpoint_id])
    return _endpoint_row(conn, endpoint_id)


@router.delete("/vpn/endpoints/{endpoint_id}", status_code=204)
def delete_endpoint(endpoint_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    cur = conn.execute("DELETE FROM vpn_endpoints WHERE id = ?", (endpoint_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    return None


# ---- VPN links ------------------------------------------------------------------

def _site_info(conn: sqlite3.Connection, clinic_id: int, location_id: int | None) -> dict:
    c = conn.execute("SELECT name, lat, lng FROM clinics WHERE id = ?", (clinic_id,)).fetchone()
    cname = c["name"] if c else "(deleted clinic)"
    if location_id:
        loc = conn.execute("SELECT name, lat, lng, display_address, address FROM clinic_locations WHERE id = ?", (location_id,)).fetchone()
        if loc:
            return {"kind": "site", "clinic_id": clinic_id, "clinic_name": cname, "site_id": location_id,
                    "site_name": loc["name"], "lat": loc["lat"], "lng": loc["lng"]}
    return {"kind": "site", "clinic_id": clinic_id, "clinic_name": cname, "site_id": "main",
            "site_name": "Main Site", "lat": c["lat"] if c else None, "lng": c["lng"] if c else None}


def _dev_brief(conn: sqlite3.Connection, device_id: int | None) -> dict | None:
    if not device_id:
        return None
    r = conn.execute("SELECT id, name, device_type FROM devices WHERE id = ?", (device_id,)).fetchone()
    if not r:
        return None
    return {"id": r["id"], "name": r["name"], "device_type": r["device_type"],
            "icon": DEVICE_TYPES.get(r["device_type"], DEVICE_TYPES["other"])["icon"]}


def _endpoint_side(conn: sqlite3.Connection, endpoint_id: int | None) -> dict:
    if endpoint_id:
        ep = conn.execute("SELECT * FROM vpn_endpoints WHERE id = ?", (endpoint_id,)).fetchone()
        if ep:
            return {"kind": "endpoint", "endpoint_id": ep["id"], "name": ep["name"], "vendor": ep["vendor"],
                    "lat": ep["lat"], "lng": ep["lng"], "address": ep["display_address"] or ep["address"],
                    "private": ep["private_clinic_id"] is not None}
    return {"kind": "endpoint", "endpoint_id": endpoint_id, "name": "(deleted endpoint)", "lat": None, "lng": None}


def _side(conn: sqlite3.Connection, link: dict, which: str) -> dict:
    """Resolve side 'a' or 'b' of a link into a display object (site or endpoint)."""
    if which == "a":
        s = _site_info(conn, link["a_clinic_id"], link["a_location_id"])
        s["device"] = _dev_brief(conn, link["a_device_id"])
        return s
    if link["b_kind"] == "site":
        s = _site_info(conn, link["b_clinic_id"], link["b_location_id"])
        s["device"] = _dev_brief(conn, link["b_device_id"])
        return s
    return _endpoint_side(conn, link["b_endpoint_id"])


def _normalize(conn: sqlite3.Connection, link: dict, local_side: str) -> dict:
    remote_side = "b" if local_side == "a" else "a"
    return {
        "id": link["id"], "name": link["name"], "vpn_type": link["vpn_type"],
        "status": link["status"], "status_label": VPN_STATUSES.get(link["status"], link["status"]),
        "notes": link["notes"], "created_at": link["created_at"], "updated_at": link["updated_at"],
        "local": _side(conn, link, local_side), "remote": _side(conn, link, remote_side),
        "raw": {k: link[k] for k in ("a_clinic_id", "a_location_id", "a_device_id", "b_kind",
                                     "b_clinic_id", "b_location_id", "b_device_id", "b_endpoint_id")},
    }


def _link_or_404(conn: sqlite3.Connection, link_id: int) -> dict:
    row = row_to_dict(conn.execute("SELECT * FROM vpn_links WHERE id = ?", (link_id,)).fetchone())
    if row is None:
        raise HTTPException(status_code=404, detail="VPN link not found")
    return row


def _clinic_sides(link: dict, clinic_id: int) -> list[tuple[str, int | None]]:
    """The sides ('a'/'b' with their location id) that belong to `clinic_id`."""
    sides = []
    if link["a_clinic_id"] == clinic_id:
        sides.append(("a", link["a_location_id"]))
    if link["b_kind"] == "site" and link["b_clinic_id"] == clinic_id:
        sides.append(("b", link["b_location_id"]))
    return sides


def _site_matches(location_id: int | None, site: str | None) -> bool:
    if not site or site == "all":
        return True
    if site == "main":
        return location_id is None
    try:
        return location_id == int(site)
    except (TypeError, ValueError):
        return False


@router.get("/clinics/{clinic_id}/vpn/links")
def list_links(clinic_id: int, site: str | None = None, conn: sqlite3.Connection = Depends(db_dependency)):
    """Every canonical VPN link touching this clinic, normalized to a local/remote view.
    Optionally scoped to one of the clinic's sites (main | <location id>)."""
    _clinic_or_404(conn, clinic_id)
    rows = rows_to_list(conn.execute(
        "SELECT * FROM vpn_links WHERE a_clinic_id = ? OR (b_kind = 'site' AND b_clinic_id = ?) ORDER BY id",
        (clinic_id, clinic_id)))
    out = []
    for l in rows:
        sides = _clinic_sides(l, clinic_id)
        # Prefer the side that matches the requested site so the local perspective is correct.
        chosen = next((s for s in sides if _site_matches(s[1], site)), None)
        if chosen is None:
            continue
        out.append(_normalize(conn, l, chosen[0]))
    return {"links": out, "statuses": VPN_STATUSES, "secrets_notice": SECRETS_NOTICE}


def topology_links(conn: sqlite3.Connection, clinic_id: int, site: str | None = None) -> list[dict]:
    """VPN links that terminate at this clinic (optionally one site), shaped for the topology
    diagram: the local terminating device id, and the remote end to draw a node for."""
    rows = rows_to_list(conn.execute(
        "SELECT * FROM vpn_links WHERE a_clinic_id = ? OR (b_kind = 'site' AND b_clinic_id = ?) ORDER BY id",
        (clinic_id, clinic_id)))
    out = []
    for l in rows:
        chosen = next((s for s in _clinic_sides(l, clinic_id) if _site_matches(s[1], site)), None)
        if chosen is None:
            continue
        local_side = chosen[0]
        remote = _side(conn, l, "b" if local_side == "a" else "a")
        out.append({
            "vpn_id": l["id"], "device_id": l["a_device_id"] if local_side == "a" else l["b_device_id"],
            "name": l["name"], "status": l["status"], "status_label": VPN_STATUSES.get(l["status"], l["status"]),
            "remote": remote,
        })
    return out


@router.get("/vpn/map")
def vpn_map(conn: sqlite3.Connection = Depends(db_dependency)):
    """All canonical VPN links whose BOTH ends have map coordinates, for the map overlay.
    An external endpoint only appears if it was given a map position."""
    out = []
    for l in rows_to_list(conn.execute("SELECT * FROM vpn_links ORDER BY id")):
        a, b = _side(conn, l, "a"), _side(conn, l, "b")
        if a.get("lat") is None or a.get("lng") is None or b.get("lat") is None or b.get("lng") is None:
            continue
        out.append({"id": l["id"], "name": l["name"], "vpn_type": l["vpn_type"], "status": l["status"],
                    "status_label": VPN_STATUSES.get(l["status"], l["status"]), "a": a, "b": b})
    return {"links": out}


@router.get("/vpn/links/{link_id}")
def get_link(link_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    link = _link_or_404(conn, link_id)
    return _normalize(conn, link, "a")


def _validate_site(conn: sqlite3.Connection, clinic_id: int, location_id: int | None, label: str) -> None:
    if location_id is not None and not conn.execute(
            "SELECT 1 FROM clinic_locations WHERE id = ? AND clinic_id = ?", (location_id, clinic_id)).fetchone():
        raise HTTPException(status_code=422, detail=f"{label} site does not belong to that clinic")


def _validate_terminator(conn: sqlite3.Connection, clinic_id: int, device_id: int | None, label: str) -> None:
    if device_id is None:
        return
    d = conn.execute("SELECT clinic_id, device_type FROM devices WHERE id = ?", (device_id,)).fetchone()
    if d is None or d["clinic_id"] != clinic_id:
        raise HTTPException(status_code=422, detail=f"{label} device does not belong to that clinic")
    if d["device_type"] not in ("router", "firewall"):
        raise HTTPException(status_code=422, detail="A VPN link must terminate on a router or firewall")


def _build_link_data(conn: sqlite3.Connection, a_clinic_id: int, payload: VpnLinkIn) -> dict:
    p = payload.model_dump()
    _validate_site(conn, a_clinic_id, p["a_location_id"], "Local")
    _validate_terminator(conn, a_clinic_id, p["a_device_id"], "Local")
    data = {"name": p["name"], "vpn_type": p["vpn_type"], "status": p["status"], "notes": p["notes"],
            "a_clinic_id": a_clinic_id, "a_location_id": p["a_location_id"], "a_device_id": p["a_device_id"],
            "b_kind": p["remote_kind"], "b_clinic_id": None, "b_location_id": None,
            "b_device_id": None, "b_endpoint_id": None}
    if p["remote_kind"] == "site":
        if not p["b_clinic_id"]:
            raise HTTPException(status_code=422, detail="Choose a remote clinic")
        _clinic_or_404(conn, p["b_clinic_id"])
        _validate_site(conn, p["b_clinic_id"], p["b_location_id"], "Remote")
        _validate_terminator(conn, p["b_clinic_id"], p["b_device_id"], "Remote")
        if p["b_clinic_id"] == a_clinic_id and p["b_location_id"] == p["a_location_id"]:
            raise HTTPException(status_code=422, detail="A site cannot VPN to itself")
        data["b_clinic_id"] = p["b_clinic_id"]
        data["b_location_id"] = p["b_location_id"]
        data["b_device_id"] = p["b_device_id"]
    else:
        if not p["b_endpoint_id"]:
            raise HTTPException(status_code=422, detail="Choose a remote endpoint")
        _accessible_endpoint(conn, p["b_endpoint_id"], a_clinic_id)
        data["b_endpoint_id"] = p["b_endpoint_id"]
    return data


@router.post("/clinics/{clinic_id}/vpn/links", status_code=201)
def create_link(clinic_id: int, payload: VpnLinkIn, conn: sqlite3.Connection = Depends(db_dependency)):
    _clinic_or_404(conn, clinic_id)
    data = _build_link_data(conn, clinic_id, payload)
    cols = ", ".join(data.keys())
    marks = ", ".join("?" * len(data))
    cur = conn.execute(f"INSERT INTO vpn_links ({cols}) VALUES ({marks})", list(data.values()))
    link = _link_or_404(conn, cur.lastrowid)
    name = data["name"] or "VPN link"
    log_event(conn, clinic_id, "equipment", f"VPN link added: {name}")
    if data["b_kind"] == "site" and data["b_clinic_id"] != clinic_id:
        log_event(conn, data["b_clinic_id"], "equipment", f"VPN link added: {name}")
    return _normalize(conn, link, "a")


@router.put("/vpn/links/{link_id}")
def update_link(link_id: int, payload: VpnLinkIn, conn: sqlite3.Connection = Depends(db_dependency)):
    existing = _link_or_404(conn, link_id)
    data = _build_link_data(conn, existing["a_clinic_id"], payload)
    sets = ", ".join(f"{k} = ?" for k in data)
    conn.execute(f"UPDATE vpn_links SET {sets}, updated_at = ? WHERE id = ?", [*data.values(), now_iso(), link_id])
    return _normalize(conn, _link_or_404(conn, link_id), "a")


@router.delete("/vpn/links/{link_id}", status_code=204)
def delete_link(link_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    cur = conn.execute("DELETE FROM vpn_links WHERE id = ?", (link_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="VPN link not found")
    return None
