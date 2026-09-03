"""Equipment inventory: devices per clinic with uplink/downlink topology, services, users and tickets."""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ..database import db_dependency, row_to_dict, rows_to_list
from ..logic import (
    DEFAULT_RACK_UNITS, DEVICE_DESIGNATIONS, DEVICE_STATUSES, DEVICE_TYPES, LINK_TYPES_NET, NON_RACKABLE_TYPES,
    NON_TOPOLOGY_TYPES, OS_DEVICE_TYPES, USER_DEVICE_TYPES, clinic_shorthand, log_event, now_iso,
)
from ..schemas import ConnectionIn, DeviceIn, EdgeOp, ServiceIn, TicketIn

router = APIRouter(prefix="/api", tags=["devices"])

DEVICE_COLUMNS = [
    "location_id", "device_type", "name", "number", "designation", "manufacturer", "model", "serial", "ip_address",
    "mac_address", "os", "user_name", "uplink_id", "link_type", "status", "off_site", "rack", "rack_room",
    "rack_position", "rack_units", "shelf_id", "services", "purchase_date", "warranty_until", "notes",
]

DEVICE_SERVICE_COLUMNS = [
    "name", "description", "ip_addresses", "ports", "internal_url", "public_url", "support_url", "support_email", "notes",
]

SELECT = """SELECT d.*, u.name AS uplink_name, u.device_type AS uplink_type, l.name AS location_name,
                   (SELECT COUNT(*) FROM devices x WHERE x.uplink_id = d.id) AS downlink_count,
                   (SELECT COUNT(*) FROM device_tickets t WHERE t.device_id = d.id) AS ticket_count
            FROM devices d LEFT JOIN devices u ON u.id = d.uplink_id
            LEFT JOIN clinic_locations l ON l.id = d.location_id"""


def _clinic_or_404(conn: sqlite3.Connection, clinic_id: int) -> dict:
    row = row_to_dict(conn.execute("SELECT * FROM clinics WHERE id = ?", (clinic_id,)).fetchone())
    if row is None:
        raise HTTPException(status_code=404, detail="Clinic not found")
    return row


def _decorate(row: dict) -> dict:
    t = DEVICE_TYPES.get(row["device_type"], DEVICE_TYPES["other"])
    row["type_label"] = t["label"]
    row["icon"] = t["icon"]
    row["is_network"] = t["network"]
    row["is_vm"] = bool(t.get("vm"))
    row["off_site"] = bool(row.get("off_site"))
    row["status_label"] = DEVICE_STATUSES.get(row["status"], row["status"])
    if row.get("device_type") == "vm" and row.get("uplink_id"):
        row["link_type_effective"] = "virtual"
        row["link_label"] = "Virtual (on host)"
    else:
        row["link_type_effective"] = row.get("link_type")
        row["link_label"] = LINK_TYPES_NET.get(row.get("link_type") or "", None)
    try:
        row["services"] = json.loads(row["services"]) if row.get("services") else []
    except (TypeError, ValueError):
        row["services"] = []
    row["uplink_icon"] = DEVICE_TYPES.get(row.get("uplink_type") or "", {}).get("icon")
    return row


def _get_or_404(conn: sqlite3.Connection, device_id: int) -> dict:
    row = row_to_dict(conn.execute(f"{SELECT} WHERE d.id = ?", (device_id,)).fetchone())
    if row is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return _decorate(row)


def _load_services(conn: sqlite3.Connection, device_id: int) -> list[dict]:
    return rows_to_list(conn.execute(
        "SELECT * FROM device_services WHERE device_id = ? ORDER BY name COLLATE NOCASE", (device_id,)))


def _services_by_device(conn: sqlite3.Connection, device_ids: list[int]) -> dict[int, list[dict]]:
    """Compact {device_id: [{id, name}]} for list/topology rendering."""
    out: dict[int, list[dict]] = {}
    if not device_ids:
        return out
    marks = ",".join("?" * len(device_ids))
    for r in conn.execute(
            f"SELECT id, device_id, name FROM device_services WHERE device_id IN ({marks}) ORDER BY name COLLATE NOCASE",
            list(device_ids)):
        out.setdefault(r["device_id"], []).append({"id": r["id"], "name": r["name"]})
    return out


def next_number(conn: sqlite3.Connection, clinic_id: int, device_type: str) -> int:
    row = conn.execute("SELECT MAX(number) FROM devices WHERE clinic_id = ? AND device_type = ?", (clinic_id, device_type)).fetchone()
    return (row[0] or 0) + 1


def template_name(clinic: dict, device_type: str, number: int) -> str:
    prefix = DEVICE_TYPES.get(device_type, DEVICE_TYPES["other"])["prefix"]
    return f"{clinic_shorthand(clinic)}-{prefix}{number:03d}"


