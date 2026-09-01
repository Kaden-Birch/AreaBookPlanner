// Quote document: print-ready, with status, download and pipeline actions.
import { quotes, pricebook } from '../api.js';
import { esc, attr, fmtMoney, fmtDate, fmtDateOnly, fmtDateTime, toast, confirmDialog, navigate, setTitle, options } from '../ui.js';

export async function render(container, params, routeParams) {
  const q = await quotes.get(Number(routeParams.id));
  const pb = await pricebook.get();
  setTitle(`${q.number} · ${q.clinic_name}`);
  const t = q.totals;
  const included = q.lines.filter(l => l.included);
  const monthlyCats = ['plan', 'infra', 'backup', 'emr', 'extras'];
  const byCat = {};
  included.forEach(l => { (byCat[l.category] ||= []).push(l); });
  const rates = included.filter(l => l.unit === 'per_hour');
  const onetime = included.filter(l => l.unit === 'one_time');
  const plan = included.find(l => l.category === 'plan');
  const expired = q.valid_until && q.valid_until < new Date().toISOString().slice(0, 10) && ['draft', 'sent'].includes(q.status);

  container.innerHTML = `
    <div class="page-header no-print">
      <h1>${esc(q.number)}</h1>
      <span class="status-stamp stamp-${esc(q.status)}">${esc(q.status_label)}</span>
      ${expired ? '<span class="badge badge-overdue">Past valid-until date</span>' : ''}
      <div class="actions">
        <select id="q-status" title="Quote status">${options({ draft: 'Draft', sent: 'Sent to customer', accepted: 'Accepted', declined: 'Declined', expired: 'Expired' }, q.status)}</select>
        <button class="btn" id="apply-deal" title="Set the clinic's deal value to this quote's annual total">Apply to deal</button>
        <a class="btn" href="#/quotes/${q.id}/edit">Edit</a>
        <button class="btn" id="dup">Duplicate</button>
        <a class="btn" href="${quotes.csvUrl(q.id)}" download>Download CSV</a>
        <button class="btn btn-primary" id="print">⬇ Download PDF</button>
        <button class="btn btn-danger" id="del">Delete</button>
      </div>
    </div>
    <p class="muted small no-print">“Download PDF” opens your browser's print dialog — choose <strong>Save as PDF</strong> as the destination.</p>

    <div class="quote-doc">
      <div class="doc-head">
        <div>
          <h1>${esc(pb.company.name)}</h1>
          <div class="company">${esc(pb.company.contact || '')}</div>
        </div>
        <div class="meta">
          <div><strong>Quote ${esc(q.number)}</strong></div>
          <div>${esc(fmtDateOnly((q.created_at || '').slice(0, 10)))}</div>
          ${q.valid_until ? `<div>Valid until ${esc(fmtDateOnly(q.valid_until))}</div>` : ''}
          ${q.prepared_by ? `<div>Prepared by ${esc(q.prepared_by)}</div>` : ''}
          <div class="mt"><span class="status-stamp stamp-${esc(q.status)}">${esc(q.status_label)}</span></div>
        </div>
      </div>
      <div class="parties">
        <div><div class="label">Prepared for</div>
          <div><strong>${esc(q.clinic_name)}</strong>${q.clinic_shorthand ? ` (${esc(q.clinic_shorthand)})` : ''}</div>
          <div>${esc([q.clinic_address, q.clinic_city, q.clinic_province, q.clinic_postal_code].filter(Boolean).join(', '))}</div>
          ${q.contact_name ? `<div>Attn: ${esc(q.contact_name)}${q.contact_title ? `, ${esc(q.contact_title)}` : ''}${q.contact_email ? ` · ${esc(q.contact_email)}` : ''}</div>` : ''}</div>
        <div><div class="label">${esc(q.title)}</div>
          <div>Priced <strong>${q.pricing_mode === 'per_user' ? `per user · ${q.user_count} users` : `per managed device · ${q.device_count} devices`}</strong>${q.user_count && q.pricing_mode === 'per_device' ? ` · ${q.user_count} users supported` : ''}</div>
          ${plan ? `<div>Plan: <strong>${esc(plan.label)}</strong></div>` : ''}
          ${q.counts && Object.keys(q.counts).length ? `<div class="desc">Network: ${q.counts.firewalls || 0} firewall, ${q.counts.switches || 0} switch, ${q.counts.aps || 0} AP, ${q.counts.servers_physical || 0} server, ${q.counts.vms || 0} VM, ${q.counts.workstations || 0} workstation, ${q.counts.laptops || 0} laptop, ${q.counts.phones || 0} phone, ${q.counts.printers || 0} printer · ${q.counts.sites || 1} site${(q.counts.sites || 1) === 1 ? '' : 's'}</div>` : ''}</div>
      </div>

      <table>
        <thead><tr><th>Monthly services</th><th class="num">Qty</th><th class="num">Unit</th><th class="num">Monthly</th></tr></thead>
        <tbody>
          ${monthlyCats.filter(c => (byCat[c] || []).some(l => l.unit !== 'per_hour' && l.unit !== 'one_time')).map(c => `
            <tr class="cat"><td colspan="4">${esc(q.categories[c])}</td></tr>
            ${byCat[c].filter(l => l.unit !== 'per_hour' && l.unit !== 'one_time').map(l => `
              <tr><td>${esc(l.label)}${l.description ? `<div class="desc">${esc(l.description)}</div>` : ''}${l.note ? `<div class="desc">${esc(l.note)}</div>` : ''}</td>
                <td class="num">${l.qty}</td><td class="num">${fmtMoney(l.unit_price)} <span class="desc">${esc(l.unit_label)}</span></td><td class="num">${fmtMoney(l.total)}</td></tr>`).join('')}`).join('')}
          ${rates.filter(l => l.qty > 0).length ? `<tr class="cat"><td colspan="4">Estimated hourly work</td></tr>${rates.filter(l => l.qty > 0).map(l => `<tr><td>${esc(l.label)}</td><td class="num">${l.qty} h</td><td class="num">${fmtMoney(l.unit_price)}/h</td><td class="num">${fmtMoney(l.total)}</td></tr>`).join('')}` : ''}
        </tbody>
      </table>

      <div class="totals">
        <div class="row"><span>Monthly subtotal</span><span>${fmtMoney(t.monthly_subtotal)}</span></div>
        ${t.discount ? `<div class="row"><span>Discount (${q.discount_pct}%)</span><span>−${fmtMoney(t.discount)}</span></div>` : ''}
        <div class="row"><span>${q.tax_pct ? `GST (${q.tax_pct}%)` : 'Tax'}</span><span>${fmtMoney(t.monthly_tax)}</span></div>
        <div class="row big"><span>Per month</span><span>${fmtMoney(t.monthly_total)}</span></div>
        <div class="row annual"><span>Annual equivalent</span><span>${fmtMoney(t.annual_total)}</span></div>
      </div>

      ${onetime.length ? `<table><thead><tr><th>One-time</th><th class="num">Qty</th><th class="num">Unit</th><th class="num">Total</th></tr></thead>
        <tbody>${onetime.map(l => `<tr><td>${esc(l.label)}</td><td class="num">${l.qty}</td><td class="num">${fmtMoney(l.unit_price)}</td><td class="num">${fmtMoney(l.total)}</td></tr>`).join('')}
        <tr><td colspan="3" class="num"><strong>One-time total incl. tax</strong></td><td class="num"><strong>${fmtMoney(t.onetime_total)}</strong></td></tr></tbody></table>` : ''}

      ${rates.length ? `<table><thead><tr><th>Rate card (as needed)</th><th class="num">Rate</th></tr></thead>
        <tbody>${rates.map(l => `<tr><td>${esc(l.label)}</td><td class="num">${fmtMoney(l.unit_price)} / hour</td></tr>`).join('')}</tbody></table>` : ''}

      ${q.notes ? `<div class="mt"><div class="label muted small" style="text-transform:uppercase;letter-spacing:.05em">Notes</div><div style="white-space:pre-line">${esc(q.notes)}</div></div>` : ''}
      ${q.terms ? `<div class="terms">${esc(q.terms)}</div>` : ''}
    </div>`;

  container.querySelector('#print').onclick = () => window.print();
  container.querySelector('#q-status').onchange = async (e) => {
    try { await quotes.setStatus(q.id, e.target.value); toast(`Marked ${e.target.value}`, 'success'); render(container, params, routeParams); }
    catch (err) { toast(err.message, 'error'); }
    if (e.target.value === 'accepted' && await confirmDialog('Quote accepted 🎉 — set the clinic deal value to this quote and mark it Won?', { title: 'Accepted', okLabel: 'Yes, mark Won', danger: false })) {
      await quotes.applyToDeal(q.id);
      navigate(`#/clinics/${q.clinic_id}`);
      const { openOutcomeDialog } = await import('../forms.js');
      const { clinics } = await import('../api.js');
      openOutcomeDialog({ clinic: await clinics.get(q.clinic_id), stage: 'won', onSaved: () => navigate(`#/clinics/${q.clinic_id}`) });
    }
  };
  container.querySelector('#apply-deal').onclick = async () => { const r = await quotes.applyToDeal(q.id); toast(`Deal value set to ${fmtMoney(r.deal_value)} / year`, 'success'); };
  container.querySelector('#dup').onclick = async () => { const d = await quotes.duplicate(q.id); toast('Quote duplicated'); navigate(`#/quotes/${d.id}/edit`); };
  container.querySelector('#del').onclick = async () => { if (!(await confirmDialog(`Delete quote ${q.number}?`))) return; await quotes.remove(q.id); toast('Quote deleted'); navigate(`#/clinics/${q.clinic_id}`); };
}
