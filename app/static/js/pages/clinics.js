// Clinics page: alphabetical, grouped by first letter, searchable and filterable.
import { clinics, getMeta } from '../api.js';
import { esc, attr, dot, fmtDate, fmtDateOnly, fmtMoney, relativeDays, badge, options, navigate, debounce, setTitle, stageBadge } from '../ui.js';
import { openClinicForm } from '../forms.js';

let state = { q: '', relationship: '', color: '', stage: '', sort: 'name' };

export async function render(container) {
  setTitle('Clinics');
  const meta = await getMeta();
  container.innerHTML = `
    <div class="page-header">
      <h1>Clinics</h1>
      <span class="muted" id="clinic-count"></span>
      <div class="actions">
        <a class="btn" href="/api/export/clinics.csv" download>Export CSV</a>
        <button class="btn btn-primary" id="add-clinic">+ New clinic</button>
      </div>
    </div>
    <div class="toolbar">
      <input type="search" class="search" id="q" placeholder="Search name, address, tags, EMR…" value="${attr(state.q)}">
      <select id="relationship">${options(meta.relationships, state.relationship, { blank: 'All relationships' })}</select>
      <select id="color">${options(meta.colors, state.color, { blank: 'All colours' })}</select>
      <select id="stage">${options(meta.stages, state.stage, { blank: 'All stages' })}</select>
      <select id="sort">
        <option value="name" ${state.sort === 'name' ? 'selected' : ''}>Sort: A → Z</option>
        <option value="last_visit" ${state.sort === 'last_visit' ? 'selected' : ''}>Sort: Last visit (oldest first)</option>
        <option value="follow_up" ${state.sort === 'follow_up' ? 'selected' : ''}>Sort: Follow-up date</option>
        <option value="priority" ${state.sort === 'priority' ? 'selected' : ''}>Sort: Priority</option>
        <option value="value" ${state.sort === 'value' ? 'selected' : ''}>Sort: Deal value</option>
      </select>
    </div>
    <div class="table-wrap" id="table"></div>`;

  container.querySelector('#add-clinic').onclick = () => openClinicForm({ onSaved: (c) => navigate(`#/clinics/${c.id}`) });
  const q = container.querySelector('#q');
  q.addEventListener('input', debounce(() => { state.q = q.value; load(); }, 200));
  ['relationship', 'color', 'stage', 'sort'].forEach(k => {
    container.querySelector(`#${k}`).addEventListener('change', (e) => { state[k] = e.target.value; load(); });
  });
  await load();
}

const PRIORITY_RANK = { high: 0, medium: 1, low: 2 };

async function load() {
  const list = await clinics.list({ q: state.q, relationship: state.relationship, color: state.color, stage: state.stage });
  document.getElementById('clinic-count').textContent = `${list.length} clinic${list.length === 1 ? '' : 's'}`;
  const el = document.getElementById('table');
  if (!list.length) { el.innerHTML = '<div class="card empty">No clinics yet. Click “+ New clinic” to add your first one.</div>'; return; }

  let sorted = [...list];
  if (state.sort === 'last_visit') sorted.sort((a, b) => (a.last_visit || '').localeCompare(b.last_visit || ''));
  else if (state.sort === 'follow_up') sorted.sort((a, b) => (a.next_follow_up || '9999').localeCompare(b.next_follow_up || '9999'));
  else if (state.sort === 'priority') sorted.sort((a, b) => PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority] || a.name.localeCompare(b.name));
  else if (state.sort === 'value') sorted.sort((a, b) => (b.deal_value || 0) - (a.deal_value || 0) || a.name.localeCompare(b.name));

  let rows = '';
  let lastLetter = null;
  for (const c of sorted) {
    if (state.sort === 'name') {
      const letter = (c.name[0] || '#').toUpperCase();
      const group = /[A-Z]/.test(letter) ? letter : '#';
      if (group !== lastLetter) { rows += `<tr class="group-row"><td colspan="9">${group}</td></tr>`; lastLetter = group; }
    }
    rows += `
      <tr class="clickable" data-id="${c.id}">
        <td>${dot(c.color, c.color_label)}<strong>${esc(c.name)}</strong>${c.priority === 'high' ? ' ' + badge('High', 'badge-high') : ''}</td>
        <td><span class="badge badge-${esc(c.color)}">${esc(c.color_label)}</span></td>
        <td>${stageBadge(c)}${c.deal_value ? `<div class="muted small money">${fmtMoney(c.deal_value)}</div>` : ''}</td>
        <td>${esc(c.clinic_type || '')}</td>
        <td>${esc(c.address || '')}${c.lat == null ? ' <span class="muted small">(not on map)</span>' : ''}</td>
        <td class="nowrap">${c.phone ? `<a href="tel:${attr(c.phone)}">${esc(c.phone)}</a>` : ''}</td>
        <td class="nowrap">${c.last_visit ? `${esc(fmtDate(c.last_visit))}<div class="muted small">${esc(relativeDays(c.last_visit))}</div>` : '<span class="muted">never</span>'}</td>
        <td class="nowrap">${c.next_appointment ? `${esc(fmtDate(c.next_appointment.start_time))}<div class="muted small">${esc(c.next_appointment.title)}</div>` : ''}</td>
        <td class="nowrap">${c.next_follow_up ? `<span class="${c.next_follow_up < new Date().toISOString().slice(0, 10) ? 'badge badge-red' : ''}">${esc(fmtDateOnly(c.next_follow_up))}</span>` : ''}</td>
      </tr>`;
  }
  el.innerHTML = `
    <table class="table">
      <thead><tr>
        <th>Clinic</th><th>Status</th><th>Stage</th><th>Type</th><th>Address</th><th>Phone</th><th>Last visit</th><th>Next appt</th><th>Follow-up</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  el.querySelectorAll('tr.clickable').forEach(tr => { tr.onclick = () => navigate(`#/clinics/${tr.dataset.id}`); });
}
