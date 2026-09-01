// Quote builder: pre-filled from the clinic's equipment, every quantity and price editable, live totals.
import { clinics, quotes } from '../api.js';
import { esc, attr, fmtMoney, toast, setTitle, getRepName, navigate, shorthandBadge, toDateInput, options } from '../ui.js';

let st = null; // builder state

export async function render(container, params, routeParams) {
  let clinic, existing = null;
  if (routeParams.quoteId) {
    existing = await quotes.get(Number(routeParams.quoteId));
    clinic = await clinics.get(existing.clinic_id);
  } else {
    clinic = await clinics.get(Number(routeParams.clinicId));
  }
  setTitle(existing ? `Edit ${existing.number}` : `Quote · ${clinic.shorthand || clinic.name}`);
  const d = await quotes.defaults(clinic.id, existing ? { pricing_mode: existing.pricing_mode, emr_mode: existing.emr_mode } : {});
  st = {
    clinic, existing, defaults: d,
    title: existing ? existing.title : d.suggested_title,
    pricing_mode: existing ? existing.pricing_mode : 'per_device',
    emr_mode: existing ? existing.emr_mode : 'flat',
    plan_key: existing ? existing.plan_key : (d.lines.find(l => l.category === 'plan' && l.included) || {}).key || null,
    user_count: existing ? existing.user_count : d.counts.users,
    device_count: existing ? existing.device_count : d.counts.devices_managed,
    counts: d.counts,
    lines: existing ? existing.lines.map(l => ({ ...l })) : d.lines.map(l => ({ ...l })),
    discount_pct: existing ? existing.discount_pct : 0,
    tax_pct: existing ? existing.tax_pct : d.tax_pct,
    notes: existing ? existing.notes || '' : '',
    terms: existing ? existing.terms || '' : d.terms,
    prepared_by: existing ? existing.prepared_by || getRepName() : getRepName(),
    contact_id: existing ? existing.contact_id || '' : (d.contacts.find(c => c.is_primary) || d.contacts[0] || {}).id || '',
    valid_until: existing ? existing.valid_until || d.valid_until : d.valid_until,
  };
  if (!existing) syncPlanLines();
  draw(container);
}

function syncPlanLines() { st.lines.forEach(l => { if (l.category === 'plan') l.included = l.key === st.plan_key; }); }

// Re-fetch defaults for a different pricing basis, keeping the user's edited prices where units did not change.
async function switchMode(mode, emr) {
  const d = await quotes.defaults(st.clinic.id, { pricing_mode: mode, emr_mode: emr });
  const old = Object.fromEntries(st.lines.map(l => [l.key, l]));
  st.lines = d.lines.map(l => {
    const o = old[l.key];
    if (!o) return l;
    const sameUnit = o.unit === l.unit;
    return { ...l, included: o.included, qty: sameUnit ? o.qty : l.qty, unit_price: sameUnit ? o.unit_price : l.unit_price, note: o.note };
  });
  // custom lines the user added
  st.lines.push(...Object.values(old).filter(o => o.custom));
  st.pricing_mode = mode; st.emr_mode = emr;
  // plan/EMR quantities follow the basis counts
  st.lines.forEach(l => {
    if (l.category === 'plan') l.qty = mode === 'per_user' ? st.user_count : st.device_count;
    if (l.key === 'primeemr' && emr === 'per_user') l.qty = st.user_count;
  });
  syncPlanLines();
}

function totals() {
  let monthly = 0, onetime = 0;
  for (const l of st.lines) {
    if (!l.included) continue;
    const t = (Number(l.qty) || 0) * (Number(l.unit_price) || 0);
    if (l.unit === 'one_time') onetime += t; else monthly += t;
  }
  const discount = monthly * (Number(st.discount_pct) || 0) / 100;
  const after = monthly - discount;
  const tax = after * (Number(st.tax_pct) || 0) / 100;
  const otax = onetime * (Number(st.tax_pct) || 0) / 100;
  return { monthly, discount, tax, monthly_total: after + tax, onetime, otax, onetime_total: onetime + otax, annual: (after + tax) * 12 };
}

