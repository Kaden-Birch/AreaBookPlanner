"""Price book (Settings) and quotes generated from a clinic's equipment topology."""
from __future__ import annotations

import csv
import io
import json
import sqlite3
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ..database import db_dependency, row_to_dict, rows_to_list
from ..logic import (
    DEFAULT_INCLUDED, DEFAULT_QUOTE_TERMS, QTY_SOURCES, QUOTE_CATEGORIES, UNIT_LABELS, log_event, now_iso,
)
from ..schemas import PriceBookIn, PriceItemIn, QuoteIn, QuoteStatusIn

router = APIRouter(prefix="/api", tags=["quotes"])

STATUS_LABELS = {"draft": "Draft", "sent": "Sent", "accepted": "Accepted", "declined": "Declined", "expired": "Expired"}


# ---- Price book ----------------------------------------------------------------

def _pb_rows(conn: sqlite3.Connection, include_inactive: bool = True) -> list[dict]:
    rows = rows_to_list(conn.execute("SELECT * FROM price_book ORDER BY sort_order, label COLLATE NOCASE"))
    out = []
    for r in rows:
        r["active"] = bool(r["active"])
        r["custom"] = bool(r["custom"])
        r["unit_label"] = UNIT_LABELS.get(r["unit"], r["unit"])
        r["alt_unit_label"] = UNIT_LABELS.get(r["alt_unit"], r["alt_unit"]) if r.get("alt_unit") else None
        r["category_label"] = QUOTE_CATEGORIES.get(r["category"], r["category"])
        if include_inactive or r["active"]:
            out.append(r)
    return out


@router.get("/pricebook")
def get_pricebook(conn: sqlite3.Connection = Depends(db_dependency)):
    from .extras import get_setting

    return {
        "items": _pb_rows(conn),
        "categories": QUOTE_CATEGORIES,
        "units": UNIT_LABELS,
        "company": {
            "name": get_setting(conn, "company_name") or "ChinookIT",
            "contact": get_setting(conn, "company_contact") or "",
            "terms": get_setting(conn, "quote_terms") or DEFAULT_QUOTE_TERMS,
            "tax_pct": float(get_setting(conn, "quote_tax_pct") or 5),
            "valid_days": int(get_setting(conn, "quote_valid_days") or 30),
        },
    }


