"""Canonical VPN links between clinic sites, plus a reusable directory of external endpoints.

A VPN link is ONE two-sided record. Side A is always a clinic site (the side the link was
created from); side B is either another clinic site or a custom/external endpoint. Because a
single record backs both sides, creating a clinic-to-clinic link from one clinic makes it
appear on the other clinic too, and editing or deleting it updates both views at once.
"""
from __future__ import annotations

import ipaddress
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from ..database import db_dependency, row_to_dict, rows_to_list
from ..logic import DEVICE_TYPES, log_event, now_iso
from ..schemas import NetworkRangeIn, TransitSetIn, VpnEndpointIn, VpnLinkIn

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


# ---- Onward access (transit routes) + connectivity resolver ---------------------

def _same_site(c1, l1, c2, l2) -> bool:
    return c1 == c2 and (l1 or None) == (l2 or None)


def _link_site(l: dict, side: str) -> tuple:
    return (l["a_clinic_id"], l["a_location_id"]) if side == "a" else (l["b_clinic_id"], l["b_location_id"])


def _site_dict(conn: sqlite3.Connection, clinic_id: int, loc: int | None) -> dict:
    s = _site_info(conn, clinic_id, loc)
    return {"clinic_id": clinic_id, "location_id": loc, "site_id": s["site_id"], "site_name": s["site_name"],
            "clinic_name": s["clinic_name"], "lat": s["lat"], "lng": s["lng"]}


def _loc_clause(col: str, loc: int | None) -> tuple[str, list]:
    return (f"{col} IS NULL", []) if loc is None else (f"{col} = ?", [loc])


def _resolve_site_loc(conn: sqlite3.Connection, clinic_id: int, site: str | None) -> int | None:
    """Map a ?site value ('main'/None/'all' -> Main Site, or a location id) to a location_id."""
    if not site or site in ("all", "main"):
        return None
    try:
        loc = int(site)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Unknown site")
    if not conn.execute("SELECT 1 FROM clinic_locations WHERE id = ? AND clinic_id = ?", (loc, clinic_id)).fetchone():
        raise HTTPException(status_code=422, detail="Site does not belong to that clinic")
    return loc


@router.get("/vpn/links/{link_id}/transit")
def transit_options(link_id: int, origin: str = Query("a", alias="from"), conn: sqlite3.Connection = Depends(db_dependency)):
    """The sites reachable *through* the far endpoint of this link — i.e. sites with a direct
    VPN link to the intermediate site — and which are already selected as onward destinations."""
    link = _link_or_404(conn, link_id)
    if link["b_kind"] != "site":
        raise HTTPException(status_code=422, detail="Onward access applies only to site-to-site VPN links")
    if origin not in ("a", "b"):
        raise HTTPException(status_code=422, detail="from must be 'a' or 'b'")
    src_c, src_l = _link_site(link, origin)
    via_c, via_l = _link_site(link, "b" if origin == "a" else "a")
    sc, sp = _loc_clause("source_location_id", src_l)
    existing = rows_to_list(conn.execute(
        f"SELECT * FROM vpn_transit_routes WHERE source_clinic_id = ? AND {sc} AND entry_vpn_link_id = ?", [src_c, *sp, link_id]))
    selected = {(r["dest_clinic_id"], r["dest_location_id"] or None, r["exit_vpn_link_id"]) for r in existing}
    rationale_of = {(r["dest_clinic_id"], r["dest_location_id"] or None, r["exit_vpn_link_id"]): r["rationale"] for r in existing}
    options = []
    for l in rows_to_list(conn.execute("SELECT * FROM vpn_links WHERE b_kind = 'site' AND id <> ?", (link_id,))):
        if _same_site(l["a_clinic_id"], l["a_location_id"], via_c, via_l):
            dest = _link_site(l, "b")
        elif _same_site(l["b_clinic_id"], l["b_location_id"], via_c, via_l):
            dest = _link_site(l, "a")
        else:
            continue
        if _same_site(dest[0], dest[1], src_c, src_l):
            continue
        d = _site_dict(conn, dest[0], dest[1])
        d["exit_vpn_link_id"] = l["id"]
        d["exit_vpn_name"] = l["name"]
        d["exit_status"] = l["status"]
        rkey = (dest[0], dest[1] or None, l["id"])
        d["selected"] = rkey in selected
        d["rationale"] = rationale_of.get(rkey)
        options.append(d)
    return {"source": _site_dict(conn, src_c, src_l), "via": _site_dict(conn, via_c, via_l), "options": options}


