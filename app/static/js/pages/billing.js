// Billing hub: Inventory, Orders and Invoices tabs.
import { inventory, orders, invoices, billingMeta } from '../api.js';
import { esc, attr, dot, badge, fmtMoney, fmtDateOnly, setTitle, navigate, debounce, toast, confirmDialog } from '../ui.js';
import { openInventoryForm, openOrderForm, openReceiveDialog, openInvoiceForm } from '../billing-forms.js';

let meta = null;
let tab = 'inventory';
const invState = { q: '', low: false };
const ordState = { status: '' };
const invoiceState = { status: '' };

export async function render(container, params) {
  setTitle('Billing');
  container.classList.add('wide');
  meta = await billingMeta();
  tab = (params && params.get('tab')) || tab || 'inventory';
  container.innerHTML = `
    <div class="page-header">
      <h1>Billing</h1>
      <div class="actions" id="tab-action"></div>
    </div>
    <div class="tabs" id="tabs">
      ${['inventory', 'orders', 'invoices'].map(t => `<button data-tab="${t}" class="${t === tab ? 'active' : ''}">${t[0].toUpperCase() + t.slice(1)}</button>`).join('')}
    </div>
    <div id="tab-body"></div>`;
  container.querySelectorAll('#tabs button').forEach(b => b.onclick = () => { tab = b.dataset.tab; window.location.hash = `#/billing?tab=${tab}`; renderTab(container); });
  renderTab(container);
}

export function destroy(container) { container.classList.remove('wide'); }

function renderTab(container) {
  container.querySelectorAll('#tabs button').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  if (tab === 'orders') return renderOrders(container);
  if (tab === 'invoices') return renderInvoices(container);
  return renderInventory(container);
}

// ---- Inventory --------------------------------------------------------------

async function renderInventory(container) {
  container.querySelector('#tab-action').innerHTML = '<button class="btn btn-primary" id="add-item">+ Item</button>';
  container.querySelector('#add-item').onclick = () => openInventoryForm({ onSaved: () => renderInventory(container) });
  const body = container.querySelector('#tab-body');
  body.innerHTML = `
    <div class="toolbar">
      <input type="search" class="search" id="inv-q" placeholder="Search items, SKU, supplier…" value="${attr(invState.q)}">
      <label class="checkbox"><input type="checkbox" id="inv-low" ${invState.low ? 'checked' : ''}> Low stock only <span class="muted" id="low-count"></span></label>
    </div>
    <div class="table-wrap" id="inv-table"></div>`;
  const q = body.querySelector('#inv-q');
  q.addEventListener('input', debounce(() => { invState.q = q.value; loadInventory(body); }, 200));
  body.querySelector('#inv-low').onchange = (e) => { invState.low = e.target.checked; loadInventory(body); };
  loadInventory(body);
}

async function loadInventory(body) {
  const items = await inventory.list({ q: invState.q, low: invState.low ? 'true' : undefined });
  const lowN = (await inventory.list({ low: 'true' })).length;
  const lc = body.querySelector('#low-count'); if (lc) lc.textContent = lowN ? `(${lowN})` : '';
  const el = body.querySelector('#inv-table');
  if (!items.length) { el.innerHTML = '<div class="card empty">No inventory items yet. Add toner, cables, hardware — anything you stock or resell.</div>'; return; }
  el.innerHTML = `
    <table class="table">
      <thead><tr><th>Item</th><th>Category</th><th>Location</th><th class="right">On hand</th><th class="right">Cost</th><th class="right">Price</th><th class="right">Margin</th><th>Supplier</th><th></th></tr></thead>
      <tbody>${items.map(i => `
        <tr class="clickable ${i.low_stock ? 'row-warn' : ''}" data-id="${i.id}">
          <td><strong>${esc(i.name)}</strong>${i.sku ? `<div class="muted small">${esc(i.sku)}</div>` : ''}</td>
          <td>${esc(i.category || '')}</td>
          <td>${esc(i.location || '')}</td>
          <td class="right">${i.quantity}${i.low_stock ? ' ' + badge('Low', 'badge-red') : ''}</td>
          <td class="right money">${i.cost != null ? fmtMoney(i.cost) : ''}</td>
          <td class="right money">${i.unit_price != null ? fmtMoney(i.unit_price) : ''}</td>
          <td class="right money">${i.margin != null ? fmtMoney(i.margin) : ''}</td>
          <td>${esc(i.supplier || '')}</td>
          <td class="nowrap"><button class="btn btn-sm" data-order="${i.id}">Order</button></td>
        </tr>`).join('')}</tbody>
    </table>`;
  el.querySelectorAll('tr.clickable').forEach(tr => tr.onclick = (e) => {
    if (e.target.closest('[data-order]')) return;
    const it = items.find(x => x.id === Number(tr.dataset.id));
    openInventoryForm({ item: it, onSaved: () => loadInventory(body) });
  });
  el.querySelectorAll('[data-order]').forEach(b => b.onclick = () => {
    const it = items.find(x => x.id === Number(b.dataset.order));
    openOrderForm({ order: { name: it.name, item_id: it.id, sku: it.sku, supplier: it.supplier, unit_cost: it.cost, unit_price: it.unit_price, quantity: 1 }, onSaved: () => toast('Order created — see the Orders tab', 'success') });
  });
}

// ---- Orders -----------------------------------------------------------------

