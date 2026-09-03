// Invoice document: print-ready, with status, CSV, edit and delete.
import { invoices } from '../api.js';
import { esc, attr, fmtMoney, fmtDateOnly, toast, confirmDialog, navigate, setTitle, options } from '../ui.js';
import { openInvoiceForm } from '../billing-forms.js';

export async function render(container, params, routeParams) {
  let inv;
  try { inv = await invoices.get(Number(routeParams.id)); }
  catch { container.innerHTML = '<div class="card empty">Invoice not found. <a href="#/billing?tab=invoices">All invoices</a></div>'; return; }
  setTitle(`${inv.number} · ${inv.clinic_name}`);
  const reload = () => render(container, params, routeParams);
  const overdue = inv.due_date && inv.due_date < new Date().toISOString().slice(0, 10) && inv.status === 'sent';
  const contactName = [inv.contact_first_name, inv.contact_last_name].filter(Boolean).join(' ');

  container.innerHTML = `
    <div class="page-header no-print">
      <h1>${esc(inv.number)}</h1>
      <span class="status-stamp stamp-${esc(inv.status)}">${esc(inv.status_label)}</span>
      ${overdue ? '<span class="badge badge-red">Overdue</span>' : ''}
      <div class="actions">
        <select id="inv-status" title="Invoice status">${options({ draft: 'Draft', sent: 'Sent', paid: 'Paid', void: 'Void' }, inv.status)}</select>
        ${inv.status === 'draft' ? '<button class="btn" id="edit">Edit</button>' : ''}
        <a class="btn" href="${invoices.csvUrl(inv.id)}" download>Download CSV</a>
        <button class="btn btn-primary" id="print">⬇ Download PDF</button>
        <button class="btn btn-danger" id="del">Delete</button>
      </div>
    </div>
    <p class="muted small no-print">Only <strong>draft</strong> invoices can be edited. Marking an invoice <strong>Sent</strong> or <strong>Paid</strong> deducts any inventory items from stock; <strong>Void</strong> restores them. “Download PDF” opens your browser's print dialog — choose <strong>Save as PDF</strong>.</p>

    <div class="quote-doc">
      <div class="doc-head">
        <div>
          <h1>${esc(inv.company.company_name || 'ChinookIT')}</h1>
          <div class="company">${esc(inv.company.company_contact || '')}</div>
        </div>
        <div class="meta">
          <div><strong>Invoice ${esc(inv.number)}</strong></div>
          <div>Issued ${esc(fmtDateOnly(inv.issue_date || (inv.created_at || '').slice(0, 10)))}</div>
          ${inv.due_date ? `<div>Due ${esc(fmtDateOnly(inv.due_date))}</div>` : ''}
          <div class="mt"><span class="status-stamp stamp-${esc(inv.status)}">${esc(inv.status_label)}</span></div>
        </div>
      </div>
      <div class="parties">
        <div><div class="label">Bill to</div>
          <div><strong>${esc(inv.clinic_name)}</strong>${inv.clinic_shorthand ? ` (${esc(inv.clinic_shorthand)})` : ''}</div>
          <div>${esc(inv.clinic_address || '')}</div>
          ${contactName ? `<div>Attn: ${esc(contactName)}${inv.contact_email ? ` · ${esc(inv.contact_email)}` : ''}</div>` : ''}</div>
        <div><div class="label">${esc(inv.title || 'Invoice')}</div>
          ${inv.ticket_url ? `<div>Ticket: <a href="${attr(inv.ticket_url)}" target="_blank" rel="noopener">${esc(inv.ticket_url)}</a></div>` : ''}</div>
      </div>

      <table>
        <thead><tr><th>Description</th><th class="num">Qty</th><th class="num">Unit</th><th class="num">Amount</th></tr></thead>
        <tbody>
          ${inv.lines.map(l => `<tr><td>${esc(l.description)}${l.item_id ? '<div class="desc">from inventory</div>' : ''}</td>
            <td class="num">${l.quantity}</td><td class="num">${fmtMoney(l.unit_price)}</td><td class="num">${fmtMoney(l.line_total)}</td></tr>`).join('')}
          ${inv.lines.length ? '' : '<tr><td colspan="4" class="desc">No line items.</td></tr>'}
        </tbody>
      </table>

      <div class="totals">
        <div class="row"><span>Subtotal</span><span>${fmtMoney(inv.subtotal)}</span></div>
        ${inv.discount_pct ? `<div class="row"><span>Discount (${inv.discount_pct}%)</span><span>−${fmtMoney(inv.subtotal * inv.discount_pct / 100)}</span></div>` : ''}
        <div class="row"><span>${inv.tax_pct ? `Tax (${inv.tax_pct}%)` : 'Tax'}</span><span>${fmtMoney(inv.tax)}</span></div>
        <div class="row big"><span>Total</span><span>${fmtMoney(inv.total)}</span></div>
      </div>

      ${inv.notes ? `<div class="terms">${esc(inv.notes)}</div>` : ''}
    </div>`;

  container.querySelector('#print').onclick = () => window.print();
  const editBtn = container.querySelector('#edit');
  if (editBtn) editBtn.onclick = () => openInvoiceForm({ invoice: inv, onSaved: reload });
  container.querySelector('#inv-status').onchange = async (e) => {
    try { await invoices.setStatus(inv.id, e.target.value); toast(`Marked ${e.target.value}`, 'success'); reload(); }
    catch (err) { toast(err.message, 'error'); }
  };
  container.querySelector('#del').onclick = async () => {
    if (!(await confirmDialog(`Delete invoice ${inv.number}? Any stock it deducted is restored.`))) return;
    await invoices.remove(inv.id); toast('Invoice deleted'); navigate(`#/clinics/${inv.clinic_id}`);
  };
}
