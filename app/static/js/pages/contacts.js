// Contacts page: everyone across all clinics.
import { contacts, clinics, getMeta } from '../api.js';
import { esc, attr, options, debounce, setTitle } from '../ui.js';
import { openContactForm } from '../forms.js';

let state = { q: '', role: '', clinic_id: '' };

export async function render(container) {
  setTitle('Contacts');
  const meta = await getMeta();
  const clinicList = await clinics.list();
  container.innerHTML = `
    <div class="page-header">
      <h1>Contacts</h1>
      <span class="muted" id="contact-count"></span>
      <div class="actions">
        <a class="btn" href="/api/export/contacts.csv" download>Export CSV</a>
        <button class="btn btn-primary" id="add-contact">+ New contact</button>
      </div>
    </div>
    <div class="toolbar">
      <input type="search" class="search" id="q" placeholder="Search name, email, phone, clinic…" value="${attr(state.q)}">
      <select id="role">${options(meta.contact_roles, state.role, { blank: 'All roles' })}</select>
      <select id="clinic_id">
        <option value="">All clinics</option>
        ${clinicList.map(c => `<option value="${c.id}" ${String(c.id) === String(state.clinic_id) ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}
      </select>
    </div>
    <div class="table-wrap" id="table"></div>`;

  container.querySelector('#add-contact').onclick = () => openContactForm({ onSaved: load });
  const q = container.querySelector('#q');
  q.addEventListener('input', debounce(() => { state.q = q.value; load(); }, 200));
  ['role', 'clinic_id'].forEach(k => container.querySelector(`#${k}`).addEventListener('change', (e) => { state[k] = e.target.value; load(); }));
  await load();
}

async function load() {
  const list = await contacts.list({ q: state.q, role: state.role, clinic_id: state.clinic_id });
  document.getElementById('contact-count').textContent = `${list.length} contact${list.length === 1 ? '' : 's'}`;
  const el = document.getElementById('table');
  if (!list.length) { el.innerHTML = '<div class="card empty">No contacts found. Add contacts from a clinic profile or with “+ New contact”.</div>'; return; }
  el.innerHTML = `
    <table class="table">
      <thead><tr><th>Name</th><th>Role</th><th>Clinic</th><th>Phone</th><th>Mobile</th><th>Email</th><th>Notes</th><th></th></tr></thead>
      <tbody>
        ${list.map(c => `
          <tr>
            <td>${c.is_primary ? '<span class="star" title="Primary contact">★</span> ' : ''}<strong>${esc(c.full_name)}</strong>${c.title ? `<div class="muted small">${esc(c.title)}</div>` : ''}</td>
            <td><span class="badge">${esc(c.role_label)}</span></td>
            <td>${c.clinic_id ? `<a href="#/clinics/${c.clinic_id}">${esc(c.clinic_name)}</a>` : '<span class="muted">—</span>'}</td>
            <td class="nowrap">${c.phone ? `<a href="tel:${attr(c.phone)}">${esc(c.phone)}</a>` : ''}</td>
            <td class="nowrap">${c.mobile ? `<a href="tel:${attr(c.mobile)}">${esc(c.mobile)}</a>` : ''}</td>
            <td>${c.email ? `<a href="mailto:${attr(c.email)}">${esc(c.email)}</a>` : ''}</td>
            <td class="small muted">${esc(c.notes || '')}</td>
            <td class="actions"><button class="btn btn-sm" data-id="${c.id}">Edit</button></td>
          </tr>`).join('')}
      </tbody>
    </table>`;
  el.querySelectorAll('button[data-id]').forEach(b => {
    b.onclick = () => openContactForm({ contact: list.find(c => c.id === Number(b.dataset.id)), onSaved: load });
  });
}
