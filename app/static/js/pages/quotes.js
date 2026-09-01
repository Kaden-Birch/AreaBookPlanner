// All quotes across clinics.
import { quotes } from '../api.js';
import { esc, fmtMoney, fmtDate, fmtDateOnly, options, setTitle, navigate } from '../ui.js';

let state = { status: '' };

export async function render(container) {
  setTitle('Quotes');
  const list = await quotes.list({ status: state.status });
  const open = list.filter(q => ['draft', 'sent'].includes(q.status));
  const monthlyOpen = open.reduce((s, q) => s + q.monthly_total, 0);
  const accepted = list.filter(q => q.status === 'accepted');
  container.innerHTML = `
    <div class="page-header"><h1>Quotes</h1><span class="muted">${list.length} quote${list.length === 1 ? '' : 's'}</span>
      <div class="actions"><select id="status">${options({ '': 'All statuses', draft: 'Draft', sent: 'Sent', accepted: 'Accepted', declined: 'Declined', expired: 'Expired' }, state.status)}</select><a class="btn" href="#/settings">Price book</a></div></div>
    <div class="grid-3 mb">
      <div class="card stat"><div class="value">${open.length}</div><div class="label">Open quotes</div><div class="sub money">${fmtMoney(monthlyOpen)} / month proposed</div></div>
      <div class="card stat"><div class="value">${accepted.length}</div><div class="label">Accepted</div><div class="sub money">${fmtMoney(accepted.reduce((s, q) => s + q.monthly_total, 0))} / month</div></div>
      <div class="card stat"><div class="value">${list.length ? Math.round(accepted.length / Math.max(1, list.filter(q => q.status !== 'draft').length) * 100) : 0}%</div><div class="label">Win rate</div><div class="sub">of non-draft quotes</div></div>
    </div>
    ${list.length ? `<div class="table-wrap"><table class="table">
      <thead><tr><th>Quote</th><th>Clinic</th><th>Title</th><th>Basis</th><th class="right">Monthly</th><th class="right">One-time</th><th>Status</th><th>Created</th><th>Valid until</th></tr></thead>
      <tbody>${list.map(q => `<tr class="clickable" data-id="${q.id}">
        <td><strong>${esc(q.number)}</strong></td><td><a href="#/clinics/${q.clinic_id}">${esc(q.clinic_name)}</a></td><td>${esc(q.title)}</td>
        <td>${q.pricing_mode === 'per_user' ? `${q.user_count} users` : `${q.device_count} devices`}</td>
        <td class="right money">${fmtMoney(q.monthly_total)}</td><td class="right money">${q.onetime_total ? fmtMoney(q.onetime_total) : ''}</td>
        <td><span class="status-stamp stamp-${esc(q.status)}">${esc(q.status_label)}</span></td><td>${esc(fmtDate(q.created_at))}</td><td>${q.valid_until ? esc(fmtDateOnly(q.valid_until)) : ''}</td></tr>`).join('')}</tbody></table></div>`
      : '<div class="card empty">No quotes yet. Open a clinic, map its equipment, and click “Generate quote”.</div>'}`;
  container.querySelector('#status').onchange = (e) => { state.status = e.target.value; render(container); };
  container.querySelectorAll('tr.clickable').forEach(tr => { tr.onclick = (e) => { if (e.target.tagName === 'A') return; navigate(`#/quotes/${tr.dataset.id}`); }; });
}
