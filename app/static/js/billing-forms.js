// Modal forms for inventory items, purchase orders and invoices.
import { inventory, orders, invoices, billingMeta, clinics } from './api.js';
import { esc, attr, options, openModal, confirmDialog, toast, formData, showFormError, fmtMoney, fmtDateOnly } from './ui.js';

// ---- Inventory item ---------------------------------------------------------

export async function openInventoryForm({ item = null, onSaved } = {}) {
  const meta = await billingMeta();
  const it = item || { quantity: 0 };
  const isEdit = !!item;
  const modal = openModal({
    title: isEdit ? `Edit ${it.name}` : 'New inventory item',
    size: 'modal-lg',
    body: `<form id="inv-form" autocomplete="off">
      <div class="field-row">
        <div class="field" style="grid-column: span 2"><label>Item name *</label><input name="name" required value="${attr(it.name)}" placeholder="e.g. HP 26A Toner"></div>
        <div class="field"><label>SKU / part #</label><input name="sku" value="${attr(it.sku)}"></div>
        <div class="field"><label>Category</label><input name="category" list="inv-cats" value="${attr(it.category)}">
          <datalist id="inv-cats">${meta.inventory_categories.map(c => `<option value="${attr(c)}">`).join('')}</datalist></div>
      </div>
      <div class="field-row">
        <div class="field"><label>On hand</label><input name="quantity" type="number" min="0" value="${attr(it.quantity ?? 0)}"></div>
        <div class="field"><label>Reorder at</label><input name="reorder_level" type="number" min="0" value="${attr(it.reorder_level ?? '')}" placeholder="low-stock alert"></div>
        <div class="field"><label>Our cost ($)</label><input name="cost" type="number" min="0" step="0.01" value="${attr(it.cost ?? '')}"></div>
        <div class="field"><label>Sell price ($)</label><input name="unit_price" type="number" min="0" step="0.01" value="${attr(it.unit_price ?? '')}"></div>
      </div>
      <div class="field-row">
        <div class="field"><label>Location</label><input name="location" value="${attr(it.location)}" placeholder="e.g. Van shelf B, Storeroom"></div>
        <div class="field"><label>Supplier</label><input name="supplier" value="${attr(it.supplier)}"></div>
      </div>
      <div class="field"><label>Notes</label><textarea name="notes" rows="2">${esc(it.notes)}</textarea></div>
    </form>`,
    footer: `${isEdit ? '<button class="btn btn-danger left" data-act="delete">Delete</button>' : ''}<button class="btn" data-act="cancel">Cancel</button><button class="btn btn-primary" data-act="save">${isEdit ? 'Save' : 'Add item'}</button>`,
  });
  const form = modal.body.querySelector('#inv-form');
  modal.root.querySelector('[data-act=cancel]').onclick = () => modal.close();
  const del = modal.root.querySelector('[data-act=delete]');
  if (del) del.onclick = async () => { if (!(await confirmDialog(`Delete "${it.name}"?`))) return; await inventory.remove(item.id); toast('Item deleted'); modal.close(); onSaved && onSaved(null); };
  const save = async () => {
    const data = formData(form);
    if (!data.name.trim()) { showFormError(form, 'Name is required.'); return; }
    try { const saved = isEdit ? await inventory.update(item.id, data) : await inventory.create(data); toast('Item saved', 'success'); modal.close(); onSaved && onSaved(saved); }
    catch (e) { showFormError(form, e.message); }
  };
  modal.root.querySelector('[data-act=save]').onclick = save;
  form.addEventListener('submit', (e) => { e.preventDefault(); save(); });
}

// ---- Purchase order ---------------------------------------------------------