def _parse_number(clinic: dict, device_type: str, name: str) -> int | None:
    prefix = DEVICE_TYPES.get(device_type, DEVICE_TYPES["other"])["prefix"]
    m = re.fullmatch(rf"{re.escape(clinic_shorthand(clinic))}-{re.escape(prefix)}(\d+)", name.strip(), re.IGNORECASE)
    return int(m.group(1)) if m else None


def _check_uplink(conn: sqlite3.Connection, clinic_id: int, device_id: int | None, uplink_id: int | None) -> None:
    if uplink_id is None:
        return
    if device_id is not None and uplink_id == device_id:
        raise HTTPException(status_code=422, detail="A device cannot be its own uplink")
    up = conn.execute("SELECT id, clinic_id, uplink_id FROM devices WHERE id = ?", (uplink_id,)).fetchone()
    if up is None or up["clinic_id"] != clinic_id:
        raise HTTPException(status_code=422, detail="Uplink must be a device at the same clinic")
    # Walk up the chain to make sure we are not creating a loop.
    seen = set()
    cur = up
    while cur is not None and cur["uplink_id"] is not None:
        if cur["uplink_id"] == device_id or cur["uplink_id"] in seen:
            raise HTTPException(status_code=422, detail="That uplink would create a loop (the device is already upstream of it)")
        seen.add(cur["id"])
        cur = conn.execute("SELECT id, clinic_id, uplink_id FROM devices WHERE id = ?", (cur["uplink_id"],)).fetchone()


def _validate(conn: sqlite3.Connection, clinic_id: int, data: dict) -> None:
    if data["device_type"] not in DEVICE_TYPES:
        raise HTTPException(status_code=422, detail="Unknown device type")
    if data.get("location_id") is not None:
        ok = conn.execute("SELECT 1 FROM clinic_locations WHERE id = ? AND clinic_id = ?", (data["location_id"], clinic_id)).fetchone()
        if not ok:
            raise HTTPException(status_code=422, detail="Location does not belong to this clinic")
    if data.get("ip_address") and not re.fullmatch(r"[0-9a-fA-F:.]{3,45}(/\d{1,3})?", data["ip_address"]):
        raise HTTPException(status_code=422, detail="IP address doesn't look valid")
    if data["device_type"] == "vm":
        data["link_type"] = None  # the VM->host link is virtual; derived in output, not stored
    elif data.get("uplink_id") is not None and not data.get("link_type"):
        data["link_type"] = "wireless" if data["device_type"] == "wireless" else "ethernet"
    if data.get("uplink_id") is None:
        data["link_type"] = None
    if data.get("off_site"):
        data["off_site"] = 1
    else:
        data["off_site"] = 0


def _site_clause(site: str | None) -> tuple[str, list]:
    """A device is at the 'Main Site' when it has no location_id, or at a secondary site
    matching its location_id. `site` is 'main', a numeric location id, or None/'all' for
    every site. Returns an SQL fragment (prefixed ' AND ...') and its params."""
    if not site or site == "all":
        return "", []
    if site == "main":
        return " AND d.location_id IS NULL", []
    try:
        return " AND d.location_id = ?", [int(site)]
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Unknown site")


def _sites_with_counts(conn: sqlite3.Connection, clinic_id: int) -> list[dict]:
    counts: dict = {}
    for r in conn.execute("SELECT location_id, COUNT(*) AS n FROM devices WHERE clinic_id = ? GROUP BY location_id", (clinic_id,)):
        counts[r["location_id"]] = r["n"]
    sites = [{"id": "main", "name": "Main Site", "count": counts.get(None, 0), "primary": True}]
    for l in rows_to_list(conn.execute(
            "SELECT id, name FROM clinic_locations WHERE clinic_id = ? ORDER BY name COLLATE NOCASE", (clinic_id,))):
        sites.append({"id": l["id"], "name": l["name"], "count": counts.get(l["id"], 0), "primary": False})
    return sites


def _summary(conn: sqlite3.Connection, clinic_id: int, site: str | None = None) -> dict:
    clause, sp = _site_clause(site)
    rows = conn.execute(
        f"SELECT device_type, status, COUNT(*) AS n FROM devices d WHERE clinic_id = ?{clause} GROUP BY device_type, status", [clinic_id, *sp]).fetchall()
    by_type = {t: {"label": v["label"], "icon": v["icon"], "prefix": v["prefix"], "active": 0, "spare": 0, "retired": 0, "total": 0} for t, v in DEVICE_TYPES.items()}
    for r in rows:
        b = by_type[r["device_type"]] if r["device_type"] in by_type else by_type["other"]
        b[r["status"]] += r["n"]
        b["total"] += r["n"]
    return {
        "by_type": {t: v for t, v in by_type.items() if v["total"]},
        "total": sum(v["total"] for v in by_type.values()),
        "active": sum(v["active"] for v in by_type.values()),
        "billable": {
            "workstations": by_type["workstation"]["active"] + by_type["laptop"]["active"],
            "servers": by_type["server"]["active"] + by_type["vm"]["active"],
            "network": sum(by_type[t]["active"] for t in ("firewall", "router", "switch", "access_point")),
            "phones": by_type["voip"]["active"],
            "printers": by_type["printer"]["active"],
        },
    }