@router.put("/pricebook")
def save_pricebook(payload: PriceBookIn, conn: sqlite3.Connection = Depends(db_dependency)):
    """Bulk-save prices/labels/active flags. Unknown keys are added as custom items."""
    existing = {r["key"] for r in rows_to_list(conn.execute("SELECT key FROM price_book"))}
    max_sort = conn.execute("SELECT COALESCE(MAX(sort_order), 0) FROM price_book").fetchone()[0]
    for it in payload.items:
        if it.unit not in UNIT_LABELS or (it.alt_unit and it.alt_unit not in UNIT_LABELS):
            raise HTTPException(status_code=422, detail=f"Unknown unit on '{it.label}'")
        if it.category not in QUOTE_CATEGORIES:
            raise HTTPException(status_code=422, detail=f"Unknown category on '{it.label}'")
        if it.key and it.key in existing:
            conn.execute(
                """UPDATE price_book SET label = ?, category = ?, unit = ?, alt_unit = ?, mode_group = ?, price = ?, alt_price = ?,
                   description = ?, active = ? WHERE key = ?""",
                (it.label.strip(), it.category, it.unit, it.alt_unit, it.mode_group, it.price, it.alt_price, it.description, int(it.active), it.key),
            )
        else:
            key = it.key or ("custom_" + "".join(ch if ch.isalnum() else "_" for ch in it.label.lower()).strip("_")[:40])
            n = 1
            base = key
            while key in existing:
                n += 1
                key = f"{base}_{n}"
            max_sort += 10
            conn.execute(
                """INSERT INTO price_book (key, label, category, unit, alt_unit, mode_group, price, alt_price, description, sort_order, active, custom)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (key, it.label.strip(), it.category, it.unit, it.alt_unit, it.mode_group, it.price, it.alt_price, it.description, max_sort, int(it.active)),
            )
            existing.add(key)
    return get_pricebook(conn)


@router.delete("/pricebook/{key}", status_code=204)
def delete_price_item(key: str, conn: sqlite3.Connection = Depends(db_dependency)):
    row = conn.execute("SELECT custom FROM price_book WHERE key = ?", (key,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Item not found")
    if not row[0]:
        raise HTTPException(status_code=422, detail="Built-in items can be hidden (inactive) but not deleted")
    conn.execute("DELETE FROM price_book WHERE key = ?", (key,))
    return None


# ---- Quote defaults from the topology ------------------------------------------------

def clinic_counts(conn: sqlite3.Connection, clinic_id: int) -> dict:
    devs = rows_to_list(conn.execute("SELECT device_type, designation, user_name FROM devices WHERE clinic_id = ? AND status = 'active'", (clinic_id,)))
    def n(t):
        return sum(1 for d in devs if d["device_type"] == t)
    servers = [d for d in devs if d["device_type"] == "server"]
    vm_type = sum(1 for d in devs if d["device_type"] == "vm")
    # Back-compat: a server tagged as a VM in its designation still counts as a VM.
    legacy_vms = sum(1 for d in servers if any(k in (d["designation"] or "").lower() for k in ("vm", "virtual")))
    vms = vm_type + legacy_vms
    physical = len(servers) - legacy_vms
    users = {(d["user_name"] or "").strip().lower() for d in devs if d["device_type"] in ("workstation", "laptop", "wireless", "voip", "vm") and d["user_name"]}
    sites = 1 + conn.execute("SELECT COUNT(*) FROM clinic_locations WHERE clinic_id = ?", (clinic_id,)).fetchone()[0]
    counts = {
        "workstations": n("workstation"), "laptops": n("laptop"), "wireless": n("wireless"),
        "servers_physical": physical, "vms": vms, "servers_all": physical + vms,
        "firewalls": n("firewall"), "routers": n("router"), "switches": n("switch"), "aps": n("access_point"),
        "phones": n("voip"), "printers": n("printer"), "sites": sites,
        "users": len(users) or n("workstation") + n("laptop"),
        "one": 1, "zero": 0,
    }
    counts["devices_managed"] = counts["workstations"] + counts["laptops"] + counts["servers_all"]
    return counts


def build_lines(items: list[dict], counts: dict, pricing_mode: str, emr_mode: str) -> list[dict]:
    lines = []
    for it in items:
        if not it["active"]:
            continue
        unit, price = it["unit"], it["price"] or 0
        if it.get("mode_group") == "plan" and pricing_mode == "per_user" and it.get("alt_unit"):
            unit, price = it["alt_unit"], it["alt_price"] or 0
        if it.get("mode_group") == "emr" and emr_mode == "per_user" and it.get("alt_unit"):
            unit, price = it["alt_unit"], it["alt_price"] or 0
        qty = counts.get(QTY_SOURCES.get(unit, "zero"), 0)
        lines.append({
            "key": it["key"], "label": it["label"], "category": it["category"], "unit": unit,
            "qty": qty, "unit_price": float(price), "included": it["key"] in DEFAULT_INCLUDED or it["custom"],
            "description": it.get("description"),
        })
    return lines


@router.get("/clinics/{clinic_id}/quote-defaults")
def quote_defaults(clinic_id: int, pricing_mode: str = "per_device", emr_mode: str = "flat", conn: sqlite3.Connection = Depends(db_dependency)):
    clinic = row_to_dict(conn.execute("SELECT * FROM clinics WHERE id = ?", (clinic_id,)).fetchone())
    if clinic is None:
        raise HTTPException(status_code=404, detail="Clinic not found")
    pb = get_pricebook(conn)
    counts = clinic_counts(conn, clinic_id)
    contacts = rows_to_list(conn.execute("SELECT id, first_name, last_name, role, email, is_primary FROM contacts WHERE clinic_id = ? ORDER BY is_primary DESC, last_name", (clinic_id,)))
    return {
        "counts": counts,
        "lines": build_lines(pb["items"], counts, pricing_mode, emr_mode),
        "company": pb["company"],
        "categories": QUOTE_CATEGORIES,
        "units": UNIT_LABELS,
        "contacts": contacts,
        "suggested_title": f"Managed IT services for {clinic['name']}",
        "valid_until": (date.today() + timedelta(days=pb["company"]["valid_days"])).isoformat(),
        "tax_pct": pb["company"]["tax_pct"],
        "terms": pb["company"]["terms"],
    }


# ---- Quotes ----------------------------------------------------------------------------

def compute_totals(lines: list[dict], discount_pct: float, tax_pct: float) -> dict:
    monthly = 0.0
    onetime = 0.0
    for ln in lines:
        if not ln.get("included"):
            continue
        total = round(float(ln.get("qty") or 0) * float(ln.get("unit_price") or 0), 2)
        ln["total"] = total
        if ln.get("unit") == "one_time":
            onetime += total
        else:
            monthly += total
    discount = round(monthly * (discount_pct or 0) / 100, 2)
    monthly_after = monthly - discount
    monthly_tax = round(monthly_after * (tax_pct or 0) / 100, 2)
    onetime_tax = round(onetime * (tax_pct or 0) / 100, 2)
    return {
        "monthly_subtotal": round(monthly, 2), "discount": discount, "monthly_tax": monthly_tax,
        "monthly_total": round(monthly_after + monthly_tax, 2),
        "onetime_subtotal": round(onetime, 2), "onetime_tax": onetime_tax, "onetime_total": round(onetime + onetime_tax, 2),
        "annual_total": round((monthly_after + monthly_tax) * 12, 2),
    }


SELECT = """SELECT q.*, cl.name AS clinic_name, cl.shorthand AS clinic_shorthand, cl.address AS clinic_address, cl.city AS clinic_city,
                   cl.province AS clinic_province, cl.postal_code AS clinic_postal_code, cl.phone AS clinic_phone,
                   c.first_name AS contact_first_name, c.last_name AS contact_last_name, c.email AS contact_email, c.title AS contact_title
            FROM quotes q JOIN clinics cl ON cl.id = q.clinic_id LEFT JOIN contacts c ON c.id = q.contact_id"""


def _decorate(q: dict) -> dict:
    q["lines"] = json.loads(q["lines"]) if isinstance(q["lines"], str) else q["lines"]
    q["counts"] = json.loads(q["counts"]) if isinstance(q.get("counts"), str) and q["counts"] else (q.get("counts") or {})
    q["number"] = f"Q-{(q['created_at'] or '')[:4]}-{q['id']:04d}"
    q["status_label"] = STATUS_LABELS.get(q["status"], q["status"])
    q["totals"] = compute_totals([dict(l) for l in q["lines"]], q["discount_pct"], q["tax_pct"])
    q["contact_name"] = " ".join(p for p in [q.get("contact_first_name"), q.get("contact_last_name")] if p) or None
    q["categories"] = QUOTE_CATEGORIES
    q["units"] = UNIT_LABELS
    for ln in q["lines"]:
        ln["unit_label"] = UNIT_LABELS.get(ln.get("unit"), ln.get("unit"))
        ln["category_label"] = QUOTE_CATEGORIES.get(ln.get("category"), ln.get("category"))
    return q


def _get_or_404(conn: sqlite3.Connection, quote_id: int) -> dict:
    row = row_to_dict(conn.execute(f"{SELECT} WHERE q.id = ?", (quote_id,)).fetchone())
    if row is None:
        raise HTTPException(status_code=404, detail="Quote not found")
    return _decorate(row)


def _persist_fields(payload: QuoteIn) -> tuple[list, dict]:
    lines = [ln.model_dump() for ln in payload.lines]
    if payload.plan_key:
        # exactly one plan included
        for ln in lines:
            if ln["category"] == "plan":
                ln["included"] = ln["key"] == payload.plan_key
    totals = compute_totals(lines, payload.discount_pct, payload.tax_pct)
    return lines, totals


@router.get("/quotes")
def list_quotes(clinic_id: int | None = None, status: str | None = None, conn: sqlite3.Connection = Depends(db_dependency)):
    sql = f"{SELECT} WHERE 1=1"
    params: list = []
    if clinic_id is not None:
        sql += " AND q.clinic_id = ?"
        params.append(clinic_id)
    if status:
        sql += " AND q.status = ?"
        params.append(status)
    sql += " ORDER BY q.created_at DESC, q.id DESC"
    out = [_decorate(r) for r in rows_to_list(conn.execute(sql, params))]
    for q in out:
        q.pop("lines", None)  # keep the list light
    return out


@router.post("/clinics/{clinic_id}/quotes", status_code=201)
def create_quote(clinic_id: int, payload: QuoteIn, conn: sqlite3.Connection = Depends(db_dependency)):
    clinic = row_to_dict(conn.execute("SELECT * FROM clinics WHERE id = ?", (clinic_id,)).fetchone())
    if clinic is None:
        raise HTTPException(status_code=404, detail="Clinic not found")
    lines, totals = _persist_fields(payload)
    cur = conn.execute(
        """INSERT INTO quotes (clinic_id, title, pricing_mode, emr_mode, plan_key, user_count, device_count, counts, lines, discount_pct, tax_pct,
           monthly_subtotal, monthly_total, onetime_subtotal, onetime_total, notes, terms, prepared_by, contact_id, valid_until)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (clinic_id, payload.title.strip(), payload.pricing_mode, payload.emr_mode, payload.plan_key, payload.user_count, payload.device_count,
         json.dumps(payload.counts or {}), json.dumps(lines), payload.discount_pct, payload.tax_pct,
         totals["monthly_subtotal"], totals["monthly_total"], totals["onetime_subtotal"], totals["onetime_total"],
         payload.notes, payload.terms, payload.prepared_by, payload.contact_id, payload.valid_until),
    )
    q = _get_or_404(conn, cur.lastrowid)
    log_event(conn, clinic_id, "quote", f"Quote {q['number']} created: {payload.title.strip()}", f"{totals['monthly_total']:.2f}/month")
    return q