export async function openOrderForm({ order = null, onSaved } = {}) {
  const [items, clinicList] = await Promise.all([inventory.list(), clinics.list()]);
  const o = order || { quantity: 1 };
  const isEdit = !!order;
  const itemOpts = `<option value="">— Custom / new item —</option>` + items.map(i => `<option value="${i.id}" ${String(i.id) === String(o.item_id) ? 'selected' : ''}>${esc(i.name)}${i.sku ? ` (${esc(i.sku)})` : ''}</option>`).join('');
  const clinicOpts = `<option value="">— Not for a specific clinic —</option>` + clinicList.map(c => `<option value="${c.id}" ${String(c.id) === String(o.clinic_id) ? 'selected' : ''}>${esc(c.name)}</option>`).join('');
  const modal = openModal({
    title: isEdit ? 'Edit order' : 'New order',
    size: 'modal-lg',
    body: `<form id="ord-form" autocomplete="off">
      <div class="field"><label>Inventory item</label><select name="item_id" id="ord-item">${itemOpts}</select>
        <div class="help">Pick an existing item, or leave as custom to order something not in inventory yet.</div></div>
      <div class="field-row">
        <div class="field" style="grid-column: span 2"><label>Item name *</label><input name="name" required value="${attr(o.name)}" placeholder="What are you ordering?"></div>
        <div class="field"><label>Quantity</label><input name="quantity" type="number" min="1" value="${attr(o.quantity ?? 1)}"></div>
      </div>
      <div class="field-row">
        <div class="field"><label>SKU</label><input name="sku" value="${attr(o.sku)}"></div>
        <div class="field"><label>Supplier</label><input name="supplier" value="${attr(o.supplier)}"></div>
        <div class="field"><label>Unit cost ($)</label><input name="unit_cost" type="number" min="0" step="0.01" value="${attr(o.unit_cost ?? '')}"></div>
        <div class="field"><label>Sell price ($)</label><input name="unit_price" type="number" min="0" step="0.01" value="${attr(o.unit_price ?? '')}"></div>
      </div>
      <div class="field-row">
        <div class="field" style="grid-column: span 2"><label>For clinic</label><select name="clinic_id">${clinicOpts}</select></div>
        <div class="field"><label>Expected date</label><input name="expected_date" type="date" value="${attr(o.expected_date)}"></div>
      </div>
      <div class="field"><label>Ticket link</label><input name="ticket_url" value="${attr(o.ticket_url)}" placeholder="https://tickets…"></div>
      <div class="field"><label>Notes</label><textarea name="notes" rows="2">${esc(o.notes)}</textarea></div>
    </form>`,
    footer: `${isEdit ? '<button class="btn btn-danger left" data-act="delete">Delete</button>' : ''}<button class="btn" data-act="cancel">Cancel</button><button class="btn btn-primary" data-act="save">${isEdit ? 'Save' : 'Add order'}</button>`,
  });
  const form = modal.body.querySelector('#ord-form');
  // Prefill from the chosen inventory item
  form.querySelector('#ord-item').onchange = (e) => {
    const it = items.find(i => String(i.id) === e.target.value);
    if (!it) return;
    if (!form.elements.name.value) form.elements.name.value = it.name;
    if (!form.elements.sku.value) form.elements.sku.value = it.sku || '';
    if (!form.elements.supplier.value) form.elements.supplier.value = it.supplier || '';
    if (!form.elements.unit_cost.value && it.cost != null) form.elements.unit_cost.value = it.cost;
    if (!form.elements.unit_price.value && it.unit_price != null) form.elements.unit_price.value = it.unit_price;
  };
  modal.root.querySelector('[data-act=cancel]').onclick = () => modal.close();
  const del = modal.root.querySelector('[data-act=delete]');
  if (del) del.onclick = async () => { if (!(await confirmDialog('Delete this order?'))) return; await orders.remove(order.id); toast('Order deleted'); modal.close(); onSaved && onSaved(null); };
  const save = async () => {
    const data = formData(form);
    if (!data.name.trim()) { showFormError(form, 'Item name is required.'); return; }
    data.item_id = data.item_id ? Number(data.item_id) : null;
    data.clinic_id = data.clinic_id ? Number(data.clinic_id) : null;
    try { const saved = isEdit ? await orders.update(order.id, data) : await orders.create(data); toast('Order saved', 'success'); modal.close(); onSaved && onSaved(saved); }
    catch (e) { showFormError(form, e.message); }
  };
  modal.root.querySelector('[data-act=save]').onclick = save;
  form.addEventListener('submit', (e) => { e.preventDefault(); save(); });
}

// ---- Receive an order -------------------------------------------------------

