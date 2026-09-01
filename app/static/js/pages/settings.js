// Settings: your name, notifications, email templates, groups, CSV import, bulk geocoding, saved views, data.
import { api, getMeta, clinics } from '../api.js';
import { esc, attr, openModal, confirmDialog, toast, formData, showFormError, setTitle, getRepName, setRepName, options } from '../ui.js';
import * as notif from '../notifications.js';

export async function render(container) {
  setTitle('Settings');
  const [templates, groups, views, geo] = await Promise.all([
    api.get('/api/templates'), api.get('/api/groups'), api.get('/api/views'), api.get('/api/geocode/bulk'),
  ]);
  const perm = notif.permission();
  container.innerHTML = `
    <div class="page-header"><h1>Settings</h1></div>
    <div class="grid-2">
      <div>
        <div class="card">
          <div class="card-header"><h3>You</h3></div>
          <div class="field"><label>Your name (used for "activity by rep" and email templates)</label>
            <div class="flex"><input id="rep-name" value="${attr(getRepName())}" placeholder="e.g. Kaden" class="grow"><button class="btn" id="save-rep">Save</button></div>
            <div class="help">Stored in this browser only. Notes, appointments and tasks you create are tagged with it.</div></div>
        </div>

        <div class="card">
          <div class="card-header"><h3>Desktop notifications</h3></div>
          <p class="small">Area Book reminds you when an appointment or task is starting, and ahead of time if you set a reminder on it. Reminders fire while a tab with the app is open.</p>
          <p>Status: <strong id="notif-status">${notifLabel(perm)}</strong></p>
          <div class="flex">
            <button class="btn btn-primary" id="notif-enable" ${perm === 'granted' || perm === 'denied' || perm === 'unsupported' ? 'disabled' : ''}>Enable notifications</button>
            <button class="btn" id="notif-test" ${perm === 'granted' ? '' : 'disabled'}>Send a test</button>
          </div>
          ${perm === 'denied' ? '<p class="help mt">Notifications are blocked for this site. Allow them in the browser\'s site settings (the lock icon in the address bar) and reload.</p>' : ''}
          ${!window.isSecureContext ? '<p class="help mt">This page is not a secure context, so the browser will not allow notifications. Open the app via <strong>localhost</strong> or <strong>https://</strong>.</p>' : ''}
        </div>

        <div class="card">
          <div class="card-header"><h3>Email templates</h3><div class="actions"><button class="btn btn-sm" id="add-tpl">+ Template</button></div></div>
          <p class="small muted">Placeholders: {contact_first_name} {contact_name} {clinic_name} {shorthand} {rep_name}</p>
          <ul class="list" id="tpl-list">${templates.map(t => `
            <li data-id="${t.id}"><div class="body"><div class="title">${esc(t.name)}</div><div class="muted small">${esc(t.subject)}</div></div>
              <div class="actions"><button class="btn btn-sm" data-act="edit-tpl">Edit</button></div></li>`).join('') || '<li class="muted">No templates.</li>'}</ul>
        </div>

        <div class="card">
          <div class="card-header"><h3>Clinic groups / chains</h3><div class="actions"><button class="btn btn-sm" id="add-group">+ Group</button></div></div>
          <p class="small muted">Assign clinics to a group from the clinic form. Contacts can be shared across a group.</p>
          <ul class="list" id="group-list">${groups.map(g => `
            <li data-id="${g.id}"><div class="body"><div class="title">${esc(g.name)} <span class="muted">(${g.member_count})</span></div>
              <div class="muted small">${g.members.map(m => `<a href="#/clinics/${m.id}">${esc(m.name)}</a>`).join(' · ') || 'No clinics yet'}</div></div>
              <div class="actions"><button class="btn btn-sm" data-act="edit-group">Edit</button></div></li>`).join('') || '<li class="muted">No groups yet.</li>'}</ul>
        </div>
      </div>

      <div>
        <div class="card">
          <div class="card-header"><h3>Import clinics from CSV</h3></div>
          <p class="small">Upload a spreadsheet exported as CSV. Columns are matched by header name (name, address, city, postal code, phone, email, website, type, EMR, tags, notes, shorthand, relationship, stage, value…). Likely duplicates are skipped.</p>
          <label class="btn" style="margin:0">Choose CSV file… <input type="file" id="csv-file" accept=".csv,text/csv" class="hidden"></label>
          <div id="csv-result" class="mt"></div>
        </div>

        <div class="card">
          <div class="card-header"><h3>Geocode unmapped clinics</h3></div>
          <p class="small">Looks up the address of every clinic that has no pin and places it on the map. Uses OpenStreetMap at one lookup per second.</p>
          <div class="flex"><button class="btn btn-primary" id="geo-start" ${geo.running ? 'disabled' : ''}>Geocode all unmapped</button><span id="geo-status" class="small muted">${geoText(geo)}</span></div>
          <div id="geo-failed" class="mt small"></div>
        </div>

        <div class="card">
          <div class="card-header"><h3>Saved map views</h3></div>
          <ul class="list" id="view-list">${views.map(v => `
            <li data-id="${v.id}"><div class="body"><div class="title">${esc(v.name)}</div><div class="muted small">${describeView(v.state)}</div></div>
              <div class="actions"><a class="btn btn-sm" href="#/map?view=${v.id}">Open</a><button class="btn btn-sm btn-danger" data-act="del-view">Delete</button></div></li>`).join('') || '<li class="muted">Save a view from the map sidebar to see it here.</li>'}</ul>
        </div>

        <div class="card">
          <div class="card-header"><h3>Data</h3></div>
          <div class="flex flex-wrap">
            <a class="btn" href="/api/export/backup.json" download>Download backup (JSON)</a>
            <a class="btn" href="/api/export/clinics.csv" download>Clinics CSV</a>
            <a class="btn" href="/api/export/contacts.csv" download>Contacts CSV</a>
            <a class="btn" href="/api/export/appointments.ics" download>Calendar .ics</a>
          </div>
          <p class="help mt">Restore a backup from the Dashboard → Data card.</p>
        </div>
      </div>
    </div>`;

  const reload = () => render(container);
  container.querySelector('#save-rep').onclick = () => { setRepName(container.querySelector('#rep-name').value.trim()); toast('Name saved', 'success'); };
  container.querySelector('#notif-enable').onclick = async () => {
    try { const p = await notif.requestPermission(); toast(p === 'granted' ? 'Notifications enabled' : 'Notifications not enabled', p === 'granted' ? 'success' : 'error'); reload(); }
    catch (e) { toast(e.message, 'error'); }
  };
  container.querySelector('#notif-test').onclick = () => { if (!notif.sendTest()) toast('Notifications are not enabled', 'error'); };

  // Templates
  container.querySelector('#add-tpl').onclick = () => openTemplateForm({ onSaved: reload });
  container.querySelectorAll('[data-act=edit-tpl]').forEach(b => {
    b.onclick = () => openTemplateForm({ template: templates.find(t => t.id === Number(b.closest('li').dataset.id)), onSaved: reload });
  });
  // Groups
  container.querySelector('#add-group').onclick = () => openGroupForm({ onSaved: reload });
  container.querySelectorAll('[data-act=edit-group]').forEach(b => {
    b.onclick = () => openGroupForm({ group: groups.find(g => g.id === Number(b.closest('li').dataset.id)), onSaved: reload });
  });
  // Views
  container.querySelectorAll('[data-act=del-view]').forEach(b => {
    b.onclick = async () => { if (!(await confirmDialog('Delete this saved view?'))) return; await api.del(`/api/views/${b.closest('li').dataset.id}`); reload(); };
  });
  // CSV
  container.querySelector('#csv-file').onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const text = await file.text();
    e.target.value = '';
    openImportWizard(text, container.querySelector('#csv-result'));
  };
  // Geocode
  container.querySelector('#geo-start').onclick = () => startGeocode(container);
  if (geo.running) pollGeocode(container);
  if (geo.failed && geo.failed.length) showGeoFailed(container, geo);
}