function draw(container) {
  const { clinic, defaults: d } = st;
  const c = st.counts;
  const cats = d.categories;
  const groups = {};
  st.lines.forEach((l, i) => { (groups[l.category] ||= []).push(i); });
  const order = ['infra', 'backup', 'emr', 'extras', 'rates', 'onetime'];
  const plans = st.lines.map((l, i) => ({ ...l, i })).filter(l => l.category === 'plan');

  container.innerHTML = `
    <div class="mb"><a href="#/clinics/${clinic.id}">← ${esc(clinic.name)}</a> · <a href="#/clinics/${clinic.id}/equipment">Equipment</a> · <a href="#/quotes">All quotes</a></div>
    <div class="page-header">
      <h1>${shorthandBadge(clinic)} ${st.existing ? `Edit ${esc(st.existing.number)}` : 'New quote'}</h1>
      <div class="actions"><a class="btn" href="${st.existing ? `#/quotes/${st.existing.id}` : `#/clinics/${clinic.id}`}">Cancel</a><button class="btn btn-primary" id="save-quote">${st.existing ? 'Save changes' : 'Generate quote'}</button></div>
    </div>
    <div class="qb-layout">
      <div>
        <div class="card">
          <div class="field-row">
            <div class="field" style="grid-column: span 2"><label>Quote title</label><input id="q-title" value="${attr(st.title)}"></div>
            <div class="field"><label>Prepared for</label><select id="q-contact"><option value="">— No named contact —</option>${d.contacts.map(ct => `<option value="${ct.id}" ${String(ct.id) === String(st.contact_id) ? 'selected' : ''}>${esc(ct.first_name)} ${esc(ct.last_name || '')}${ct.role ? ` (${esc(ct.role)})` : ''}</option>`).join('')}</select></div>
            <div class="field"><label>Prepared by</label><input id="q-rep" value="${attr(st.prepared_by)}"></div>
            <div class="field"><label>Valid until</label><input id="q-valid" type="date" value="${attr(st.valid_until)}"></div>
          </div>
        </div>

        <div class="card">
          <div class="card-header"><h3>Pricing basis</h3>
            <div class="actions"><span class="mode-toggle"><button class="btn ${st.pricing_mode === 'per_device' ? 'active' : ''}" data-mode="per_device">Per device</button><button class="btn ${st.pricing_mode === 'per_user' ? 'active' : ''}" data-mode="per_user">Per user</button></span></div></div>
          <div class="field-row">
            <div class="field"><label>Managed devices (workstations + laptops + servers)</label><input id="q-devices" type="number" min="0" value="${st.device_count}"><div class="help">From the topology: ${c.workstations} workstations · ${c.laptops} laptops · ${c.servers_all} servers</div></div>
            <div class="field"><label>Users needing support</label><input id="q-users" type="number" min="0" value="${st.user_count}"><div class="help">${c.users} distinct users found on devices; adjust to the headcount that will call for help.</div></div>
          </div>
          <div class="count-grid">
            ${[['Firewalls', c.firewalls], ['Switches', c.switches], ['Access points', c.aps], ['Physical servers', c.servers_physical], ['VMs', c.vms], ['Phones', c.phones], ['Printers', c.printers], ['Sites', c.sites]].map(([l, n]) => `<span><strong>${n}</strong> ${l}</span>`).join('')}
          </div>
          <div class="help mt">Counts come from active equipment on this clinic. Every quantity below can still be changed by hand.</div>
        </div>

        <div class="card">
          <div class="card-header"><h3>Managed IT plan</h3><span class="muted small">Pick one · priced ${st.pricing_mode === 'per_user' ? 'per user' : 'per managed device'} per month</span></div>
          <div class="plan-grid">${plans.map(p => `
            <div class="plan-card ${st.plan_key === p.key ? 'selected' : ''}" data-plan="${p.key}">
              <div class="name">${esc(p.label)}</div>
              <div class="price">$<input type="number" min="0" step="1" data-price="${p.i}" value="${p.unit_price}"> <span class="muted small">× ${p.qty}</span></div>
              <div class="desc">${esc(p.description || '')}</div>
              <div class="mt"><strong class="money">${fmtMoney(p.qty * p.unit_price)}</strong> <span class="muted small">/ month</span></div>
            </div>`).join('')}
            <div class="plan-card ${!st.plan_key ? 'selected' : ''}" data-plan=""><div class="name">No managed plan</div><div class="desc">Infrastructure and add-ons only.</div></div>
          </div>
        </div>

        <div class="card">
          <div class="card-header"><h3>Services</h3><div class="actions"><button class="btn btn-sm" id="add-line">+ Custom line</button></div></div>
          <div class="table-wrap"><table class="table qline-table">
            <thead><tr><th></th><th>Item</th><th class="right">Qty</th><th class="right">Unit price</th><th class="right">Monthly</th></tr></thead>
            <tbody>${order.filter(k => groups[k]).map(k => `
              <tr class="group-row"><td colspan="5">${esc(cats[k])}${k === 'rates' ? ' <span class="muted" style="font-weight:400">— shown as a rate card; enter estimated hours/month to include in the total</span>' : ''}${k === 'emr' ? ` <span class="mode-toggle" style="margin-left:8px"><button class="btn btn-sm ${st.emr_mode === 'flat' ? 'active' : ''}" data-emr="flat">Flat / month</button><button class="btn btn-sm ${st.emr_mode === 'per_user' ? 'active' : ''}" data-emr="per_user">Per user</button></span>` : ''}</td></tr>
              ${groups[k].map(i => lineRow(st.lines[i], i, d)).join('')}`).join('')}
            </tbody></table></div>
        </div>

        <div class="card">
          <div class="field"><label>Notes to the customer</label><textarea id="q-notes" rows="3" placeholder="Assumptions, what's excluded, onboarding timeline…">${esc(st.notes)}</textarea></div>
          <div class="field"><label>Terms</label><textarea id="q-terms" rows="3">${esc(st.terms)}</textarea></div>
        </div>
      </div>

      <div class="qb-sticky">
        <div class="card totals-box" id="totals"></div>
        <div class="card mt">
          <div class="field-row">
            <div class="field"><label>Discount %</label><input id="q-discount" type="number" min="0" max="100" step="0.5" value="${st.discount_pct}"></div>
            <div class="field"><label>Tax %</label><input id="q-tax" type="number" min="0" step="0.1" value="${st.tax_pct}"></div>
          </div>
        </div>
      </div>
    </div>`;

  const redraw = () => draw(container);
  const bindVal = (id, key, num = false) => { const el = container.querySelector(id); el.oninput = () => { st[key] = num ? Number(el.value) : el.value; if (num) renderTotals(container); }; };
  bindVal('#q-title', 'title'); bindVal('#q-rep', 'prepared_by'); bindVal('#q-valid', 'valid_until'); bindVal('#q-notes', 'notes'); bindVal('#q-terms', 'terms');
  bindVal('#q-discount', 'discount_pct', true); bindVal('#q-tax', 'tax_pct', true);
  container.querySelector('#q-contact').onchange = (e) => { st.contact_id = e.target.value; };
  container.querySelector('#q-devices').onchange = (e) => { st.device_count = Number(e.target.value) || 0; if (st.pricing_mode === 'per_device') st.lines.forEach(l => { if (l.category === 'plan') l.qty = st.device_count; }); redraw(); };
  container.querySelector('#q-users').onchange = (e) => { st.user_count = Number(e.target.value) || 0; st.lines.forEach(l => { if (l.category === 'plan' && st.pricing_mode === 'per_user') l.qty = st.user_count; if (l.unit === 'per_user') l.qty = st.user_count; }); redraw(); };
  container.querySelectorAll('[data-mode]').forEach(b => { b.onclick = async () => { await switchMode(b.dataset.mode, st.emr_mode); redraw(); }; });
  container.querySelectorAll('[data-emr]').forEach(b => { b.onclick = async () => { await switchMode(st.pricing_mode, b.dataset.emr); redraw(); }; });
  container.querySelectorAll('.plan-card').forEach(card => {
    card.onclick = (e) => { if (e.target.tagName === 'INPUT') return; st.plan_key = card.dataset.plan || null; syncPlanLines(); redraw(); };
  });
  container.querySelectorAll('[data-price]').forEach(inp => { inp.oninput = () => { st.lines[Number(inp.dataset.price)].unit_price = Number(inp.value) || 0; renderTotals(container); }; inp.onchange = redraw; });
  container.querySelectorAll('[data-qty]').forEach(inp => { inp.oninput = () => { st.lines[Number(inp.dataset.qty)].qty = Number(inp.value) || 0; renderTotals(container); updateRow(container, Number(inp.dataset.qty)); }; });
  container.querySelectorAll('[data-lprice]').forEach(inp => { inp.oninput = () => { st.lines[Number(inp.dataset.lprice)].unit_price = Number(inp.value) || 0; renderTotals(container); updateRow(container, Number(inp.dataset.lprice)); }; });
  container.querySelectorAll('[data-inc]').forEach(cb => { cb.onchange = () => { st.lines[Number(cb.dataset.inc)].included = cb.checked; renderTotals(container); updateRow(container, Number(cb.dataset.inc)); }; });
  container.querySelectorAll('[data-label]').forEach(inp => { inp.oninput = () => { st.lines[Number(inp.dataset.label)].label = inp.value; }; });
  container.querySelectorAll('[data-lunit]').forEach(sel => { sel.onchange = () => { st.lines[Number(sel.dataset.lunit)].unit = sel.value; redraw(); }; });
  container.querySelectorAll('[data-del]').forEach(b => { b.onclick = () => { st.lines.splice(Number(b.dataset.del), 1); redraw(); }; });
  container.querySelector('#add-line').onclick = () => { st.lines.push({ key: `custom_${Date.now()}`, label: '', category: 'extras', unit: 'per_month', qty: 1, unit_price: 0, included: true, custom: true }); redraw(); setTimeout(() => { const els = container.querySelectorAll('[data-label]'); if (els.length) els[els.length - 1].focus(); }, 30); };
  container.querySelector('#save-quote').onclick = save;
  renderTotals(container);
}

function lineRow(l, i, d) {
  const t = (Number(l.qty) || 0) * (Number(l.unit_price) || 0);
  const isRate = l.unit === 'per_hour';
  return `<tr class="${l.included ? '' : 'excluded'}" data-row="${i}">
    <td><input type="checkbox" data-inc="${i}" ${l.included ? 'checked' : ''} title="Include in quote"></td>
    <td>${l.custom ? `<input class="wide" data-label="${i}" value="${attr(l.label)}" placeholder="Item name"><select data-lunit="${i}" class="mt" style="width:auto;padding:3px 6px;font-size:12px">${options(d.units, l.unit)}</select>` : `<strong>${esc(l.label)}</strong><div class="unit">${esc(d.units[l.unit] || l.unit)}${l.description ? ` · ${esc(l.description)}` : ''}</div>`}</td>
    <td class="right"><input type="number" min="0" step="${isRate ? '0.5' : '1'}" data-qty="${i}" value="${l.qty}" title="${isRate ? 'Estimated hours per month' : 'Quantity'}">${isRate ? '<div class="auto">hrs / month</div>' : ''}</td>
    <td class="right"><input type="number" min="0" step="0.01" data-lprice="${i}" value="${l.unit_price}"></td>
    <td class="total" data-total="${i}">${l.unit === 'one_time' ? `<span class="muted small">one-time</span> ${fmtMoney(t)}` : fmtMoney(t)}${l.custom ? ` <button class="btn btn-link btn-sm" data-del="${i}" title="Remove line">×</button>` : ''}</td>
  </tr>`;
}

function updateRow(container, i) {
  const l = st.lines[i];
  const row = container.querySelector(`[data-row="${i}"]`);
  if (!row) return;
  row.classList.toggle('excluded', !l.included);
  const t = (Number(l.qty) || 0) * (Number(l.unit_price) || 0);
  const cell = row.querySelector(`[data-total="${i}"]`);
  const del = cell.querySelector('[data-del]');
  cell.innerHTML = (l.unit === 'one_time' ? `<span class="muted small">one-time</span> ${fmtMoney(t)}` : fmtMoney(t));
  if (del) cell.appendChild(del);
}

function renderTotals(container) {
  const t = totals();
  const plan = st.lines.find(l => l.category === 'plan' && l.included);
  container.querySelector('#totals').innerHTML = `
    <h3>Quote total</h3>
    <div class="row muted"><span>Plan</span><span>${plan ? esc(plan.label) : 'None'}</span></div>
    <div class="row muted"><span>Basis</span><span>${st.pricing_mode === 'per_user' ? `${st.user_count} users` : `${st.device_count} devices`}</span></div>
    <div class="row"><span>Monthly services</span><span class="money">${fmtMoney(t.monthly)}</span></div>
    ${t.discount ? `<div class="row"><span>Discount (${st.discount_pct}%)</span><span class="money">−${fmtMoney(t.discount)}</span></div>` : ''}
    <div class="row"><span>Tax (${st.tax_pct}%)</span><span class="money">${fmtMoney(t.tax)}</span></div>
    <div class="row big"><span>Per month</span><span class="money">${fmtMoney(t.monthly_total)}</span></div>
    <div class="row muted"><span>Per year</span><span class="money">${fmtMoney(t.annual)}</span></div>
    ${t.onetime ? `<div class="row mt"><span>One-time (incl. tax)</span><span class="money">${fmtMoney(t.onetime_total)}</span></div>` : ''}
    <div class="row muted"><span>Per ${st.pricing_mode === 'per_user' ? 'user' : 'device'}</span><span class="money">${fmtMoney(t.monthly_total / Math.max(1, st.pricing_mode === 'per_user' ? st.user_count : st.device_count))}</span></div>`;
}

async function save() {
  if (!st.title.trim()) { toast('Give the quote a title', 'error'); return; }
  const body = {
    title: st.title, pricing_mode: st.pricing_mode, emr_mode: st.emr_mode, plan_key: st.plan_key, user_count: st.user_count, device_count: st.device_count,
    counts: st.counts, lines: st.lines.filter(l => !(l.custom && !l.label.trim())).map(l => ({ key: l.key, label: l.label, category: l.category, unit: l.unit, qty: Number(l.qty) || 0, unit_price: Number(l.unit_price) || 0, included: !!l.included, note: l.note || null })),
    discount_pct: Number(st.discount_pct) || 0, tax_pct: Number(st.tax_pct) || 0, notes: st.notes, terms: st.terms, prepared_by: st.prepared_by,
    contact_id: st.contact_id ? Number(st.contact_id) : null, valid_until: st.valid_until || null,
  };
  try {
    const q = st.existing ? await quotes.update(st.existing.id, body) : await quotes.create(st.clinic.id, body);
    toast(st.existing ? 'Quote saved' : `Quote ${q.number} generated`, 'success');
    navigate(`#/quotes/${q.id}`);
  } catch (e) { toast(e.message, 'error', 6000); }
}