export async function openReceiveDialog({ order, onSaved }) {
  const clinicList = await clinics.list();
  // Draft invoices this could be appended to
  const draftInvoices = (await invoices.list({ status: 'draft' })).filter(iv => !order.clinic_id || iv.clinic_id === order.clinic_id);
  const clinicOpts = `<option value="">— Select a clinic —</option>` + clinicList.map(c => `<option value="${c.id}" ${String(c.id) === String(order.clinic_id) ? 'selected' : ''}>${esc(c.name)}</option>`).join('');
  const draftOpts = draftInvoices.map(iv => `<option value="${iv.id}">${esc(iv.number)} · ${esc(iv.clinic_name)}${iv.title ? ' · ' + esc(iv.title) : ''}</option>`).join('');
  const modal = openModal({
    title: `Receive: ${esc(order.name)}`,
    size: 'modal-sm',
    body: `<form id="recv-form">
      <p class="small muted">${order.quantity} × ${esc(order.name)} has arrived. What next?</p>
      <div class="field"><label class="radio"><input type="radio" name="disp" value="inventory" checked> Add to inventory (stock it)</label></div>
      <div class="field"><label class="radio"><input type="radio" name="disp" value="invoice"> Bill it to a client</label></div>
      <div id="recv-invoice" class="hidden" style="border-left:2px solid var(--border);padding-left:10px;margin-left:6px">
        <div class="field"><label>Add to draft invoice</label>
          <select name="invoice_id" id="recv-inv-sel"><option value="">— New invoice —</option>${draftOpts}</select></div>
        <div class="field" id="recv-clinic-wrap"><label>Client</label><select name="clinic_id">${clinicOpts}</select></div>
      </div>
    </form>`,
    footer: `<button class="btn" data-act="cancel">Cancel</button><button class="btn btn-primary" data-act="save">Receive</button>`,
  });
  const form = modal.body.querySelector('#recv-form');
  const invBox = form.querySelector('#recv-invoice');
  const syncDisp = () => { invBox.classList.toggle('hidden', form.disp.value !== 'invoice'); };
  form.querySelectorAll('[name=disp]').forEach(r => r.onchange = syncDisp);
  form.querySelector('#recv-inv-sel').onchange = (e) => { form.querySelector('#recv-clinic-wrap').classList.toggle('hidden', !!e.target.value); };
  modal.root.querySelector('[data-act=cancel]').onclick = () => modal.close();
  modal.root.querySelector('[data-act=save]').onclick = async () => {
    const disp = form.disp.value;
    const body = { disposition: disp };
    if (disp === 'invoice') {
      const invId = form.invoice_id.value;
      if (invId) body.invoice_id = Number(invId);
      else {
        const cid = form.clinic_id.value || order.clinic_id;
        if (!cid) { showFormError(form, 'Pick a client to bill.'); return; }
        body.clinic_id = Number(cid);
      }
    }
    try {
      const res = await orders.receive(order.id, body);
      toast(disp === 'inventory' ? 'Added to inventory' : 'Billed to a draft invoice', 'success');
      modal.close();
      onSaved && onSaved(res);
    } catch (e) { showFormError(form, e.message); }
  };
}

// ---- Invoice editor ---------------------------------------------------------