async function renderOrders(container) {
  container.querySelector('#tab-action').innerHTML = '<button class="btn btn-primary" id="add-order">+ Order</button>';
  container.querySelector('#add-order').onclick = () => openOrderForm({ onSaved: () => renderOrders(container) });
  const body = container.querySelector('#tab-body');
  body.innerHTML = `
    <div class="toolbar">
      <select id="ord-status">${['', 'ordered', 'received', 'cancelled'].map(s => `<option value="${s}" ${ordState.status === s ? 'selected' : ''}>${s ? meta.order_statuses[s] : 'All orders'}</option>`).join('')}</select>
    </div>
    <div class="table-wrap" id="ord-table"></div>`;
  body.querySelector('#ord-status').onchange = (e) => { ordState.status = e.target.value; loadOrders(body); };
  loadOrders(body);
}

async function loadOrders(body) {
  const rows = await orders.list({ status: ordState.status || undefined });
  const el = body.querySelector('#ord-table');
  if (!rows.length) { el.innerHTML = '<div class="card empty">No orders. When something isn’t in stock, add an order and mark it received when it arrives.</div>'; return; }
  const stCls = { ordered: 'badge-yellow', received: 'badge-green', cancelled: 'badge-grey' };
  el.innerHTML = `
    <table class="table">
      <thead><tr><th>Item</th><th class="right">Qty</th><th>Supplier</th><th>For clinic</th><th>Expected</th><th class="right">Cost</th><th>Status</th><th></th></tr></thead>
      <tbody>${rows.map(o => `
        <tr data-id="${o.id}">
          <td><strong>${esc(o.name)}</strong>${o.ticket_url ? ` <a href="${attr(o.ticket_url)}" target="_blank" rel="noopener" title="Ticket">🎫</a>` : ''}${o.disposition ? `<div class="muted small">${o.disposition === 'inventory' ? 'Stocked' : 'Billed to client'}</div>` : ''}</td>
          <td class="right">${o.quantity}</td>
          <td>${esc(o.supplier || '')}</td>
          <td>${o.clinic_id ? `<a href="#/clinics/${o.clinic_id}">${esc(o.clinic_name || '')}</a>` : '<span class="muted">—</span>'}</td>
          <td class="nowrap">${o.expected_date ? esc(fmtDateOnly(o.expected_date)) : ''}</td>
          <td class="right money">${o.line_cost ? fmtMoney(o.line_cost) : ''}</td>
          <td>${badge(o.status_label, stCls[o.status] || '')}</td>
          <td class="nowrap">
            ${o.status === 'ordered' ? `<button class="btn btn-sm btn-primary" data-recv="${o.id}">Receive</button>` : ''}
            <button class="btn btn-sm" data-edit="${o.id}">Edit</button>
          </td>
        </tr>`).join('')}</tbody>
    </table>`;
  el.querySelectorAll('[data-recv]').forEach(b => b.onclick = () => {
    const o = rows.find(x => x.id === Number(b.dataset.recv));
    openReceiveDialog({ order: o, onSaved: () => loadOrders(body) });
  });
  el.querySelectorAll('[data-edit]').forEach(b => b.onclick = () => {
    const o = rows.find(x => x.id === Number(b.dataset.edit));
    openOrderForm({ order: o, onSaved: () => loadOrders(body) });
  });
}

// ---- Invoices ---------------------------------------------------------------

async function renderInvoices(container) {
  container.querySelector('#tab-action').innerHTML = '<button class="btn btn-primary" id="add-invoice">+ Invoice</button>';
  container.querySelector('#add-invoice').onclick = () => openInvoiceForm({ onSaved: (iv) => iv && navigate(`#/invoices/${iv.id}`) });
  const body = container.querySelector('#tab-body');
  body.innerHTML = `
    <div class="toolbar">
      <select id="inv-status">${['', 'draft', 'sent', 'paid', 'void'].map(s => `<option value="${s}" ${invoiceState.status === s ? 'selected' : ''}>${s ? meta.invoice_statuses[s] : 'All invoices'}</option>`).join('')}</select>
    </div>
    <div class="table-wrap" id="invoice-table"></div>`;
  body.querySelector('#inv-status').onchange = (e) => { invoiceState.status = e.target.value; loadInvoices(body); };
  loadInvoices(body);
}

async function loadInvoices(body) {
  const rows = await invoices.list({ status: invoiceState.status || undefined });
  const el = body.querySelector('#invoice-table');
  if (!rows.length) { el.innerHTML = '<div class="card empty">No invoices yet. Create one here or from a clinic’s profile.</div>'; return; }
  const stCls = { draft: 'badge-grey', sent: 'badge-yellow', paid: 'badge-green', void: 'badge-red' };
  el.innerHTML = `
    <table class="table">
      <thead><tr><th>Invoice</th><th>Client</th><th>Title</th><th>Issued</th><th class="right">Total</th><th>Status</th><th></th></tr></thead>
      <tbody>${rows.map(iv => `
        <tr class="clickable" data-id="${iv.id}">
          <td><strong>${esc(iv.number)}</strong>${iv.ticket_url ? ` <a href="${attr(iv.ticket_url)}" target="_blank" rel="noopener" title="Ticket">🎫</a>` : ''}</td>
          <td><a href="#/clinics/${iv.clinic_id}">${esc(iv.clinic_name)}</a></td>
          <td>${esc(iv.title || '')}</td>
          <td class="nowrap">${iv.issue_date ? esc(fmtDateOnly(iv.issue_date)) : ''}</td>
          <td class="right money">${fmtMoney(iv.total)}</td>
          <td>${badge(iv.status_label, stCls[iv.status] || '')}</td>
          <td class="nowrap"><a class="btn btn-sm" href="#/invoices/${iv.id}">Open</a></td>
        </tr>`).join('')}</tbody>
    </table>`;
  el.querySelectorAll('tr.clickable').forEach(tr => tr.onclick = (e) => { if (!e.target.closest('a')) navigate(`#/invoices/${tr.dataset.id}`); });
}