@router.put("/vpn/links/{link_id}/transit")
def set_transit(link_id: int, payload: TransitSetIn, conn: sqlite3.Connection = Depends(db_dependency)):
    """Replace the onward-access destinations for one direction of this link."""
    link = _link_or_404(conn, link_id)
    if link["b_kind"] != "site":
        raise HTTPException(status_code=422, detail="Onward access applies only to site-to-site VPN links")
    src_c, src_l = _link_site(link, payload.origin)
    via_c, via_l = _link_site(link, "b" if payload.origin == "a" else "a")
    chosen: dict[tuple, str | None] = {}
    for d in payload.destinations:
        ex = _link_or_404(conn, d.exit_vpn_link_id)
        if ex["b_kind"] != "site":
            raise HTTPException(status_code=422, detail="An onward link must be site-to-site")
        ends = [(ex["a_clinic_id"], ex["a_location_id"]), (ex["b_clinic_id"], ex["b_location_id"])]
        if not any(_same_site(c, l, via_c, via_l) for c, l in ends):
            raise HTTPException(status_code=422, detail="That onward link is not connected to the intermediate site")
        if not any(_same_site(c, l, d.clinic_id, d.location_id) for c, l in ends):
            raise HTTPException(status_code=422, detail="That onward link is not connected to the chosen destination")
        if _same_site(d.clinic_id, d.location_id, src_c, src_l):
            raise HTTPException(status_code=422, detail="A route cannot loop back to the source site")
        chosen[(d.clinic_id, d.location_id or None, d.exit_vpn_link_id)] = d.rationale
    sc, sp = _loc_clause("source_location_id", src_l)
    existing = rows_to_list(conn.execute(
        f"SELECT * FROM vpn_transit_routes WHERE source_clinic_id = ? AND {sc} AND entry_vpn_link_id = ?", [src_c, *sp, link_id]))
    for r in existing:  # keep an existing rationale when the caller didn't send a new one
        key = (r["dest_clinic_id"], r["dest_location_id"] or None, r["exit_vpn_link_id"])
        if key in chosen and chosen[key] is None:
            chosen[key] = r["rationale"]
    conn.execute(f"DELETE FROM vpn_transit_routes WHERE source_clinic_id = ? AND {sc} AND entry_vpn_link_id = ?", [src_c, *sp, link_id])
    for (dc, dl, ex), rationale in chosen.items():
        conn.execute(
            """INSERT INTO vpn_transit_routes
               (source_clinic_id, source_location_id, entry_vpn_link_id, via_clinic_id, via_location_id,
                exit_vpn_link_id, dest_clinic_id, dest_location_id, rationale)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (src_c, src_l, link_id, via_c, via_l, ex, dc, dl, rationale))
    return {"count": len(chosen)}


def _sid(loc: int | None) -> str:
    return "main" if loc is None else str(loc)


@router.get("/clinics/{clinic_id}/connectivity")
def connectivity(clinic_id: int, site: str | None = None, conn: sqlite3.Connection = Depends(db_dependency)):
    """Resolve which other sites the selected site can reach: directly-linked sites/endpoints,
    plus destinations explicitly configured as reachable through one intermediate site. Disabled
    tunnels are excluded from the calculation; documented status is surfaced, never live state."""
    _clinic_or_404(conn, clinic_id)
    src_l = _resolve_site_loc(conn, clinic_id, site)
    source = _site_dict(conn, clinic_id, src_l)
    source["ranges"] = _ranges_for_site(conn, clinic_id, src_l)
    all_links = rows_to_list(conn.execute("SELECT * FROM vpn_links"))
    active = [l for l in all_links if l["status"] != "disabled"]
    active_ids = {l["id"] for l in active}

    direct, seen = [], set()
    for l in active:
        if _same_site(l["a_clinic_id"], l["a_location_id"], clinic_id, src_l):
            opp = _side(conn, l, "b")
        elif l["b_kind"] == "site" and _same_site(l["b_clinic_id"], l["b_location_id"], clinic_id, src_l):
            opp = _side(conn, l, "a")
        else:
            continue
        key = f"e{opp['endpoint_id']}" if opp["kind"] == "endpoint" else f"c{opp['clinic_id']}:{opp['site_id']}"
        if key in seen:
            continue
        seen.add(key)
        entry = {"relationship": "direct", "vpn_link_id": l["id"], "vpn_name": l["name"],
                 "status": l["status"], "status_label": VPN_STATUSES.get(l["status"], l["status"]), **opp}
        if opp["kind"] == "site":
            entry["ranges"] = _ranges_for_site(conn, opp["clinic_id"], None if opp["site_id"] == "main" else int(opp["site_id"]))
        direct.append(entry)

    remote = []
    sc, sp = _loc_clause("source_location_id", src_l)
    for r in rows_to_list(conn.execute(
            f"SELECT * FROM vpn_transit_routes WHERE source_clinic_id = ? AND {sc}", [clinic_id, *sp])):
        if r["entry_vpn_link_id"] not in active_ids or r["exit_vpn_link_id"] not in active_ids:
            continue  # a hop is disabled -> not a calculated route
        dkey = f"c{r['dest_clinic_id']}:{_sid(r['dest_location_id'])}"
        if dkey in seen:
            continue  # already directly reachable
        dest = _site_dict(conn, r["dest_clinic_id"], r["dest_location_id"])
        via = _site_dict(conn, r["via_clinic_id"], r["via_location_id"])
        remote.append({**dest, "kind": "site", "relationship": "via", "via": via, "transit_id": r["id"],
                       "rationale": r["rationale"],
                       "ranges": _ranges_for_site(conn, r["dest_clinic_id"], r["dest_location_id"]),
                       "path": [{"vpn_link_id": r["entry_vpn_link_id"], "from": source, "to": via},
                                {"vpn_link_id": r["exit_vpn_link_id"], "from": via, "to": dest}]})
    return {"source_site": source, "direct": direct, "remote": remote}


# ---- Optional IP network ranges (advanced) --------------------------------------

RANGE_COLUMNS = ["name", "cidr", "network_type", "notes"]
NETWORK_TYPES = {"lan": "LAN", "server": "Server", "voip": "VoIP", "guest": "Guest", "management": "Management", "other": "Other"}


def _ranges_for_site(conn: sqlite3.Connection, clinic_id: int, loc: int | None) -> list[dict]:
    lc, lp = _loc_clause("location_id", loc)
    return rows_to_list(conn.execute(
        f"SELECT * FROM site_network_ranges WHERE clinic_id = ? AND {lc} ORDER BY name COLLATE NOCASE", [clinic_id, *lp]))


def _directly_linked_sites(conn: sqlite3.Connection, clinic_id: int, loc: int | None) -> list[tuple[int, int | None]]:
    out = []
    for l in rows_to_list(conn.execute("SELECT * FROM vpn_links WHERE b_kind = 'site'")):
        if _same_site(l["a_clinic_id"], l["a_location_id"], clinic_id, loc):
            out.append((l["b_clinic_id"], l["b_location_id"]))
        elif _same_site(l["b_clinic_id"], l["b_location_id"], clinic_id, loc):
            out.append((l["a_clinic_id"], l["a_location_id"]))
    return out


def _overlaps_for(conn: sqlite3.Connection, ranges: list[dict], clinic_id: int, loc: int | None) -> dict[int, list]:
    """For each range at this site, any overlapping range at a directly VPN-linked site."""
    peers = _directly_linked_sites(conn, clinic_id, loc)
    peer_ranges = []
    for pc, pl in peers:
        for r in _ranges_for_site(conn, pc, pl):
            info = _site_info(conn, pc, pl)
            peer_ranges.append((r, info))
    result: dict[int, list] = {}
    for r in ranges:
        try:
            net = ipaddress.ip_network(r["cidr"], strict=False)
        except ValueError:
            continue
        hits = []
        for pr, info in peer_ranges:
            try:
                if net.overlaps(ipaddress.ip_network(pr["cidr"], strict=False)):
                    hits.append({"range_id": pr["id"], "cidr": pr["cidr"], "name": pr["name"],
                                 "clinic_name": info["clinic_name"], "site_name": info["site_name"]})
            except ValueError:
                continue
        if hits:
            result[r["id"]] = hits
    return result


@router.get("/clinics/{clinic_id}/network-ranges")
def list_ranges(clinic_id: int, site: str | None = None, conn: sqlite3.Connection = Depends(db_dependency)):
    _clinic_or_404(conn, clinic_id)
    loc = _resolve_site_loc(conn, clinic_id, site)
    ranges = _ranges_for_site(conn, clinic_id, loc)
    overlaps = _overlaps_for(conn, ranges, clinic_id, loc)
    for r in ranges:
        r["type_label"] = NETWORK_TYPES.get(r["network_type"], r["network_type"])
        r["overlaps"] = overlaps.get(r["id"], [])
    return {"ranges": ranges, "network_types": NETWORK_TYPES, "site": _site_dict(conn, clinic_id, loc)}


@router.post("/clinics/{clinic_id}/network-ranges", status_code=201)
def create_range(clinic_id: int, payload: NetworkRangeIn, site: str | None = None, conn: sqlite3.Connection = Depends(db_dependency)):
    _clinic_or_404(conn, clinic_id)
    loc = _resolve_site_loc(conn, clinic_id, site)
    data = payload.model_dump()
    cols = ", ".join(["clinic_id", "location_id", *RANGE_COLUMNS])
    marks = ", ".join("?" * (len(RANGE_COLUMNS) + 2))
    cur = conn.execute(f"INSERT INTO site_network_ranges ({cols}) VALUES ({marks})",
                       [clinic_id, loc] + [data[c] for c in RANGE_COLUMNS])
    return row_to_dict(conn.execute("SELECT * FROM site_network_ranges WHERE id = ?", (cur.lastrowid,)).fetchone())


@router.put("/network-ranges/{range_id}")
def update_range(range_id: int, payload: NetworkRangeIn, conn: sqlite3.Connection = Depends(db_dependency)):
    if not conn.execute("SELECT 1 FROM site_network_ranges WHERE id = ?", (range_id,)).fetchone():
        raise HTTPException(status_code=404, detail="Network range not found")
    data = payload.model_dump()
    sets = ", ".join(f"{c} = ?" for c in RANGE_COLUMNS)
    conn.execute(f"UPDATE site_network_ranges SET {sets}, updated_at = ? WHERE id = ?",
                 [data[c] for c in RANGE_COLUMNS] + [now_iso(), range_id])
    return row_to_dict(conn.execute("SELECT * FROM site_network_ranges WHERE id = ?", (range_id,)).fetchone())


@router.delete("/network-ranges/{range_id}", status_code=204)
def delete_range(range_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    cur = conn.execute("DELETE FROM site_network_ranges WHERE id = ?", (range_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Network range not found")
    return None
