// Clients page: recurring revenue, contract renewals, churn and onboarding health.
import { revenue as revenueApi, getMeta } from '../api.js';
import { esc, dot, badge, fmtMoney, fmtDateOnly, setTitle, navigate } from '../ui.js';

let data = null;

export async function render(container) {
  setTitle('Clients');
  container.classList.add('wide');
  await getMeta();
  container.innerHTML = '<div class="loading">Loading…</div>';
  data = await revenueApi();
  const s = data.summary;

  container.innerHTML = `
    <div class="page-header">
      <h1>Clients</h1>
      <span class="muted">${s.active_clients} active · ${fmtMoney(s.mrr) || '$0'} MRR</span>
      <div class="actions"><a class="btn" href="/api/export/clinics.csv" download>Export CSV</a></div>
    </div>

    <div class="grid-4">
      <div class="card stat"><div class="value money">${fmtMoney(s.mrr) || '$0'}</div><div class="label">Monthly recurring revenue</div><div class="sub">${fmtMoney(s.arr) || '$0'} ARR</div></div>
      <div class="card stat"><div class="value">${s.active_clients}</div><div class="label">Active clients</div><div class="sub">${fmtMoney(s.avg_mrr) || '$0'} avg / client</div></div>
      <div class="card stat"><div class="value">${s.new_clients_ytd}</div><div class="label">New clients this year</div><div class="sub">${s.renewals_due} renewal${s.renewals_due === 1 ? '' : 's'} due</div></div>
      <div class="card stat ${s.churned_ytd ? 'stat-warn' : ''}"><div class="value">${s.churned_ytd}</div><div class="label">Churned this year</div><div class="sub">${fmtMoney(s.churned_mrr_ytd) || '$0'} lost MRR</div></div>
    </div>

    <div class="card mt">
      <div class="card-header"><h3>MRR movement</h3><span class="muted small">New vs. churned recurring revenue by month</span></div>
      ${movementChart(data.movement)}
    </div>

    <div class="grid-2 mt">
      <div class="card">
        <div class="card-header"><h3>Renewals</h3><span class="muted small">Contracts ending soon or overdue</span></div>
        ${renewalList(data.renewals.filter(r => r.renewal_due || r.renewal_overdue))}
      </div>
      <div class="card">
        <div class="card-header"><h3>Missing contract info</h3><span class="muted small">Active clients without an MRR or renewal date</span></div>
        ${data.no_contract.length ? `<ul class="list">${data.no_contract.map(c => `
          <li><div class="body"><div class="title">${dot(c.color)}<a href="#/clinics/${c.id}">${esc(c.name)}</a></div>
            <div class="muted small">${!c.mrr ? 'No MRR set' : ''}${!c.mrr && !c.contract_end ? ' · ' : ''}${!c.contract_end ? 'No contract end date' : ''}</div></div>
          <div class="actions"><a class="btn btn-sm" href="#/clinics/${c.id}">Fix</a></div></li>`).join('')}</ul>`
          : '<p class="muted">Every client has an MRR and a renewal date. 🎉</p>'}
      </div>
    </div>

    <div class="card mt">
      <div class="card-header"><h3>All clients</h3><span class="muted small">${data.clients.length} active, by MRR</span></div>
      <div class="table-wrap">${clientTable(data.clients)}</div>
    </div>`;

  container.querySelectorAll('tr.clickable').forEach(tr => { tr.onclick = () => navigate(`#/clinics/${tr.dataset.id}`); });
}

export function destroy(container) { container.classList.remove('wide'); }

function movementChart(movement) {
  if (!movement || !movement.length) return '<p class="muted">No revenue movement yet.</p>';
  const max = Math.max(1, ...movement.map(m => Math.max(m.added, m.churned)));
  const H = 90;
  const bars = movement.map(m => {
    const up = Math.round((m.added / max) * H);
    const down = Math.round((m.churned / max) * H);
    const label = m.month.slice(5);
    const title = `${m.month}: +${fmtMoney(m.added) || '$0'} / -${fmtMoney(m.churned) || '$0'} = ${fmtMoney(m.net) || '$0'} net`;
    return `<div class="mv-col" title="${esc(title)}">
      <div class="mv-bars">
        <div class="mv-up" style="height:${up}px"></div>
        <div class="mv-down" style="height:${down}px"></div>
      </div>
      <div class="mv-label">${esc(label)}</div>
    </div>`;
  }).join('');
  return `<div class="mv-chart" style="--mv-h:${H}px">${bars}</div>
    <div class="mv-legend"><span><i class="sw" style="background:var(--c-green)"></i>New MRR</span><span><i class="sw" style="background:var(--c-red)"></i>Churned MRR</span></div>`;
}

function renewalBadge(r) {
  if (r.renewal_overdue) return badge('Expired', 'badge-red');
  if (r.days_to_renewal != null && r.days_to_renewal <= 30) return badge(`${r.days_to_renewal}d`, 'badge-high');
  if (r.days_to_renewal != null) return badge(`${r.days_to_renewal}d`, 'badge-yellow');
  return '';
}

function renewalList(renewals) {
  if (!renewals.length) return '<p class="muted">No renewals due in the next while. Set a contract end date on a client to track it.</p>';
  return `<ul class="list">${renewals.map(r => `
    <li><div class="body"><div class="title"><a href="#/clinics/${r.id}">${esc(r.name)}</a> ${renewalBadge(r)} ${r.auto_renew ? badge('Auto-renew', 'badge-grey') : ''}</div>
      <div class="muted small">${r.contract_end ? `Ends ${esc(fmtDateOnly(r.contract_end))}` : ''}${r.mrr ? ` · ${fmtMoney(r.mrr)}/mo` : ''}</div></div></li>`).join('')}</ul>`;
}

function clientTable(clients) {
  if (!clients.length) return '<div class="card empty">No active clients yet. Win a deal and it shows up here.</div>';
  return `
    <table class="table">
      <thead><tr><th>Client</th><th>MRR</th><th>ARR</th><th>Contract ends</th><th>Term</th><th>Renewal</th></tr></thead>
      <tbody>${clients.map(c => `
        <tr class="clickable" data-id="${c.id}">
          <td>${dot(c.color)}<strong>${esc(c.name)}</strong></td>
          <td class="money">${c.mrr ? fmtMoney(c.mrr) : '<span class="muted">—</span>'}</td>
          <td class="money">${c.arr ? fmtMoney(c.arr) : ''}</td>
          <td class="nowrap">${c.contract_end ? esc(fmtDateOnly(c.contract_end)) : '<span class="muted">—</span>'}</td>
          <td>${c.contract_term_months ? `${c.contract_term_months} mo` : ''}</td>
          <td class="nowrap">${c.contract_end ? renewalBadge(c) : ''} ${c.auto_renew ? badge('Auto', 'badge-grey') : ''}</td>
        </tr>`).join('')}</tbody>
    </table>`;
}