function notifLabel(p) {
  return { granted: 'Enabled', denied: 'Blocked by browser', default: 'Not enabled yet', unsupported: 'Not supported in this browser' }[p] || p;
}
function geoText(g) {
  if (g.running) return `Running… ${g.done}/${g.total}`;
  if (g.finished_at && g.total) return `Last run: ${g.updated} of ${g.total} placed on the map.`;
  return '';
}
function describeView(s) {
  const bits = [];
  if (s.q) bits.push(`"${s.q}"`);
  if (s.colors && s.colors.length && s.colors.length < 6) bits.push(s.colors.join(', '));
  if (s.stages && s.stages.length) bits.push('stages: ' + s.stages.join(', '));
  if (s.near && s.near.on) bits.push(s.near.mode === 'min' ? `within ${s.near.min} min` : `within ${s.near.km} km`);
  if (s.near && s.near.staleOnly) bits.push('not visited 3+ months');
  return bits.join(' · ') || 'All clinics';
}

// ---- Geocoding job -------------------------------------------------------------

export async function startGeocode(container, clinicIds = null) {
  try {
    await api.post('/api/geocode/bulk', clinicIds ? { clinic_ids: clinicIds } : {});
    toast('Geocoding started');
    pollGeocode(container);
  } catch (e) { toast(e.message, 'error'); }
}

