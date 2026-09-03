"""Inventory, purchase orders and client invoices."""
from __future__ import annotations

import csv
import io
import sqlite3
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ..database import db_dependency, row_to_dict, rows_to_list
from ..logic import (
    INVENTORY_CATEGORIES, INVOICE_BILLED_STATUSES, INVOICE_STATUS_LABELS, ORDER_STATUS_LABELS,
    log_event, now_iso,
)
from ..schemas import (
    InventoryItemIn, InvoiceIn, InvoiceStatusIn, OrderIn, OrderReceiveIn, StockAdjustIn,
)

router = APIRouter(prefix="/api", tags=["billing"])

INVENTORY_COLUMNS = [
    "name", "sku", "category", "description", "location", "unit_price", "cost",
    "quantity", "reorder_level", "supplier", "notes",
]
ORDER_COLUMNS = [
    "name", "item_id", "clinic_id", "sku", "supplier", "quantity", "unit_cost", "unit_price",
    "status", "ordered_date", "expected_date", "ticket_url", "notes",
]


# ---- Meta -------------------------------------------------------------------

@router.get("/meta/billing")
def meta_billing():
    return {
        "inventory_categories": INVENTORY_CATEGORIES,
        "order_statuses": ORDER_STATUS_LABELS,
        "invoice_statuses": INVOICE_STATUS_LABELS,
    }


# ---- Inventory --------------------------------------------------------------

def _enrich_item(item: dict) -> dict:
    item["low_stock"] = bool(item.get("reorder_level") is not None and item["quantity"] <= item["reorder_level"])
    item["margin"] = (round(item["unit_price"] - item["cost"], 2)
                      if item.get("unit_price") is not None and item.get("cost") is not None else None)
    item["stock_value"] = round((item.get("cost") or 0) * (item.get("quantity") or 0), 2)
    return item


@router.get("/inventory")
def list_inventory(q: str | None = None, low: bool | None = None, conn: sqlite3.Connection = Depends(db_dependency)):
    sql = "SELECT * FROM inventory_items WHERE 1=1"
    params: list = []
    if q:
        like = f"%{q.strip()}%"
        sql += " AND (name LIKE ? OR sku LIKE ? OR category LIKE ? OR supplier LIKE ? OR location LIKE ?)"
        params += [like] * 5
    sql += " ORDER BY name COLLATE NOCASE"
    items = [_enrich_item(i) for i in rows_to_list(conn.execute(sql, params))]
    if low:
        items = [i for i in items if i["low_stock"]]
    return items


@router.post("/inventory", status_code=201)
def create_item(payload: InventoryItemIn, conn: sqlite3.Connection = Depends(db_dependency)):
    data = payload.model_dump()
    cols = ", ".join(INVENTORY_COLUMNS)
    marks = ", ".join("?" * len(INVENTORY_COLUMNS))
    cur = conn.execute(f"INSERT INTO inventory_items ({cols}) VALUES ({marks})", [data[c] for c in INVENTORY_COLUMNS])
    return _enrich_item(row_to_dict(conn.execute("SELECT * FROM inventory_items WHERE id = ?", (cur.lastrowid,)).fetchone()))