@router.get("/quotes/{quote_id}")
def get_quote(quote_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    return _get_or_404(conn, quote_id)


@router.put("/quotes/{quote_id}")
def update_quote(quote_id: int, payload: QuoteIn, conn: sqlite3.Connection = Depends(db_dependency)):
    _get_or_404(conn, quote_id)
    lines, totals = _persist_fields(payload)
    conn.execute(
        """UPDATE quotes SET title = ?, pricing_mode = ?, emr_mode = ?, plan_key = ?, user_count = ?, device_count = ?, counts = ?, lines = ?,
           discount_pct = ?, tax_pct = ?, monthly_subtotal = ?, monthly_total = ?, onetime_subtotal = ?, onetime_total = ?, notes = ?, terms = ?,
           prepared_by = ?, contact_id = ?, valid_until = ?, updated_at = ? WHERE id = ?""",
        (payload.title.strip(), payload.pricing_mode, payload.emr_mode, payload.plan_key, payload.user_count, payload.device_count,
         json.dumps(payload.counts or {}), json.dumps(lines), payload.discount_pct, payload.tax_pct,
         totals["monthly_subtotal"], totals["monthly_total"], totals["onetime_subtotal"], totals["onetime_total"],
         payload.notes, payload.terms, payload.prepared_by, payload.contact_id, payload.valid_until, now_iso(), quote_id),
    )
    return _get_or_404(conn, quote_id)


@router.patch("/quotes/{quote_id}/status")
def set_quote_status(quote_id: int, payload: QuoteStatusIn, conn: sqlite3.Connection = Depends(db_dependency)):
    q = _get_or_404(conn, quote_id)
    conn.execute("UPDATE quotes SET status = ?, sent_at = COALESCE(sent_at, ?), updated_at = ? WHERE id = ?",
                 (payload.status, now_iso() if payload.status == "sent" else None, now_iso(), quote_id))
    log_event(conn, q["clinic_id"], "quote", f"Quote {q['number']} marked {STATUS_LABELS[payload.status].lower()}", f"{q['totals']['monthly_total']:.2f}/month")
    # Sending a quote is a proposal; nudge the pipeline forward without going backwards.
    # A quote also pulls a not-yet-contacted lead onto the board (and marks it Interested).
    if payload.status == "sent":
        row = conn.execute("SELECT stage, relationship FROM clinics WHERE id = ?", (q["clinic_id"],)).fetchone()
        stage, relationship = row[0], row[1]
        if stage in ("lead", "prospect", "contacted", "demo"):
            new_rel = "interested" if relationship == "prospect" else relationship
            conn.execute("UPDATE clinics SET stage = 'proposal', relationship = ?, updated_at = ? WHERE id = ?",
                         (new_rel, now_iso(), q["clinic_id"]))
            log_event(conn, q["clinic_id"], "stage_change", "Stage: → Quote sent", None, from_value=stage, to_value="proposal")
    return _get_or_404(conn, quote_id)


@router.post("/quotes/{quote_id}/apply-to-deal")
def apply_to_deal(quote_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    """Copy the annual value of the quote onto the clinic's deal."""
    q = _get_or_404(conn, quote_id)
    annual = q["totals"]["annual_total"]
    conn.execute("UPDATE clinics SET deal_value = ?, updated_at = ? WHERE id = ?", (annual, now_iso(), q["clinic_id"]))
    log_event(conn, q["clinic_id"], "quote", f"Deal value set from quote {q['number']}", f"{annual:.2f}/year")
    return {"clinic_id": q["clinic_id"], "deal_value": annual}


@router.post("/quotes/{quote_id}/duplicate", status_code=201)
def duplicate_quote(quote_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    q = _get_or_404(conn, quote_id)
    cur = conn.execute(
        """INSERT INTO quotes (clinic_id, title, pricing_mode, emr_mode, plan_key, user_count, device_count, counts, lines, discount_pct, tax_pct,
           monthly_subtotal, monthly_total, onetime_subtotal, onetime_total, notes, terms, prepared_by, contact_id, valid_until)
           SELECT clinic_id, title || ' (copy)', pricing_mode, emr_mode, plan_key, user_count, device_count, counts, lines, discount_pct, tax_pct,
           monthly_subtotal, monthly_total, onetime_subtotal, onetime_total, notes, terms, prepared_by, contact_id, ? FROM quotes WHERE id = ?""",
        ((date.today() + timedelta(days=30)).isoformat(), quote_id),
    )
    return _get_or_404(conn, cur.lastrowid)


@router.delete("/quotes/{quote_id}", status_code=204)
def delete_quote(quote_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    _get_or_404(conn, quote_id)
    conn.execute("DELETE FROM quotes WHERE id = ?", (quote_id,))
    return None


@router.get("/quotes/{quote_id}/export.csv")
def quote_csv(quote_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    q = _get_or_404(conn, quote_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Quote", q["number"], q["title"]])
    w.writerow(["Clinic", q["clinic_name"], q.get("clinic_address") or ""])
    w.writerow(["Pricing basis", q["pricing_mode"].replace("_", " "), f"{q['device_count']} devices", f"{q['user_count']} users"])
    w.writerow([])
    w.writerow(["Category", "Item", "Unit", "Qty", "Unit price", "Total", "Included"])
    for ln in q["lines"]:
        w.writerow([ln.get("category_label"), ln["label"], ln.get("unit_label"), ln["qty"], f"{ln['unit_price']:.2f}", f"{ln.get('total', 0):.2f}", "yes" if ln["included"] else "no"])
    t = q["totals"]
    w.writerow([])
    w.writerow(["Monthly subtotal", f"{t['monthly_subtotal']:.2f}"])
    w.writerow([f"Discount ({q['discount_pct']}%)", f"-{t['discount']:.2f}"])
    w.writerow([f"Tax ({q['tax_pct']}%)", f"{t['monthly_tax']:.2f}"])
    w.writerow(["Monthly total", f"{t['monthly_total']:.2f}"])
    w.writerow(["One-time total", f"{t['onetime_total']:.2f}"])
    w.writerow(["Annual equivalent", f"{t['annual_total']:.2f}"])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{q["number"]}.csv"'})
