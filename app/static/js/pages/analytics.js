// Analytics: visits over time, conversion, time in stage, activity by rep.
// Charts are inline SVG (no library): thin rounded bars, hairline grid, hover tooltips, table view.
import { api } from '../api.js';
import { esc, setTitle, fmtMoney } from '../ui.js';

export async function render(container) {
  setTitle('Analytics');
  const a = await api.get('/api/analytics');
  const t = a.totals;
  const delta = t.visits_this_month - t.visits_last_month;
  container.innerHTML = `
    <div class="page-header"><h1>Analytics</h1><span class="muted">Last 12 weeks / 12 months</span></div>
    <div class="grid-4 viz-root">
      <div class="card stat"><div class="value">${t.visits_this_month}</div><div class="label">Visits this month</div>
        <div class="sub ${delta > 0 ? 'delta-up' : delta < 0 ? 'delta-down' : ''}">${delta === 0 ? 'Same as' : (delta > 0 ? '▲ ' : '▼ ') + Math.abs(delta) + ' vs'} last month (${t.visits_last_month})</div></div>
      <div class="card stat"><div class="value">${a.conversion.rate == null ? '—' : a.conversion.rate + '%'}</div><div class="label">Conversion rate</div><div class="sub">${a.conversion.won} won · ${a.conversion.lost} lost · ${a.conversion.open} open</div></div>
      <div class="card stat"><div class="value">${t.clients}</div><div class="label">Current clients</div><div class="sub">of ${t.clinics_total} clinics</div></div>
      <div class="card stat"><div class="value">${t.visits_all_time}</div><div class="label">Visits all time</div><div class="sub">In-person appointments</div></div>
    </div>

    <div class="grid-2 mt viz-root">
      ${chartCard('visits-week', 'Visits per week', 'In-person visits, last 12 weeks', a.visits_by_week.map(x => ({ label: weekLabel(x.week), value: x.count })), ['Visits'])}
      ${chartCard('visits-month', 'Visits per month', 'In-person visits, last 12 months', a.visits_by_month.map(x => ({ label: monthLabel(x.month), value: x.count })), ['Visits'])}
      ${chartCard('outcomes', 'Deals won vs lost', 'By outcome month', a.outcomes_by_month.map(x => ({ label: monthLabel(x.month), value: x.won, value2: x.lost })), ['Won', 'Lost'])}
      ${chartCard('new-clinics', 'New clinics added', 'Prospects entered per month', a.new_clinics_by_month.map(x => ({ label: monthLabel(x.month), value: x.count })), ['Clinics'])}
    </div>

    <div class="grid-2 mt viz-root">
      <div class="card">
        <div class="card-header"><h3>Average time in stage</h3><span class="muted small">Days spent before moving on (from stage history)</span></div>
        ${hbars(a.time_in_stage.map(s => ({ label: s.label, value: s.avg_days, extra: s.n ? `${s.n} move${s.n === 1 ? '' : 's'}` : 'no data' })), 'days')}
      </div>
      <div class="card">
        <div class="card-header"><h3>Pipeline funnel</h3><span class="muted small">Clinics currently in each stage</span></div>
        ${hbars(a.funnel.map(s => ({ label: s.label, value: s.count })), '')}
      </div>
    </div>

    <div class="card mt">
      <div class="card-header"><h3>Activity by rep</h3><span class="muted small">Set your name under Settings so activity is attributed to you</span></div>
      ${a.by_rep.length ? `<div class="table-wrap"><table class="table">
        <thead><tr><th>Rep</th><th class="right">Visits</th><th class="right">Calls</th><th class="right">All appointments</th><th class="right">Notes</th><th class="right">Tasks done</th><th class="right">Total</th></tr></thead>
        <tbody>${a.by_rep.map(r => `<tr><td><strong>${esc(r.rep)}</strong></td><td class="right money">${r.visits}</td><td class="right money">${r.calls}</td><td class="right money">${r.appointments}</td><td class="right money">${r.notes}</td><td class="right money">${r.tasks_done}</td><td class="right money"><strong>${r.total}</strong></td></tr>`).join('')}</tbody>
      </table></div>` : '<p class="muted">No activity recorded yet.</p>'}
    </div>`;

  container.querySelectorAll('[data-toggle-table]').forEach(b => {
    b.onclick = () => {
      const card = b.closest('.card');
      card.querySelector('.viz-plot').classList.toggle('hidden');
      card.querySelector('.viz-table').classList.toggle('hidden');
      b.textContent = card.querySelector('.viz-plot').classList.contains('hidden') ? 'Chart' : 'Table';
    };
  });
  wireTooltips(container);
}

function weekLabel(iso) { const [y, m, d] = iso.split('-').map(Number); return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }); }
function monthLabel(ym) { const [y, m] = ym.split('-').map(Number); return new Date(y, m - 1, 1).toLocaleDateString(undefined, { month: 'short', year: '2-digit' }); }