function pollGeocode(container) {
  const btn = container.querySelector('#geo-start');
  const status = container.querySelector('#geo-status');
  if (btn) btn.disabled = true;
  const tick = async () => {
    const g = await api.get('/api/geocode/bulk');
    if (status) status.textContent = geoText(g);
    if (g.running) { setTimeout(tick, 1500); return; }
    if (btn) btn.disabled = false;
    if (g.total) toast(`Geocoding finished: ${g.updated} of ${g.total} placed`, 'success', 5000);
    showGeoFailed(container, g);
  };
  tick();
}

function showGeoFailed(container, g) {
  const el = container.querySelector('#geo-failed');
  if (!el) return;
  el.innerHTML = g.failed && g.failed.length
    ? `<strong>Could not find:</strong> ${g.failed.map(f => `<a href="#/clinics/${f.id}">${esc(f.name)}</a>`).join(', ')} — open each clinic and place the pin by hand.`
    : '';
}

// ---- Template / group forms ---------------------------------------------------

function openTemplateForm({ template = null, onSaved }) {
  const t = template || { name: '', subject: '', body: '' };
  const modal = openModal({
    title: template ? 'Edit template' : 'New email template',
    body: `<form id="tpl-form">
      <div class="field"><label>Name</label><input name="name" required value="${attr(t.name)}"></div>
      <div class="field"><label>Subject</label><input name="subject" required value="${attr(t.subject)}"></div>
      <div class="field"><label>Body</label><textarea name="body" rows="8">${esc(t.body)}</textarea>
        <div class="help">Placeholders: {contact_first_name} {contact_name} {clinic_name} {shorthand} {rep_name}</div></div>
    </form>`,
    footer: `${template ? '<button class="btn btn-danger left" data-act="delete">Delete</button>' : ''}<button class="btn" data-act="cancel">Cancel</button><button class="btn btn-primary" data-act="save">Save</button>`,
  });
  const form = modal.body.querySelector('#tpl-form');
  modal.root.querySelector('[data-act=cancel]').onclick = () => modal.close();
  const del = modal.root.querySelector('[data-act=delete]');
  if (del) del.onclick = async () => { if (!(await confirmDialog('Delete this template?'))) return; await api.del(`/api/templates/${template.id}`); modal.close(); onSaved(); };
  const save = async () => {
    const data = formData(form);
    if (!data.name.trim() || !data.subject.trim()) { showFormError(form, 'Name and subject are required.'); return; }
    try { template ? await api.put(`/api/templates/${template.id}`, data) : await api.post('/api/templates', data); toast('Template saved', 'success'); modal.close(); onSaved(); }
    catch (e) { showFormError(form, e.message); }
  };
  modal.root.querySelector('[data-act=save]').onclick = save;
  form.onsubmit = (e) => { e.preventDefault(); save(); };
}

export function openGroupForm({ group = null, onSaved }) {
  const g = group || { name: '', notes: '' };
  const modal = openModal({
    title: group ? 'Edit group' : 'New clinic group',
    size: 'modal-sm',
    body: `<form id="group-form">
      <div class="field"><label>Group name</label><input name="name" required value="${attr(g.name)}" placeholder="e.g. SDI Clinics"></div>
      <div class="field"><label>Notes</label><textarea name="notes" rows="3" placeholder="Shared decision makers, billing arrangements…">${esc(g.notes)}</textarea></div>
    </form>`,
    footer: `${group ? '<button class="btn btn-danger left" data-act="delete">Delete</button>' : ''}<button class="btn" data-act="cancel">Cancel</button><button class="btn btn-primary" data-act="save">Save</button>`,
  });
  const form = modal.body.querySelector('#group-form');
  modal.root.querySelector('[data-act=cancel]').onclick = () => modal.close();
  const del = modal.root.querySelector('[data-act=delete]');
  if (del) del.onclick = async () => { if (!(await confirmDialog('Delete this group? Clinics stay, they just leave the group.'))) return; await api.del(`/api/groups/${group.id}`); modal.close(); onSaved(); };
  const save = async () => {
    const data = formData(form);
    if (!data.name.trim()) { showFormError(form, 'Name is required.'); return; }
    try { const saved = group ? await api.put(`/api/groups/${group.id}`, data) : await api.post('/api/groups', data); toast('Group saved', 'success'); modal.close(); onSaved(saved); }
    catch (e) { showFormError(form, e.message); }
  };
  modal.root.querySelector('[data-act=save]').onclick = save;
  form.onsubmit = (e) => { e.preventDefault(); save(); };
  return modal;
}