export async function openInvoiceForm({ clinicId = null, invoice = null, onSaved } = {}) {
  const items = await inventory.list();
  const isEdit = !!invoice;
  let clinicList = [];
  if (!clinicId && !isEdit) clinicList = await clinics.list();
  const inv = invoice || { tax_pct: 0, discount_pct: 0, lines: [] };
  const lines = (inv.lines || []).map(l => ({ item_id: l.item_id || null, description: l.description, quantity: l.quantity, unit_price: l.unit_price }));
  if (!lines.length) lines.push({ item_id: null, description: '', quantity: 1, unit_price: 0 });

  const clinicPicker = (!clinicId && !isEdit)
    ? `<div class="field"><label>Client *</label><select id="inv-clinic">${clinicList.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select></div>` : '';

  const modal = openModal({
    title: isEdit ? `Edit ${inv.number}` : 'New invoice',
    size: 'modal-lg',
    body: `<form id="invoice-form" autocomplete="off">
      ${clinicPicker}
      <div class="field-row">
        <div class="field" style="grid-column: span 2"><label>Title / reference</label><input name="title" value="${attr(inv.title)}" placeholder="e.g. Toner + on-site swap"></div>
        <div class="field"><label>Issue date</label><input name="issue_date" type="date" value="${attr(inv.issue_date)}"></div>
        <div class="field"><label>Due date</label><input name="due_date" type="date" value="${attr(inv.due_date)}"></div>
      </div>
      <div class="field"><label>Ticket link</label><input name="ticket_url" value="${attr(inv.ticket_url)}" placeholder="https://tickets…"></div>
      <table class="table qline-table" id="inv-lines">
        <thead><tr><th>Description</th><th style="width:80px">Qty</th><th style="width:110px">Unit $</th><th class="right" style="width:100px">Total</th><th></th></tr></thead>
        <tbody></tbody>
      </table>
      <div class="flex mt">
        <select id="inv-add-item"><option value="">+ Add from inventory…</option>${items.map(i => `<option value="${i.id}">${esc(i.name)}${i.quantity != null ? ` · ${i.quantity} on hand` : ''}</option>`).join('')}</select>
        <button type="button" class="btn btn-sm" id="inv-add-custom">+ Custom line</button>
      </div>
      <div class="field-row mt">
        <div class="field"><label>Discount %</label><input name="discount_pct" type="number" min="0" max="100" step="0.5" value="${attr(inv.discount_pct ?? 0)}"></div>
        <div class="field"><label>Tax %</label><input name="tax_pct" type="number" min="0" step="0.1" value="${attr(inv.tax_pct ?? 0)}"></div>
        <div class="field" style="grid-column: span 2"><label>&nbsp;</label><div class="inv-totals" id="inv-totals"></div></div>
      </div>
      <div class="field"><label>Notes</label><textarea name="notes" rows="2" placeholder="Payment terms, PO number, etc.">${esc(inv.notes)}</textarea></div>
    </form>`,
    footer: `<button class="btn" data-act="cancel">Cancel</button><button class="btn btn-primary" data-act="save">${isEdit ? 'Save invoice' : 'Create invoice'}</button>`,
  });
  const form = modal.body.querySelector('#invoice-form');
  const tbody = form.querySelector('#inv-lines tbody');

  const rowHtml = (l) => `<tr>
    <td><input class="wide" data-f="description" value="${attr(l.description)}" placeholder="Description">${l.item_id ? '<span class="unit">from inventory</span>' : ''}</td>
    <td><input type="number" min="0" step="1" data-f="quantity" value="${attr(l.quantity)}"></td>
    <td><input type="number" min="0" step="0.01" data-f="unit_price" value="${attr(l.unit_price)}"></td>
    <td class="right money" data-total>$0</td>
    <td><button type="button" class="btn btn-link btn-sm" data-del>✕</button></td></tr>`;

  const rowData = [];
  function renderRows() {
    tbody.innerHTML = '';
    rowData.length = 0;
    lines.forEach(l => { rowData.push(l); tbody.insertAdjacentHTML('beforeend', rowHtml(l)); });
    wireRows();
    recalc();
  }
  function wireRows() {
    [...tbody.children].forEach((tr, i) => {
      tr.querySelectorAll('[data-f]').forEach(inp => {
        inp.oninput = () => {
          const f = inp.dataset.f;
          lines[i][f] = f === 'description' ? inp.value : (inp.value === '' ? 0 : Number(inp.value));
          recalc();
        };
      });
      tr.querySelector('[data-del]').onclick = () => { lines.splice(i, 1); if (!lines.length) lines.push({ item_id: null, description: '', quantity: 1, unit_price: 0 }); renderRows(); };
    });
  }
  function recalc() {
    let subtotal = 0;
    [...tbody.children].forEach((tr, i) => {
      const t = (lines[i].quantity || 0) * (lines[i].unit_price || 0);
      subtotal += t;
      tr.querySelector('[data-total]').textContent = fmtMoney(t) || '$0';
    });
    const disc = subtotal * (Number(form.elements.discount_pct.value) || 0) / 100;
    const taxed = subtotal - disc;
    const tax = taxed * (Number(form.elements.tax_pct.value) || 0) / 100;
    form.querySelector('#inv-totals').innerHTML =
      `<div>Subtotal <strong>${fmtMoney(subtotal) || '$0'}</strong></div>${disc ? `<div>Discount −${fmtMoney(disc)}</div>` : ''}<div>Tax ${fmtMoney(tax) || '$0'}</div><div class="grand">Total <strong>${fmtMoney(taxed + tax) || '$0'}</strong></div>`;
  }
  renderRows();
  form.elements.discount_pct.oninput = recalc;
  form.elements.tax_pct.oninput = recalc;
  form.querySelector('#inv-add-custom').onclick = () => { lines.push({ item_id: null, description: '', quantity: 1, unit_price: 0 }); renderRows(); };
  form.querySelector('#inv-add-item').onchange = (e) => {
    const it = items.find(i => String(i.id) === e.target.value);
    if (!it) return;
    lines.push({ item_id: it.id, description: it.name, quantity: 1, unit_price: it.unit_price || 0 });
    e.target.value = '';
    renderRows();
  };

  modal.root.querySelector('[data-act=cancel]').onclick = () => modal.close();
  modal.root.querySelector('[data-act=save]').onclick = async () => {
    const cid = clinicId || (invoice && invoice.clinic_id) || Number(form.querySelector('#inv-clinic')?.value);
    if (!cid) { showFormError(form, 'Pick a client.'); return; }
    const payloadLines = lines.filter(l => (l.description || '').trim()).map(l => ({ item_id: l.item_id || null, description: l.description.trim(), quantity: Number(l.quantity) || 0, unit_price: Number(l.unit_price) || 0 }));
    if (!payloadLines.length) { showFormError(form, 'Add at least one line.'); return; }
    const body = {
      title: form.elements.title.value, issue_date: form.elements.issue_date.value, due_date: form.elements.due_date.value,
      ticket_url: form.elements.ticket_url.value, notes: form.elements.notes.value,
      tax_pct: Number(form.elements.tax_pct.value) || 0, discount_pct: Number(form.elements.discount_pct.value) || 0,
      lines: payloadLines,
    };
    try {
      const saved = isEdit ? await invoices.update(invoice.id, body) : await invoices.create(cid, body);
      toast(isEdit ? 'Invoice saved' : 'Invoice created', 'success');
      modal.close();
      onSaved && onSaved(saved);
    } catch (e) { showFormError(form, e.message); }
  };
  form.addEventListener('submit', (e) => e.preventDefault());
  return modal;
}