// Column chart. rows: [{label, value, value2?}], series: names (1 or 2).
function chartCard(id, title, subtitle, rows, series) {
  const W = 560, H = 220, padL = 32, padR = 8, padT = 12, padB = 28;
  const two = series.length === 2;
  const max = Math.max(1, ...rows.map(r => Math.max(r.value || 0, r.value2 || 0)));
  const step = niceStep(max);
  const top = Math.ceil(max / step) * step;
  const innerW = W - padL - padR, innerH = H - padT - padB;
  const band = innerW / rows.length;
  const barW = Math.min(24, (band - 6) / (two ? 2 : 1) - (two ? 1 : 0));
  const y = v => padT + innerH - (v / top) * innerH;
  let grid = '';
  for (let v = 0; v <= top; v += step) {
    grid += `<line x1="${padL}" x2="${W - padR}" y1="${y(v)}" y2="${y(v)}" class="viz-grid"/><text x="${padL - 6}" y="${y(v) + 4}" class="viz-tick" text-anchor="end">${v}</text>`;
  }
  let bars = '';
  rows.forEach((r, i) => {
    const cx = padL + band * i + band / 2;
    const draw = (v, cls, offset, name) => {
      const h = Math.max(0, (v / top) * innerH);
      const x = cx - (two ? barW + 1 : barW / 2) + offset;
      const yy = y(v);
      const rad = Math.min(4, h);
      const d = h <= 0 ? '' : `M${x},${yy + innerH - (yy - padT) - 0} ` ;
      // rounded top, square bottom
      const path = h <= 0 ? '' : `<path class="viz-bar ${cls}" d="M${x},${padT + innerH} V${yy + rad} Q${x},${yy} ${x + rad},${yy} H${x + barW - rad} Q${x + barW},${yy} ${x + barW},${yy + rad} V${padT + innerH} Z"/>`;
      return `<g class="viz-hit" data-tip="${esc(r.label)}: ${v} ${esc(name)}"><rect x="${x - 2}" y="${padT}" width="${barW + 4}" height="${innerH}" fill="transparent"/>${path}</g>`;
    };
    bars += draw(r.value || 0, 'viz-s1', 0, series[0]);
    if (two) bars += draw(r.value2 || 0, 'viz-s2', barW + 2, series[1]);
    const showLabel = rows.length <= 12 || i % 2 === 0;
    if (showLabel) bars += `<text x="${cx}" y="${H - 8}" class="viz-tick" text-anchor="middle">${esc(r.label)}</text>`;
  });
  const legend = two ? `<div class="viz-legend"><span><i class="viz-swatch viz-s1"></i>${esc(series[0])}</span><span><i class="viz-swatch viz-s2"></i>${esc(series[1])}</span></div>` : '';
  const total = rows.reduce((s, r) => s + (r.value || 0), 0);
  const total2 = rows.reduce((s, r) => s + (r.value2 || 0), 0);
  return `
    <div class="card" id="${id}">
      <div class="card-header"><div><h3>${esc(title)}</h3><span class="muted small">${esc(subtitle)} · total ${total}${two ? ` / ${total2}` : ''}</span></div>
        <div class="actions"><button class="btn btn-sm" data-toggle-table>Table</button></div></div>
      ${legend}
      <div class="viz-plot"><svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="${esc(title)}"><line x1="${padL}" x2="${W - padR}" y1="${y(0)}" y2="${y(0)}" class="viz-axis"/>${grid}${bars}</svg></div>
      <div class="viz-table hidden"><table class="table"><thead><tr><th>Period</th>${series.map(s => `<th class="right">${esc(s)}</th>`).join('')}</tr></thead>
        <tbody>${rows.map(r => `<tr><td>${esc(r.label)}</td><td class="right money">${r.value || 0}</td>${two ? `<td class="right money">${r.value2 || 0}</td>` : ''}</tr>`).join('')}</tbody></table></div>
    </div>`;
}

function niceStep(max) {
  if (max <= 5) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(max)));
  const f = max / p;
  return (f <= 2 ? 0.5 : f <= 5 ? 1 : 2) * p;
}

// Horizontal bars with the value at the tip.
function hbars(rows, unit) {
  const max = Math.max(1, ...rows.map(r => r.value || 0));
  return `<div class="hbars">${rows.map(r => `
    <div class="hbar-row viz-hit" data-tip="${esc(r.label)}: ${r.value == null ? 'no data' : r.value + (unit ? ' ' + unit : '')}${r.extra ? ' · ' + esc(r.extra) : ''}">
      <div class="hbar-label">${esc(r.label)}</div>
      <div class="hbar-track"><div class="hbar-fill viz-s1" style="width:${r.value ? Math.max(2, (r.value / max) * 100) : 0}%"></div></div>
      <div class="hbar-value money">${r.value == null ? '<span class="muted">—</span>' : r.value + (unit ? ` <span class="muted small">${unit}</span>` : '')}</div>
    </div>`).join('')}</div>`;
}

function wireTooltips(root) {
  let tip = document.getElementById('viz-tip');
  if (!tip) { tip = document.createElement('div'); tip.id = 'viz-tip'; tip.className = 'viz-tip hidden'; document.body.appendChild(tip); }
  root.querySelectorAll('.viz-hit').forEach(el => {
    el.addEventListener('mouseenter', () => { tip.textContent = el.dataset.tip; tip.classList.remove('hidden'); });
    el.addEventListener('mousemove', (e) => { tip.style.left = `${e.clientX + 12}px`; tip.style.top = `${e.clientY + 12}px`; });
    el.addEventListener('mouseleave', () => tip.classList.add('hidden'));
  });
}