// ---- CSV import wizard --------------------------------------------------------

const FIELD_LABELS = {
  '': '— skip —', name: 'Clinic name', shorthand: 'Shorthand', address: 'Street address', city: 'City', province: 'Province',
  postal_code: 'Postal code', phone: 'Phone', fax: 'Fax', email: 'Email', website: 'Website', clinic_type: 'Clinic type',
  emr_system: 'EMR system', it_provider: 'IT provider', provider_count: '# providers', relationship: 'Relationship',
  stage: 'Pipeline stage', priority: 'Priority', deal_value: 'Deal value', expected_close: 'Expected close', next_follow_up: 'Next follow-up',
  tags: 'Tags', notes: 'Notes', lat: 'Latitude', lng: 'Longitude',
};
const SYNONYMS = {
  name: ['name', 'clinic', 'clinic name', 'practice', 'business'], shorthand: ['shorthand', 'short', 'code', 'abbreviation', 'abbr'],
  address: ['address', 'street', 'address 1', 'address1', 'street address'], city: ['city', 'town'], province: ['province', 'prov', 'state'],
  postal_code: ['postal', 'postal code', 'postcode', 'zip', 'zip code'], phone: ['phone', 'telephone', 'main line', 'phone number'], fax: ['fax'],
  email: ['email', 'e-mail'], website: ['website', 'web', 'url', 'site'], clinic_type: ['type', 'clinic type', 'category'],
  emr_system: ['emr', 'emr system', 'ehr'], it_provider: ['it provider', 'it', 'current it', 'msp'], provider_count: ['providers', '# providers', 'provider count', 'doctors'],
  relationship: ['relationship', 'status', 'client status'], stage: ['stage', 'pipeline', 'pipeline stage'], priority: ['priority'],
  deal_value: ['value', 'deal value', 'annual value', 'contract value'], expected_close: ['expected close', 'close date'], next_follow_up: ['follow up', 'follow-up', 'next follow up', 'next follow-up'],
  tags: ['tags', 'tag', 'area', 'quadrant'], notes: ['notes', 'note', 'comments'], lat: ['lat', 'latitude'], lng: ['lng', 'lon', 'long', 'longitude'],
};

export function parseCsv(text) {
  const rows = [];
  let row = [], field = '', inQ = false;
  text = text.replace(/^﻿/, '');
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQ) {
      if (ch === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else inQ = false; }
      else field += ch;
    } else if (ch === '"') inQ = true;
    else if (ch === ',') { row.push(field); field = ''; }
    else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && text[i + 1] === '\n') i++;
      row.push(field); field = '';
      if (row.some(v => v.trim() !== '')) rows.push(row);
      row = [];
    } else field += ch;
  }
  row.push(field);
  if (row.some(v => v.trim() !== '')) rows.push(row);
  return rows;
}

function guessField(header) {
  const h = header.trim().toLowerCase().replace(/[_-]+/g, ' ');
  for (const [field, names] of Object.entries(SYNONYMS)) if (names.includes(h)) return field;
  for (const [field, names] of Object.entries(SYNONYMS)) if (names.some(n => h.includes(n))) return field;
  return '';
}