# ---- Meta -------------------------------------------------------------------

@router.get("/meta/devices")
def device_meta():
    return {"types": DEVICE_TYPES, "designations": DEVICE_DESIGNATIONS, "statuses": DEVICE_STATUSES,
            "link_types": LINK_TYPES_NET, "user_types": list(USER_DEVICE_TYPES), "os_types": list(OS_DEVICE_TYPES),
            "default_rack_units": DEFAULT_RACK_UNITS, "non_rackable": list(NON_RACKABLE_TYPES)}


# ---- Per clinic ---------------------------------------------------------------

@router.get("/clinics/{clinic_id}/sites")
def list_sites(clinic_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    _clinic_or_404(conn, clinic_id)
    return {"sites": _sites_with_counts(conn, clinic_id)}


@router.get("/clinics/{clinic_id}/devices")
def list_devices(clinic_id: int, q: str | None = None, device_type: str | None = None, status: str | None = None,
                 site: str | None = None, conn: sqlite3.Connection = Depends(db_dependency)):
    clinic = _clinic_or_404(conn, clinic_id)
    site_clause, site_params = _site_clause(site)
    sql = f"{SELECT} WHERE d.clinic_id = ?{site_clause}"
    params: list = [clinic_id, *site_params]
    if q:
        like = f"%{q.strip()}%"
        sql += " AND (d.name LIKE ? OR d.ip_address LIKE ? OR d.user_name LIKE ? OR d.serial LIKE ? OR d.model LIKE ? OR d.designation LIKE ? OR d.notes LIKE ?)"
        params += [like] * 7
    if device_type:
        sql += " AND d.device_type = ?"
        params.append(device_type)
    if status:
        sql += " AND d.status = ?"
        params.append(status)
    sql += " ORDER BY d.device_type, d.number, d.name COLLATE NOCASE"
    devices = [_decorate(r) for r in rows_to_list(conn.execute(sql, params))]
    svc = _services_by_device(conn, [d["id"] for d in devices])
    for d in devices:
        d["services"] = svc.get(d["id"], [])
    return {"devices": devices, "summary": _summary(conn, clinic_id, site), "shorthand": clinic_shorthand(clinic),
            "sites": _sites_with_counts(conn, clinic_id),
            "locations": rows_to_list(conn.execute("SELECT id, name FROM clinic_locations WHERE clinic_id = ? ORDER BY name", (clinic_id,)))}


@router.get("/clinics/{clinic_id}/devices/next-name")
def next_name(clinic_id: int, device_type: str, conn: sqlite3.Connection = Depends(db_dependency)):
    clinic = _clinic_or_404(conn, clinic_id)
    if device_type not in DEVICE_TYPES:
        raise HTTPException(status_code=422, detail="Unknown device type")
    n = next_number(conn, clinic_id, device_type)
    return {"name": template_name(clinic, device_type, n), "number": n, "shorthand": clinic_shorthand(clinic),
            "template": f"{{shorthand}}-{DEVICE_TYPES[device_type]['prefix']}{{number:03}}"}


@router.post("/clinics/{clinic_id}/devices", status_code=201)
def create_device(clinic_id: int, payload: DeviceIn, conn: sqlite3.Connection = Depends(db_dependency)):
    clinic = _clinic_or_404(conn, clinic_id)
    data = payload.model_dump()
    qty = data.pop("quantity", 1)
    svc_names = [str(s).strip() for s in (data.get("services") or []) if str(s).strip()]
    _validate(conn, clinic_id, data)
    _check_uplink(conn, clinic_id, None, data.get("uplink_id"))
    created = []
    for i in range(qty):
        d = dict(data)
        n = next_number(conn, clinic_id, d["device_type"])
        if d.get("name") and qty == 1:
            parsed = _parse_number(clinic, d["device_type"], d["name"])
            d["number"] = parsed if parsed is not None else n
        else:
            d["name"] = template_name(clinic, d["device_type"], n)
            d["number"] = n
        d["services"] = None  # services are structured now (device_services), not text
        cols = ", ".join(["clinic_id", *DEVICE_COLUMNS])
        marks = ", ".join("?" * (len(DEVICE_COLUMNS) + 1))
        cur = conn.execute(f"INSERT INTO devices ({cols}) VALUES ({marks})", [clinic_id] + [d.get(c) for c in DEVICE_COLUMNS])
        for name in svc_names:
            conn.execute("INSERT INTO device_services (device_id, name) VALUES (?, ?)", (cur.lastrowid, name))
        dev = _get_or_404(conn, cur.lastrowid)
        dev["services"] = _load_services(conn, cur.lastrowid)
        created.append(dev)
    label = DEVICE_TYPES[data["device_type"]]["label"]
    log_event(conn, clinic_id, "equipment", f"Added {len(created)} {label.lower()}{'s' if len(created) > 1 else ''}: " + ", ".join(c["name"] for c in created[:5]) + ("…" if len(created) > 5 else ""))
    return created if qty > 1 else created[0]


def ensure_device_by_name(conn: sqlite3.Connection, clinic_id: int, name: str, device_type: str = "workstation") -> int | None:
    """Return the id of the clinic's device with this name, creating a workstation if none matches.

    Used when linking a machine to a ticket by name — an unknown name drops a placeholder into
    the topology that can be corrected later.
    """
    name = (name or "").strip()
    if not name:
        return None
    row = conn.execute(
        "SELECT id FROM devices WHERE clinic_id = ? AND name = ? COLLATE NOCASE", (clinic_id, name)).fetchone()
    if row:
        return row[0]
    clinic = _clinic_or_404(conn, clinic_id)
    n = next_number(conn, clinic_id, device_type)
    parsed = _parse_number(clinic, device_type, name)
    number = parsed if parsed is not None else n
    cur = conn.execute(
        "INSERT INTO devices (clinic_id, device_type, name, number, status) VALUES (?, ?, ?, ?, 'active')",
        (clinic_id, device_type, name, number))
    log_event(conn, clinic_id, "equipment", f"Added workstation {name} (linked from a ticket)")
    return cur.lastrowid


def _edge_link_type(d: dict) -> str:
    if d["device_type"] == "vm":
        return "virtual"
    return d.get("link_type") or "ethernet"


@router.get("/clinics/{clinic_id}/topology")
def topology(clinic_id: int, site: str | None = None, conn: sqlite3.Connection = Depends(db_dependency)):
    """Nodes + edges for the network diagram.

    The primary uplink forms the on-site tree (roots = on-site devices with no uplink).
    Off-site devices are returned separately and never joined to the tree. Extra
    connections (device_links) are returned as overlay edges so a device can show
    more than one uplink.
    """
    _clinic_or_404(conn, clinic_id)
    site_clause, site_params = _site_clause(site)
    all_rows = [_decorate(r) for r in rows_to_list(conn.execute(f"{SELECT} WHERE d.clinic_id = ?{site_clause} ORDER BY d.device_type, d.number", [clinic_id, *site_params]))]
    # Passive rack fixtures (patch panels, shelves) are physical only — keep them out of the network diagram.
    devices = [d for d in all_rows if d["device_type"] not in NON_TOPOLOGY_TYPES]
    by_id = {d["id"]: d for d in devices}
    onsite = [d for d in devices if not d["off_site"]]
    children: dict[int, list[int]] = {d["id"]: [] for d in devices}
    for d in onsite:
        if d["uplink_id"] in by_id and not by_id[d["uplink_id"]]["off_site"]:
            children[d["uplink_id"]].append(d["id"])
    node_keys = ("id", "name", "device_type", "type_label", "icon", "is_network", "is_vm", "off_site", "designation",
                 "ip_address", "user_name", "status", "link_type", "uplink_id", "ticket_count", "location_name", "model")
    svc = _services_by_device(conn, [d["id"] for d in devices if d["device_type"] in ("server", "vm")])
    nodes = [{k: d.get(k) for k in node_keys} | {"children": children[d["id"]], "services": svc.get(d["id"], [])} for d in onsite]
    offsite_nodes = [{k: d.get(k) for k in node_keys} | {"children": [], "services": svc.get(d["id"], [])} for d in devices if d["off_site"]]
    roots = [d["id"] for d in onsite if d["uplink_id"] not in by_id or by_id[d["uplink_id"]]["off_site"]]
    edges = [{"from": d["uplink_id"], "to": d["id"], "link_type": _edge_link_type(d), "primary": True}
             for d in onsite if d["uplink_id"] in by_id and not by_id[d["uplink_id"]]["off_site"]]
    for l in rows_to_list(conn.execute(
        """SELECT dl.* FROM device_links dl JOIN devices d ON d.id = dl.device_id WHERE d.clinic_id = ?""", (clinic_id,))):
        if l["device_id"] in by_id and l["uplink_id"] in by_id:
            edges.append({"from": l["uplink_id"], "to": l["device_id"], "link_type": l["link_type"] or "ethernet", "primary": False, "link_id": l["id"]})
    from .vpn import topology_links
    vpn = topology_links(conn, clinic_id, site)
    return {"nodes": nodes, "roots": roots, "edges": edges, "offsite": offsite_nodes, "vpn": vpn}


# ---- Extra connections (multiple uplinks / edge cases) ---------------------------

@router.post("/devices/{device_id}/connections", status_code=201)
def add_connection(device_id: int, payload: ConnectionIn, conn: sqlite3.Connection = Depends(db_dependency)):
    d = _get_or_404(conn, device_id)
    up = row_to_dict(conn.execute("SELECT id, clinic_id, name FROM devices WHERE id = ?", (payload.uplink_id,)).fetchone())
    if up is None or up["clinic_id"] != d["clinic_id"]:
        raise HTTPException(status_code=422, detail="Uplink must be a device at the same clinic")
    if payload.uplink_id == device_id:
        raise HTTPException(status_code=422, detail="A device cannot connect to itself")
    if d["uplink_id"] == payload.uplink_id:
        raise HTTPException(status_code=422, detail="That is already the primary uplink")
    dup = conn.execute("SELECT 1 FROM device_links WHERE device_id = ? AND uplink_id = ?", (device_id, payload.uplink_id)).fetchone()
    if dup:
        raise HTTPException(status_code=422, detail="These devices are already connected")
    conn.execute("INSERT INTO device_links (device_id, uplink_id, link_type, notes) VALUES (?, ?, ?, ?)",
                 (device_id, payload.uplink_id, payload.link_type, payload.notes))
    return get_device(device_id, conn)


@router.delete("/devices/{device_id}/connections/{link_id}", status_code=204)
def remove_connection(device_id: int, link_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    cur = conn.execute("DELETE FROM device_links WHERE id = ? AND device_id = ?", (link_id, device_id))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Connection not found")
    return None


@router.post("/clinics/{clinic_id}/connect")
def connect_devices(clinic_id: int, payload: EdgeOp, conn: sqlite3.Connection = Depends(db_dependency)):
    """Draw a line child->parent from the topology. Sets the primary uplink if the child
    has none; otherwise records an extra connection. Returns the mode used."""
    _clinic_or_404(conn, clinic_id)
    child = row_to_dict(conn.execute("SELECT * FROM devices WHERE id = ? AND clinic_id = ?", (payload.child_id, clinic_id)).fetchone())
    parent = row_to_dict(conn.execute("SELECT * FROM devices WHERE id = ? AND clinic_id = ?", (payload.parent_id, clinic_id)).fetchone()) if payload.parent_id else None
    if child is None or parent is None:
        raise HTTPException(status_code=422, detail="Both devices must belong to this clinic")
    if payload.child_id == payload.parent_id:
        raise HTTPException(status_code=422, detail="A device cannot connect to itself")
    is_vm = child["device_type"] == "vm"
    link_type = payload.link_type or ("virtual" if is_vm else ("wireless" if child["device_type"] == "wireless" else "ethernet"))
    if child["uplink_id"] is None and not child["off_site"]:
        _check_uplink(conn, clinic_id, payload.child_id, payload.parent_id)
        conn.execute("UPDATE devices SET uplink_id = ?, link_type = ?, updated_at = ? WHERE id = ?",
                     (payload.parent_id, None if is_vm else link_type, now_iso(), payload.child_id))
        return {"mode": "primary"}
    if child["uplink_id"] == payload.parent_id or conn.execute("SELECT 1 FROM device_links WHERE device_id = ? AND uplink_id = ?", (payload.child_id, payload.parent_id)).fetchone():
        raise HTTPException(status_code=422, detail="Those devices are already connected")
    conn.execute("INSERT INTO device_links (device_id, uplink_id, link_type) VALUES (?, ?, ?)", (payload.child_id, payload.parent_id, link_type))
    return {"mode": "extra"}


@router.post("/clinics/{clinic_id}/disconnect")
def disconnect_devices(clinic_id: int, payload: EdgeOp, conn: sqlite3.Connection = Depends(db_dependency)):
    """Break a line between two devices: clears the primary uplink if that is the link,
    otherwise removes the matching extra connection."""
    _clinic_or_404(conn, clinic_id)
    child = row_to_dict(conn.execute("SELECT * FROM devices WHERE id = ? AND clinic_id = ?", (payload.child_id, clinic_id)).fetchone())
    if child is None:
        raise HTTPException(status_code=404, detail="Device not found")
    if child["uplink_id"] == payload.parent_id:
        conn.execute("UPDATE devices SET uplink_id = NULL, link_type = NULL, updated_at = ? WHERE id = ?", (now_iso(), payload.child_id))
        return {"removed": "primary"}
    cur = conn.execute("DELETE FROM device_links WHERE device_id = ? AND uplink_id = ?", (payload.child_id, payload.parent_id))
    if cur.rowcount == 0:
        # also try the reverse direction just in case the caller passed them swapped
        cur = conn.execute("DELETE FROM device_links WHERE device_id = ? AND uplink_id = ?", (payload.parent_id, payload.child_id))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="No such connection")
    return {"removed": "extra"}


@router.get("/clinics/{clinic_id}/devices.csv")
def export_devices(clinic_id: int, site: str | None = None, conn: sqlite3.Connection = Depends(db_dependency)):
    clinic = _clinic_or_404(conn, clinic_id)
    site_clause, site_params = _site_clause(site)
    devices = [_decorate(r) for r in rows_to_list(conn.execute(f"{SELECT} WHERE d.clinic_id = ?{site_clause} ORDER BY d.device_type, d.number", [clinic_id, *site_params]))]
    svc = _services_by_device(conn, [d["id"] for d in devices])
    cols = ["name", "type_label", "designation", "status", "user_name", "ip_address", "mac_address", "os", "manufacturer", "model", "serial",
            "uplink_name", "link_label", "location_name", "purchase_date", "warranty_until", "services", "notes"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for d in devices:
        d = dict(d)
        d["services"] = "; ".join(s["name"] for s in svc.get(d["id"], []))
        w.writerow(d)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", clinic["shorthand"] or clinic["name"])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{safe}-equipment.csv"'})


# ---- Racks (physical elevation) -------------------------------------------------

@router.get("/clinics/{clinic_id}/racks")
def racks(clinic_id: int, site: str | None = None, conn: sqlite3.Connection = Depends(db_dependency)):
    """Group rack devices into racks. Mounted devices carry a U position; a shelf carries
    the loose devices sitting on it (shelf_id). Links are directional (up = the member's
    uplink, down = something that uplinks into the member) so the view can put upstream
    devices on the left and downstream on the right."""
    _clinic_or_404(conn, clinic_id)
    site_clause, site_params = _site_clause(site)
    all_devs = [_decorate(r) for r in rows_to_list(conn.execute(f"{SELECT} WHERE d.clinic_id = ?{site_clause} ORDER BY d.rack, d.rack_position DESC, d.name", [clinic_id, *site_params]))]
    by_id = {d["id"]: d for d in all_devs}

    # directed uplinks: uplinks_of[x] = set of devices x connects UP to
    uplinks_of: dict[int, set[int]] = {d["id"]: set() for d in all_devs}
    link_type_of: dict[tuple[int, int], str] = {}
    for d in all_devs:
        if d["uplink_id"] in by_id:
            uplinks_of[d["id"]].add(d["uplink_id"])
            link_type_of[(d["id"], d["uplink_id"])] = "virtual" if d["device_type"] == "vm" else (d["link_type"] or "ethernet")
    for l in rows_to_list(conn.execute(
        """SELECT dl.device_id, dl.uplink_id, dl.link_type FROM device_links dl JOIN devices d ON d.id = dl.device_id WHERE d.clinic_id = ?""", (clinic_id,))):
        if l["device_id"] in by_id and l["uplink_id"] in by_id:
            uplinks_of[l["device_id"]].add(l["uplink_id"])
            link_type_of.setdefault((l["device_id"], l["uplink_id"]), l["link_type"] or "ethernet")

    # An item on a shelf inherits the shelf's rack for grouping.
    def rack_of(d: dict) -> str | None:
        if d.get("shelf_id") and d["shelf_id"] in by_id:
            return by_id[d["shelf_id"]].get("rack")
        return d.get("rack")

    racks: dict[str, dict] = {}
    for d in all_devs:
        rk = rack_of(d)
        if not rk:
            continue
        r = racks.setdefault(rk, {"name": rk, "room": d.get("rack_room"), "units": 0, "devices": [], "_members": {}})
        if d.get("rack_room") and not r["room"]:
            r["room"] = d["rack_room"]
        r["_members"][d["id"]] = d

    def brief(d: dict) -> dict:
        return {"id": d["id"], "name": d["name"], "device_type": d["device_type"], "type_label": d["type_label"],
                "icon": d["icon"], "designation": d["designation"], "ip_address": d["ip_address"], "status": d["status"],
                "model": d.get("model"), "user_name": d.get("user_name"), "ticket_count": d["ticket_count"]}

    out = []
    for rk, r in sorted(racks.items()):
        members = r.pop("_members")
        member_ids = set(members)
        # shelf items grouped by their shelf
        items_by_shelf: dict[int, list] = {}
        for d in members.values():
            if d.get("shelf_id") in members:
                items_by_shelf.setdefault(d["shelf_id"], []).append(brief(d))
        # mounted devices (have a U position, are not sitting on a shelf)
        mounted = []
        for d in members.values():
            if d.get("shelf_id"):
                continue
            pos = d.get("rack_position")
            height = d.get("rack_units") or DEFAULT_RACK_UNITS.get(d["device_type"], 1) or 1
            row = {**brief(d), "position": pos, "units": height}
            if d["device_type"] == "shelf":
                row["shelf_items"] = sorted(items_by_shelf.get(d["id"], []), key=lambda x: x["name"])
            mounted.append(row)
            top = (pos or 0) + height - 1
            if top > r["units"]:
                r["units"] = top
        mounted.sort(key=lambda x: (x["position"] or 0), reverse=True)
        r["devices"] = mounted
        r["units"] = max(r["units"], 12)
        r["device_count"] = len(members)
        # anchor: which mounted member a link should attach to (shelf item -> its shelf)
        def anchor_member(mid: int) -> int:
            d = members.get(mid)
            if d and d.get("shelf_id") in members:
                return d["shelf_id"]
            return mid

        links = []
        seen_ext = set()
        seen_int = set()
        for mid, d in members.items():
            am = anchor_member(mid)
            # upstream (this member's uplinks)
            for up in uplinks_of.get(mid, set()):
                lt = link_type_of.get((mid, up), "ethernet")
                if up in member_ids:
                    key = tuple(sorted((am, anchor_member(up))))
                    if key[0] != key[1] and key not in seen_int:
                        seen_int.add(key)
                        links.append({"member_id": key[0], "other_member_id": key[1], "in_rack": True, "direction": "peer", "link_type": lt})
                else:
                    o = by_id.get(up)
                    k = (am, up)
                    if k in seen_ext:
                        continue
                    seen_ext.add(k)
                    links.append({"member_id": am, "in_rack": False, "direction": "up", "link_type": lt,
                                  "ext": {"id": up, "name": o["name"] if o else None, "icon": o["icon"] if o else None, "rack": o.get("rack") if o else None}})
            # downstream (things that uplink into this member)
            for other_id, ups in uplinks_of.items():
                if mid in ups and other_id not in member_ids:
                    lt = link_type_of.get((other_id, mid), "ethernet")
                    k = (am, other_id)
                    if k in seen_ext:
                        continue
                    seen_ext.add(k)
                    o = by_id.get(other_id)
                    links.append({"member_id": am, "in_rack": False, "direction": "down", "link_type": lt,
                                  "ext": {"id": other_id, "name": o["name"] if o else None, "icon": o["icon"] if o else None, "rack": o.get("rack") if o else None}})
        r["links"] = links
        out.append(r)

    rooms = sorted({d["rack_room"] for d in all_devs if d.get("rack_room")})
    existing_racks = sorted({d["rack"] for d in all_devs if d.get("rack")})
    shelves = [{"id": d["id"], "name": d["name"], "rack": d.get("rack"), "rack_room": d.get("rack_room")}
               for d in all_devs if d["device_type"] == "shelf"]
    return {"racks": out, "rooms": rooms, "rack_names": existing_racks, "shelves": shelves,
            "unracked_infra": [{"id": d["id"], "name": d["name"], "icon": d["icon"], "device_type": d["device_type"]}
                               for d in all_devs if not rack_of(d) and d["device_type"] not in NON_RACKABLE_TYPES and (d["is_network"] or d["device_type"] in ("server", "nvr", "patch_panel", "shelf"))]}


# ---- Single device --------------------------------------------------------------

@router.get("/devices/{device_id}")
def get_device(device_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    d = _get_or_404(conn, device_id)
    d["services"] = _load_services(conn, device_id)
    d["tickets"] = rows_to_list(conn.execute("SELECT * FROM device_tickets WHERE device_id = ? ORDER BY ticket_date DESC, id DESC", (device_id,)))
    d["downlinks"] = [_decorate(r) for r in rows_to_list(conn.execute(f"{SELECT} WHERE d.uplink_id = ? ORDER BY d.device_type, d.number", (device_id,)))]
    chain = []
    cur = d
    seen = {d["id"]}
    while cur.get("uplink_id"):
        up = row_to_dict(conn.execute("SELECT id, name, device_type, uplink_id, ip_address FROM devices WHERE id = ?", (cur["uplink_id"],)).fetchone())
        if not up or up["id"] in seen:
            break
        up["icon"] = DEVICE_TYPES.get(up["device_type"], DEVICE_TYPES["other"])["icon"]
        chain.append(up)
        seen.add(up["id"])
        cur = up
    d["uplink_chain"] = chain  # nearest first
    d["connections"] = rows_to_list(conn.execute(
        """SELECT dl.id, dl.link_type, dl.notes, u.id AS uplink_id, u.name AS uplink_name, u.device_type AS uplink_type
           FROM device_links dl JOIN devices u ON u.id = dl.uplink_id WHERE dl.device_id = ? ORDER BY dl.id""", (device_id,)))
    for cn in d["connections"]:
        cn["uplink_icon"] = DEVICE_TYPES.get(cn["uplink_type"], DEVICE_TYPES["other"])["icon"]
    d["extra_downlinks"] = rows_to_list(conn.execute(
        """SELECT dl.id, dl.link_type, d2.id AS device_id, d2.name, d2.device_type FROM device_links dl
           JOIN devices d2 ON d2.id = dl.device_id WHERE dl.uplink_id = ? ORDER BY dl.id""", (device_id,)))
    for dn in d["extra_downlinks"]:
        dn["icon"] = DEVICE_TYPES.get(dn["device_type"], DEVICE_TYPES["other"])["icon"]
    return d


@router.put("/devices/{device_id}")
def update_device(device_id: int, payload: DeviceIn, conn: sqlite3.Connection = Depends(db_dependency)):
    before = _get_or_404(conn, device_id)
    clinic = _clinic_or_404(conn, before["clinic_id"])
    data = payload.model_dump()
    data.pop("quantity", None)
    _validate(conn, before["clinic_id"], data)
    _check_uplink(conn, before["clinic_id"], device_id, data.get("uplink_id"))
    if not data.get("name"):
        data["name"] = template_name(clinic, data["device_type"], before["number"] or next_number(conn, before["clinic_id"], data["device_type"]))
    parsed = _parse_number(clinic, data["device_type"], data["name"])
    data["number"] = parsed if parsed is not None else (before["number"] if before["device_type"] == data["device_type"] else next_number(conn, before["clinic_id"], data["device_type"]))
    data["services"] = None  # structured services live in device_services, not the text column
    sets = ", ".join(f"{c} = ?" for c in DEVICE_COLUMNS)
    conn.execute(f"UPDATE devices SET {sets}, updated_at = ? WHERE id = ?", [data.get(c) for c in DEVICE_COLUMNS] + [now_iso(), device_id])
    return get_device(device_id, conn)


@router.delete("/devices/{device_id}", status_code=204)
def delete_device(device_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    d = _get_or_404(conn, device_id)
    conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
    log_event(conn, d["clinic_id"], "equipment", f"Removed {d['type_label'].lower()} {d['name']}")
    return None


@router.post("/devices/{device_id}/tickets", status_code=201)
def add_ticket(device_id: int, payload: TicketIn, conn: sqlite3.Connection = Depends(db_dependency)):
    _get_or_404(conn, device_id)
    cur = conn.execute("INSERT INTO device_tickets (device_id, title, url, ticket_date, notes) VALUES (?, ?, ?, ?, ?)",
                       (device_id, payload.title.strip(), payload.url, payload.ticket_date, payload.notes))
    return row_to_dict(conn.execute("SELECT * FROM device_tickets WHERE id = ?", (cur.lastrowid,)).fetchone())


@router.delete("/devices/{device_id}/tickets/{ticket_id}", status_code=204)
def delete_ticket(device_id: int, ticket_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    cur = conn.execute("DELETE FROM device_tickets WHERE id = ? AND device_id = ?", (ticket_id, device_id))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return None


# ---- Structured running services (on servers and VMs) -----------------------

def _service_row(conn: sqlite3.Connection, service_id: int) -> dict:
    row = row_to_dict(conn.execute(
        """SELECT s.*, d.clinic_id AS clinic_id, d.name AS device_name, d.device_type AS device_type
           FROM device_services s JOIN devices d ON d.id = s.device_id WHERE s.id = ?""", (service_id,)).fetchone())
    if row is None:
        raise HTTPException(status_code=404, detail="Service not found")
    return row


def _service_detail(conn: sqlite3.Connection, service_id: int) -> dict:
    s = _service_row(conn, service_id)
    from .clinics import _enrich_note

    s["note_log"] = [_enrich_note(conn, n) for n in rows_to_list(conn.execute(
        "SELECT * FROM clinic_notes WHERE service_id = ? ORDER BY created_at DESC, id DESC", (service_id,)))]
    atts = rows_to_list(conn.execute(
        "SELECT * FROM attachments WHERE service_id = ? ORDER BY created_at DESC, id DESC", (service_id,)))
    s["photos"] = [a for a in atts if a["kind"] == "photo"]
    s["files"] = [a for a in atts if a["kind"] != "photo"]
    return s


@router.post("/devices/{device_id}/services", status_code=201)
def add_service(device_id: int, payload: ServiceIn, conn: sqlite3.Connection = Depends(db_dependency)):
    d = _get_or_404(conn, device_id)
    if d["device_type"] not in ("server", "vm"):
        raise HTTPException(status_code=422, detail="Services can only run on a server or VM")
    data = payload.model_dump()
    cols = ", ".join(["device_id", *DEVICE_SERVICE_COLUMNS])
    marks = ", ".join("?" * (len(DEVICE_SERVICE_COLUMNS) + 1))
    cur = conn.execute(f"INSERT INTO device_services ({cols}) VALUES ({marks})",
                       [device_id] + [data[c] for c in DEVICE_SERVICE_COLUMNS])
    return _service_detail(conn, cur.lastrowid)


@router.get("/services/{service_id}")
def get_service(service_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    return _service_detail(conn, service_id)


@router.put("/services/{service_id}")
def update_service(service_id: int, payload: ServiceIn, conn: sqlite3.Connection = Depends(db_dependency)):
    _service_row(conn, service_id)
    data = payload.model_dump()
    sets = ", ".join(f"{c} = ?" for c in DEVICE_SERVICE_COLUMNS)
    conn.execute(f"UPDATE device_services SET {sets}, updated_at = ? WHERE id = ?",
                 [data[c] for c in DEVICE_SERVICE_COLUMNS] + [now_iso(), service_id])
    return _service_detail(conn, service_id)


@router.delete("/services/{service_id}", status_code=204)
def delete_service(service_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    if conn.execute("DELETE FROM device_services WHERE id = ?", (service_id,)).rowcount == 0:
        raise HTTPException(status_code=404, detail="Service not found")
    return None