@router.get("/inventory/{item_id}")
def get_item(item_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    row = row_to_dict(conn.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone())
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")
    return _enrich_item(row)


@router.put("/inventory/{item_id}")
def update_item(item_id: int, payload: InventoryItemIn, conn: sqlite3.Connection = Depends(db_dependency)):
    if conn.execute("SELECT 1 FROM inventory_items WHERE id = ?", (item_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Item not found")
    data = payload.model_dump()
    sets = ", ".join(f"{c} = ?" for c in INVENTORY_COLUMNS)
    conn.execute(f"UPDATE inventory_items SET {sets}, updated_at = ? WHERE id = ?",
                 [data[c] for c in INVENTORY_COLUMNS] + [now_iso(), item_id])
    return _enrich_item(row_to_dict(conn.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone()))


@router.post("/inventory/{item_id}/adjust")
def adjust_stock(item_id: int, payload: StockAdjustIn, conn: sqlite3.Connection = Depends(db_dependency)):
    row = row_to_dict(conn.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone())
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")
    new_qty = max(0, row["quantity"] + payload.delta)
    conn.execute("UPDATE inventory_items SET quantity = ?, updated_at = ? WHERE id = ?", (new_qty, now_iso(), item_id))
    return _enrich_item(row_to_dict(conn.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone()))


@router.delete("/inventory/{item_id}", status_code=204)
def delete_item(item_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    if conn.execute("DELETE FROM inventory_items WHERE id = ?", (item_id,)).rowcount == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    return None


# ---- Orders -----------------------------------------------------------------

def _order_detail(conn: sqlite3.Connection, order_id: int) -> dict:
    row = row_to_dict(conn.execute(
        """SELECT o.*, cl.name AS clinic_name, i.name AS item_name
           FROM orders o LEFT JOIN clinics cl ON cl.id = o.clinic_id
           LEFT JOIN inventory_items i ON i.id = o.item_id WHERE o.id = ?""", (order_id,)).fetchone())
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    row["status_label"] = ORDER_STATUS_LABELS.get(row["status"], row["status"])
    row["line_cost"] = round((row["unit_cost"] or 0) * row["quantity"], 2)
    return row


@router.get("/orders")
def list_orders(status: str | None = None, conn: sqlite3.Connection = Depends(db_dependency)):
    sql = ("""SELECT o.*, cl.name AS clinic_name, i.name AS item_name
              FROM orders o LEFT JOIN clinics cl ON cl.id = o.clinic_id
              LEFT JOIN inventory_items i ON i.id = o.item_id WHERE 1=1""")
    params: list = []
    if status:
        sql += " AND o.status = ?"
        params.append(status)
    sql += " ORDER BY CASE o.status WHEN 'ordered' THEN 0 WHEN 'received' THEN 1 ELSE 2 END, o.expected_date IS NULL, o.expected_date, o.id DESC"
    rows = rows_to_list(conn.execute(sql, params))
    for r in rows:
        r["status_label"] = ORDER_STATUS_LABELS.get(r["status"], r["status"])
        r["line_cost"] = round((r["unit_cost"] or 0) * r["quantity"], 2)
    return rows


@router.post("/orders", status_code=201)
def create_order(payload: OrderIn, conn: sqlite3.Connection = Depends(db_dependency)):
    data = payload.model_dump()
    if not data.get("ordered_date"):
        data["ordered_date"] = now_iso()[:10]
    # Default name/price from the linked inventory item when not given.
    if data.get("item_id"):
        item = row_to_dict(conn.execute("SELECT * FROM inventory_items WHERE id = ?", (data["item_id"],)).fetchone())
        if item:
            data["unit_cost"] = data["unit_cost"] if data["unit_cost"] is not None else item["cost"]
            data["unit_price"] = data["unit_price"] if data["unit_price"] is not None else item["unit_price"]
            data["sku"] = data["sku"] or item["sku"]
            data["supplier"] = data["supplier"] or item["supplier"]
    cols = ", ".join(ORDER_COLUMNS)
    marks = ", ".join("?" * len(ORDER_COLUMNS))
    cur = conn.execute(f"INSERT INTO orders ({cols}) VALUES ({marks})", [data[c] for c in ORDER_COLUMNS])
    return _order_detail(conn, cur.lastrowid)


@router.put("/orders/{order_id}")
def update_order(order_id: int, payload: OrderIn, conn: sqlite3.Connection = Depends(db_dependency)):
    if conn.execute("SELECT 1 FROM orders WHERE id = ?", (order_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Order not found")
    data = payload.model_dump()
    sets = ", ".join(f"{c} = ?" for c in ORDER_COLUMNS)
    conn.execute(f"UPDATE orders SET {sets}, updated_at = ? WHERE id = ?",
                 [data[c] for c in ORDER_COLUMNS] + [now_iso(), order_id])
    return _order_detail(conn, order_id)


@router.delete("/orders/{order_id}", status_code=204)
def delete_order(order_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    if conn.execute("DELETE FROM orders WHERE id = ?", (order_id,)).rowcount == 0:
        raise HTTPException(status_code=404, detail="Order not found")
    return None


@router.post("/orders/{order_id}/receive")
def receive_order(order_id: int, payload: OrderReceiveIn, conn: sqlite3.Connection = Depends(db_dependency)):
    """Mark an order received and either stock it or bill it to a client."""
    order = row_to_dict(conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone())
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    result: dict = {}

    if payload.disposition == "inventory":
        item_id = payload.item_id or order["item_id"]
        if item_id:
            item = row_to_dict(conn.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone())
            if not item:
                raise HTTPException(status_code=404, detail="Inventory item not found")
            conn.execute("UPDATE inventory_items SET quantity = quantity + ?, updated_at = ? WHERE id = ?",
                         (order["quantity"], now_iso(), item_id))
        else:
            cur = conn.execute(
                """INSERT INTO inventory_items (name, sku, unit_price, cost, quantity, supplier)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (order["name"], order["sku"], order["unit_price"], order["unit_cost"], order["quantity"], order["supplier"]))
            item_id = cur.lastrowid
        conn.execute("UPDATE orders SET status='received', disposition='inventory', item_id=?, received_date=?, updated_at=? WHERE id=?",
                     (item_id, now_iso()[:10], now_iso(), order_id))
        result["item_id"] = item_id

    else:  # invoice
        invoice_id = payload.invoice_id
        if not invoice_id:
            clinic_id = payload.clinic_id or order["clinic_id"]
            if not clinic_id:
                raise HTTPException(status_code=422, detail="Choose a clinic to bill, or an existing draft invoice")
            if conn.execute("SELECT 1 FROM clinics WHERE id = ?", (clinic_id,)).fetchone() is None:
                raise HTTPException(status_code=404, detail="Clinic not found")
            cur = conn.execute(
                "INSERT INTO invoices (clinic_id, title, status, issue_date, tax_pct) VALUES (?, ?, 'draft', ?, ?)",
                (clinic_id, f"Order: {order['name']}", now_iso()[:10], _default_tax(conn)))
            invoice_id = cur.lastrowid
        else:
            inv = row_to_dict(conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone())
            if not inv:
                raise HTTPException(status_code=404, detail="Invoice not found")
            if inv["status"] != "draft":
                raise HTTPException(status_code=422, detail="Can only add to a draft invoice")
        conn.execute(
            "INSERT INTO invoice_lines (invoice_id, description, quantity, unit_price) VALUES (?, ?, ?, ?)",
            (invoice_id, order["name"], order["quantity"], order["unit_price"] or order["unit_cost"] or 0))
        _recompute_invoice(conn, invoice_id)
        conn.execute("UPDATE orders SET status='received', disposition='invoiced', received_date=?, updated_at=? WHERE id=?",
                     (now_iso()[:10], now_iso(), order_id))
        result["invoice_id"] = invoice_id

    result["order"] = _order_detail(conn, order_id)
    return result


# ---- Invoices ---------------------------------------------------------------

def _default_tax(conn: sqlite3.Connection) -> float:
    row = conn.execute("SELECT value FROM settings WHERE key = 'quote_tax_pct'").fetchone()
    try:
        return float(row[0]) if row and row[0] else 0.0
    except (ValueError, TypeError):
        return 0.0


def _recompute_invoice(conn: sqlite3.Connection, invoice_id: int) -> None:
    inv = row_to_dict(conn.execute("SELECT tax_pct, discount_pct FROM invoices WHERE id = ?", (invoice_id,)).fetchone())
    lines = rows_to_list(conn.execute("SELECT quantity, unit_price FROM invoice_lines WHERE invoice_id = ?", (invoice_id,)))
    subtotal = sum((l["quantity"] or 0) * (l["unit_price"] or 0) for l in lines)
    discount = subtotal * (inv["discount_pct"] or 0) / 100
    taxed_base = subtotal - discount
    tax = taxed_base * (inv["tax_pct"] or 0) / 100
    total = taxed_base + tax
    conn.execute("UPDATE invoices SET subtotal = ?, tax = ?, total = ?, updated_at = ? WHERE id = ?",
                 (round(subtotal, 2), round(tax, 2), round(total, 2), now_iso(), invoice_id))


def _apply_stock(conn: sqlite3.Connection, invoice_id: int, sign: int) -> None:
    """Deduct (sign=-1) or restore (sign=+1) inventory for this invoice's item-linked lines."""
    for l in rows_to_list(conn.execute(
            "SELECT item_id, quantity FROM invoice_lines WHERE invoice_id = ? AND item_id IS NOT NULL", (invoice_id,))):
        conn.execute("UPDATE inventory_items SET quantity = MAX(0, quantity + ?), updated_at = ? WHERE id = ?",
                     (int(sign * (l["quantity"] or 0)), now_iso(), l["item_id"]))


def _invoice_number(row: dict) -> str:
    return f"INV-{(row['created_at'] or '')[:4]}-{row['id']:04d}"


def _invoice_detail(conn: sqlite3.Connection, invoice_id: int) -> dict:
    row = row_to_dict(conn.execute(
        """SELECT inv.*, cl.name AS clinic_name, cl.address AS clinic_address, cl.shorthand AS clinic_shorthand,
                  c.first_name AS contact_first_name, c.last_name AS contact_last_name, c.email AS contact_email
           FROM invoices inv JOIN clinics cl ON cl.id = inv.clinic_id
           LEFT JOIN contacts c ON c.id = inv.contact_id WHERE inv.id = ?""", (invoice_id,)).fetchone())
    if not row:
        raise HTTPException(status_code=404, detail="Invoice not found")
    row["number"] = _invoice_number(row)
    row["status_label"] = INVOICE_STATUS_LABELS.get(row["status"], row["status"])
    row["lines"] = rows_to_list(conn.execute(
        "SELECT * FROM invoice_lines WHERE invoice_id = ? ORDER BY id", (invoice_id,)))
    for l in row["lines"]:
        l["line_total"] = round((l["quantity"] or 0) * (l["unit_price"] or 0), 2)
    company = {}
    for k in ("company_name", "company_contact"):
        r = conn.execute("SELECT value FROM settings WHERE key = ?", (k,)).fetchone()
        company[k] = r[0] if r else None
    row["company"] = company
    return row


def _write_lines(conn: sqlite3.Connection, invoice_id: int, lines: list) -> None:
    conn.execute("DELETE FROM invoice_lines WHERE invoice_id = ?", (invoice_id,))
    for l in lines:
        conn.execute(
            "INSERT INTO invoice_lines (invoice_id, item_id, description, quantity, unit_price) VALUES (?, ?, ?, ?, ?)",
            (invoice_id, l.item_id, l.description.strip(), l.quantity, l.unit_price))


@router.get("/invoices")
def list_invoices(clinic_id: int | None = None, status: str | None = None, conn: sqlite3.Connection = Depends(db_dependency)):
    sql = "SELECT inv.*, cl.name AS clinic_name FROM invoices inv JOIN clinics cl ON cl.id = inv.clinic_id WHERE 1=1"
    params: list = []
    if clinic_id is not None:
        sql += " AND inv.clinic_id = ?"
        params.append(clinic_id)
    if status:
        sql += " AND inv.status = ?"
        params.append(status)
    sql += " ORDER BY inv.created_at DESC, inv.id DESC"
    rows = rows_to_list(conn.execute(sql, params))
    for r in rows:
        r["number"] = _invoice_number(r)
        r["status_label"] = INVOICE_STATUS_LABELS.get(r["status"], r["status"])
    return rows


@router.post("/clinics/{clinic_id}/invoices", status_code=201)
def create_invoice(clinic_id: int, payload: InvoiceIn, conn: sqlite3.Connection = Depends(db_dependency)):
    if conn.execute("SELECT 1 FROM clinics WHERE id = ?", (clinic_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Clinic not found")
    cur = conn.execute(
        """INSERT INTO invoices (clinic_id, contact_id, title, issue_date, due_date, ticket_url, notes, tax_pct, discount_pct)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (clinic_id, payload.contact_id, payload.title, payload.issue_date or now_iso()[:10], payload.due_date,
         payload.ticket_url, payload.notes, payload.tax_pct, payload.discount_pct))
    invoice_id = cur.lastrowid
    _write_lines(conn, invoice_id, payload.lines)
    _recompute_invoice(conn, invoice_id)
    log_event(conn, clinic_id, "invoice", f"Invoice {_invoice_number({'created_at': now_iso(), 'id': invoice_id})} created")
    return _invoice_detail(conn, invoice_id)


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    return _invoice_detail(conn, invoice_id)


@router.put("/invoices/{invoice_id}")
def update_invoice(invoice_id: int, payload: InvoiceIn, conn: sqlite3.Connection = Depends(db_dependency)):
    inv = row_to_dict(conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone())
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    # If stock was already applied, restore it before rewriting the lines, then re-apply after.
    if inv["stock_applied"]:
        _apply_stock(conn, invoice_id, +1)
    conn.execute(
        """UPDATE invoices SET contact_id=?, title=?, issue_date=?, due_date=?, ticket_url=?, notes=?, tax_pct=?, discount_pct=?, updated_at=?
           WHERE id=?""",
        (payload.contact_id, payload.title, payload.issue_date, payload.due_date, payload.ticket_url, payload.notes,
         payload.tax_pct, payload.discount_pct, now_iso(), invoice_id))
    _write_lines(conn, invoice_id, payload.lines)
    _recompute_invoice(conn, invoice_id)
    if inv["stock_applied"]:
        _apply_stock(conn, invoice_id, -1)
    return _invoice_detail(conn, invoice_id)


@router.patch("/invoices/{invoice_id}/status")
def set_invoice_status(invoice_id: int, payload: InvoiceStatusIn, conn: sqlite3.Connection = Depends(db_dependency)):
    inv = row_to_dict(conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone())
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    new = payload.status
    should_apply = new in INVOICE_BILLED_STATUSES
    if should_apply and not inv["stock_applied"]:
        _apply_stock(conn, invoice_id, -1)
        conn.execute("UPDATE invoices SET stock_applied = 1 WHERE id = ?", (invoice_id,))
    elif not should_apply and inv["stock_applied"]:
        _apply_stock(conn, invoice_id, +1)
        conn.execute("UPDATE invoices SET stock_applied = 0 WHERE id = ?", (invoice_id,))
    sent_at = inv["sent_at"] or (now_iso() if new == "sent" else None)
    paid_at = now_iso() if new == "paid" else (None if new in ("draft", "void") else inv["paid_at"])
    conn.execute("UPDATE invoices SET status=?, sent_at=?, paid_at=?, updated_at=? WHERE id=?",
                 (new, sent_at, paid_at, now_iso(), invoice_id))
    log_event(conn, inv["clinic_id"], "invoice", f"Invoice {_invoice_number(inv)} marked {INVOICE_STATUS_LABELS[new].lower()}")
    return _invoice_detail(conn, invoice_id)


@router.delete("/invoices/{invoice_id}", status_code=204)
def delete_invoice(invoice_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    inv = row_to_dict(conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone())
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if inv["stock_applied"]:
        _apply_stock(conn, invoice_id, +1)
    conn.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))
    return None


@router.get("/invoices/{invoice_id}/export.csv")
def export_invoice(invoice_id: int, conn: sqlite3.Connection = Depends(db_dependency)):
    inv = _invoice_detail(conn, invoice_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Invoice", inv["number"]])
    w.writerow(["Clinic", inv["clinic_name"]])
    w.writerow(["Status", inv["status_label"]])
    w.writerow(["Issue date", inv["issue_date"] or ""])
    w.writerow(["Due date", inv["due_date"] or ""])
    w.writerow(["Ticket", inv["ticket_url"] or ""])
    w.writerow([])
    w.writerow(["Description", "Qty", "Unit price", "Line total"])
    for l in inv["lines"]:
        w.writerow([l["description"], l["quantity"], f'{l["unit_price"]:.2f}', f'{l["line_total"]:.2f}'])
    w.writerow([])
    w.writerow(["Subtotal", "", "", f'{inv["subtotal"]:.2f}'])
    if inv["discount_pct"]:
        w.writerow([f'Discount {inv["discount_pct"]}%', "", "", ""])
    w.writerow([f'Tax {inv["tax_pct"]}%', "", "", f'{inv["tax"]:.2f}'])
    w.writerow(["Total", "", "", f'{inv["total"]:.2f}'])
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{inv["number"]}.csv"'})