function normalizeValue(field, v) {
  v = (v ?? '').toString().trim();
  if (!v) return null;
  if (field === 'relationship') {
    const s = v.toLowerCase();
    if (/(current|existing)?\s*client|customer|won/.test(s)) return 'current_client';
    if (/interest/.test(s)) return 'interested';
    if (/do not|dnc|don't|no contact/.test(s)) return 'do_not_contact';
    return 'prospect';
  }
  if (field === 'stage') {
    const s = v.toLowerCase();
    for (const k of ['prospect', 'contacted', 'demo', 'proposal', 'won', 'lost']) if (s.includes(k)) return k;
    if (/contact/.test(s)) return 'contacted';
    return 'prospect';
  }
  if (field === 'priority') { const s = v.toLowerCase(); return s.startsWith('h') ? 'high' : s.startsWith('l') ? 'low' : 'medium'; }
  if (field === 'provider_count') { const n = parseInt(v, 10); return isNaN(n) ? null : n; }
  if (['deal_value', 'lat', 'lng'].includes(field)) { const n = parseFloat(v.replace(/[$,]/g, '')); return isNaN(n) ? null : n; }
  return v;
}

async function openImportWizard(text, resultEl) {
  const rows = parseCsv(text);
  if (rows.length < 2) { toast('The file needs a header row and at least one data row', 'error'); return; }
  const headers = rows[0];
  const data = rows.slice(1);
  const mapping = headers.map(guessField);
  const modal = openModal({
    title: `Import ${data.length} clinic${data.length === 1 ? '' : 's'}`,
    size: 'modal-lg',
    body: `
      <p class="small">Match each column to a clinic field. Rows without a name are skipped; likely duplicates of existing clinics are skipped and listed afterwards.</p>
      <div class="table-wrap"><table class="table" id="map-table">
        <thead><tr>${headers.map((h, i) => `<th><div class="small muted">${esc(h)}</div><select data-col="${i}">${Object.entries(FIELD_LABELS).map(([k, l]) => `<option value="${k}" ${mapping[i] === k ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select></th>`).join('')}</tr></thead>
        <tbody>${data.slice(0, 5).map(r => `<tr>${headers.map((_, i) => `<td class="small">${esc(r[i] || '')}</td>`).join('')}</tr>`).join('')}</tbody>
      </table></div>
      ${data.length > 5 ? `<p class="muted small">…and ${data.length - 5} more rows</p>` : ''}
      <label class="checkbox mt"><input type="checkbox" id="imp-geocode" checked> Look up addresses and place new clinics on the map after import</label>
      <label class="checkbox"><input type="checkbox" id="imp-skip" checked> Skip likely duplicates</label>`,
    footer: `<button class="btn" data-act="cancel">Cancel</button><button class="btn btn-primary" data-act="go">Import</button>`,
  });
  modal.root.querySelector('[data-act=cancel]').onclick = () => modal.close();
  modal.root.querySelector('[data-act=go]').onclick = async () => {
    const map = [...modal.body.querySelectorAll('select[data-col]')].map(s => s.value);
    if (!map.includes('name')) { toast('Map one column to "Clinic name"', 'error'); return; }
    const payloadRows = data.map(r => {
      const obj = {};
      map.forEach((f, i) => { if (f) { const v = normalizeValue(f, r[i]); if (v !== null) obj[f] = v; } });
      return obj;
    });
    const geocode = modal.body.querySelector('#imp-geocode').checked;
    const btn = modal.root.querySelector('[data-act=go]');
    btn.disabled = true; btn.textContent = 'Importing…';
    try {
      const res = await api.post('/api/import/clinics', { rows: payloadRows, skip_duplicates: modal.body.querySelector('#imp-skip').checked });
      modal.close();
      resultEl.innerHTML = `
        <div class="form-ok"><strong>${res.created.length}</strong> clinic${res.created.length === 1 ? '' : 's'} imported
          · <strong>${res.skipped.length}</strong> skipped as duplicates · <strong>${res.errors.length}</strong> rows with errors.</div>
        ${res.skipped.length ? `<details class="mt"><summary>Skipped duplicates</summary><ul class="small">${res.skipped.map(s => `<li>Row ${s.row}: "${esc(s.name)}" looks like <a href="#/clinics/${s.match_id}">${esc(s.match)}</a> (${esc(s.reasons.join(', '))})</li>`).join('')}</ul></details>` : ''}
        ${res.errors.length ? `<details class="mt"><summary>Errors</summary><ul class="small">${res.errors.map(e => `<li>Row ${e.row}: ${esc(e.error)}</li>`).join('')}</ul></details>` : ''}`;
      toast(`Imported ${res.created.length} clinics`, 'success');
      const toGeocode = res.created.filter(c => c.needs_geocode).map(c => c.id);
      if (geocode && toGeocode.length) startGeocode(document.getElementById('app'), toGeocode);
    } catch (e) { toast(e.message, 'error'); btn.disabled = false; btn.textContent = 'Import'; }
  };
}
