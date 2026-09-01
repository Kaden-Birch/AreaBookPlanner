// Modal forms for clinics, contacts and appointments (shared across pages).
import { clinics, contacts, appointments, geocode, getMeta } from './api.js';
import {
  esc, attr, openModal, confirmDialog, toast, formData, showFormError, options,
  toLocalInput, pinIcon, debounce,
} from './ui.js';

// ---- Clinic --------------------------------------------------------------

export async function openClinicForm({ clinic = null, initial = {}, onSaved } = {}) {
  const meta = await getMeta();
  const c = { city: 'Calgary', province: 'AB', relationship: 'prospect', priority: 'medium', ...(clinic || {}), ...initial };
  const isEdit = !!clinic;

  const body = `
    <form id="clinic-form" autocomplete="off">
      <div class="field-row">
        <div class="field" style="grid-column: span 2">
          <label>Clinic name *</label>
          <input name="name" required value="${attr(c.name)}" placeholder="e.g. Crowfoot Medical Clinic">
        </div>
        <div class="field">
          <label>Relationship to ChinookIT</label>
          <select name="relationship">${options(meta.relationships, c.relationship)}</select>
          <div class="help">Prospects are coloured by visit recency (blue / grey / white).</div>
        </div>
        <div class="field">
          <label>Priority</label>
          <select name="priority">${options({ high: 'High', medium: 'Medium', low: 'Low' }, c.priority)}</select>
        </div>
      </div>

      <div class="form-section">
        <h3>Address & location</h3>
        <div class="field">
          <label>Street address</label>
          <div class="flex">
            <input name="address" value="${attr(c.address)}" placeholder="123 4 Ave SW" class="grow">
            <button type="button" class="btn" id="geocode-btn" title="Look up this address and drop the pin">Find on map</button>
          </div>
          <div class="geocode-results hidden" id="geocode-results"></div>
        </div>
        <div class="field-row">
          <div class="field"><label>City</label><input name="city" value="${attr(c.city)}"></div>
          <div class="field"><label>Province</label><input name="province" value="${attr(c.province)}"></div>
          <div class="field"><label>Postal code</label><input name="postal_code" value="${attr(c.postal_code)}"></div>
        </div>
        <div class="field-row">
          <div class="field"><label>Latitude</label><input name="lat" type="number" step="any" value="${attr(c.lat ?? '')}"></div>
          <div class="field"><label>Longitude</label><input name="lng" type="number" step="any" value="${attr(c.lng ?? '')}"></div>
          <div class="field" style="align-self:end"><button type="button" class="btn" id="clear-pin">Clear pin</button></div>
        </div>
        <div class="help mb">Click the map to place the pin manually, or drag it to adjust.</div>
        <div class="mini-map" id="clinic-form-map"></div>
      </div>

      <div class="form-section">
        <h3>Contact details</h3>
        <div class="field-row">
          <div class="field"><label>Phone</label><input name="phone" value="${attr(c.phone)}"></div>
          <div class="field"><label>Fax</label><input name="fax" value="${attr(c.fax)}"></div>
          <div class="field"><label>Email</label><input name="email" type="email" value="${attr(c.email)}"></div>
          <div class="field"><label>Website</label><input name="website" value="${attr(c.website)}" placeholder="https://"></div>
        </div>
      </div>

      <div class="form-section">
        <h3>Practice details</h3>
        <div class="field-row">
          <div class="field">
            <label>Clinic type</label>
            <input name="clinic_type" list="clinic-types" value="${attr(c.clinic_type)}">
            <datalist id="clinic-types">${meta.clinic_types.map(t => `<option value="${attr(t)}">`).join('')}</datalist>
          </div>
          <div class="field"><label>EMR system</label><input name="emr_system" value="${attr(c.emr_system)}" placeholder="e.g. Telus Wolf, Accuro"></div>
          <div class="field"><label>Current IT provider</label><input name="it_provider" value="${attr(c.it_provider)}"></div>
          <div class="field"><label># Providers</label><input name="provider_count" type="number" min="0" value="${attr(c.provider_count ?? '')}"></div>
        </div>
        <div class="field-row">
          <div class="field"><label>Tags (comma separated)</label><input name="tags" value="${attr(c.tags)}" placeholder="NW, walk-in, referral"></div>
          <div class="field"><label>Next follow-up</label><input name="next_follow_up" type="date" value="${attr(c.next_follow_up)}"></div>
        </div>
        <div class="field">
          <label>General notes</label>
          <textarea name="notes" rows="4" placeholder="Anything useful about this clinic: hours, parking, decision makers, history...">${esc(c.notes)}</textarea>
        </div>
      </div>
    </form>`;

  const modal = openModal({
    title: isEdit ? `Edit ${c.name}` : 'New clinic',
    size: 'modal-lg',
    body,
    footer: `<button class="btn" data-act="cancel">Cancel</button>
             <button class="btn btn-primary" data-act="save">${isEdit ? 'Save changes' : 'Create clinic'}</button>`,
  });

  const form = modal.body.querySelector('#clinic-form');
  const latEl = form.elements.lat;
  const lngEl = form.elements.lng;

  // Mini map with draggable pin
  const map = L.map(modal.body.querySelector('#clinic-form-map'), { zoomControl: true });
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution: '&copy; OpenStreetMap contributors',
  }).addTo(map);
  let marker = null;
  const setPin = (lat, lng, pan = true) => {
    latEl.value = Number(lat).toFixed(6);
    lngEl.value = Number(lng).toFixed(6);
    if (!marker) {
      marker = L.marker([lat, lng], { draggable: true, icon: pinIcon(c.color || 'blue') }).addTo(map);
      marker.on('dragend', () => { const p = marker.getLatLng(); setPin(p.lat, p.lng, false); });
    } else {
      marker.setLatLng([lat, lng]);
    }
    if (pan) map.setView([lat, lng], Math.max(map.getZoom(), 14));
  };
  if (c.lat != null && c.lng != null) {
    map.setView([c.lat, c.lng], 14);
    setPin(c.lat, c.lng);
  } else {
    map.setView([meta.map_default.lat, meta.map_default.lng], meta.map_default.zoom);
  }
  map.on('click', (e) => setPin(e.latlng.lat, e.latlng.lng, false));
  setTimeout(() => map.invalidateSize(), 50);
  const syncFromInputs = () => {
    const lat = parseFloat(latEl.value), lng = parseFloat(lngEl.value);
    if (!isNaN(lat) && !isNaN(lng)) setPin(lat, lng);
  };
  latEl.addEventListener('change', syncFromInputs);
  lngEl.addEventListener('change', syncFromInputs);
  form.querySelector('#clear-pin').onclick = () => {
    latEl.value = ''; lngEl.value = '';
    if (marker) { marker.remove(); marker = null; }
  };

  // Geocoding
  const resultsEl = form.querySelector('#geocode-results');
  form.querySelector('#geocode-btn').onclick = async () => {
    const q = [form.elements.address.value, form.elements.city.value, form.elements.province.value, form.elements.postal_code.value]
      .filter(v => v && v.trim()).join(', ');
    if (!q || q.length < 3) { toast('Enter an address first', 'error'); return; }
    resultsEl.classList.remove('hidden');
    resultsEl.innerHTML = '<div class="muted">Searching…</div>';
    try {
      const results = await geocode(q);
      if (!results.length) { resultsEl.innerHTML = '<div class="muted">No matches found. Try a simpler address, or click the map to place the pin.</div>'; return; }
      resultsEl.innerHTML = results.map((r, i) => `<div data-i="${i}">${esc(r.display_name)}</div>`).join('');
      resultsEl.querySelectorAll('[data-i]').forEach(el => {
        el.onclick = () => {
          const r = results[Number(el.dataset.i)];
          setPin(r.lat, r.lng);
          if (r.postal_code && !form.elements.postal_code.value) form.elements.postal_code.value = r.postal_code;
          if (r.city && !form.elements.city.value) form.elements.city.value = r.city;
          resultsEl.classList.add('hidden');
        };
      });
    } catch (e) {
      resultsEl.innerHTML = `<div class="muted">${esc(e.message)}</div>`;
    }
  };

  modal.root.querySelector('[data-act=cancel]').onclick = () => modal.close();
  const save = async () => {
    const data = formData(form);
    if (!data.name.trim()) { showFormError(form, 'Clinic name is required.'); return; }
    if (data.lat === '' || data.lat === null) data.lat = null;
    if (data.lng === '' || data.lng === null) data.lng = null;
    try {
      const saved = isEdit ? await clinics.update(clinic.id, data) : await clinics.create(data);
      toast(isEdit ? 'Clinic updated' : 'Clinic created', 'success');
      modal.close();
      onSaved && onSaved(saved);
    } catch (e) {
      showFormError(form, e.message);
    }
  };
  modal.root.querySelector('[data-act=save]').onclick = save;
  form.addEventListener('submit', (e) => { e.preventDefault(); save(); });
  return modal;
}

export async function deleteClinic(clinic) {
  const ok = await confirmDialog(
    `Delete "${clinic.name}"? Its appointments and note log will be deleted too. Contacts will be kept but unlinked.`
  );
  if (!ok) return false;
  await clinics.remove(clinic.id);
  toast('Clinic deleted');
  return true;
}

// ---- Contact -------------------------------------------------------------

async function clinicOptions(selected) {
  const list = await clinics.list();
  return `<option value="">— No clinic —</option>` + list.map(c =>
    `<option value="${c.id}"${String(c.id) === String(selected) ? ' selected' : ''}>${esc(c.name)}</option>`).join('');
}

export async function openContactForm({ contact = null, clinicId = null, onSaved } = {}) {
  const meta = await getMeta();
  const c = { role: 'staff', ...(contact || {}) };
  if (!contact && clinicId) c.clinic_id = clinicId;
  const isEdit = !!contact;
  const clinicOpts = await clinicOptions(c.clinic_id);

  const body = `
    <form id="contact-form" autocomplete="off">
      <div class="field">
        <label>Clinic</label>
        <select name="clinic_id">${clinicOpts}</select>
      </div>
      <div class="field-row">
        <div class="field"><label>First name *</label><input name="first_name" required value="${attr(c.first_name)}"></div>
        <div class="field"><label>Last name</label><input name="last_name" value="${attr(c.last_name)}"></div>
      </div>
      <div class="field-row">
        <div class="field"><label>Role</label><select name="role">${options(meta.contact_roles, c.role)}</select></div>
        <div class="field"><label>Title</label><input name="title" value="${attr(c.title)}" placeholder="e.g. Office Manager, MD"></div>
      </div>
      <div class="field-row">
        <div class="field"><label>Phone</label><input name="phone" value="${attr(c.phone)}"></div>
        <div class="field"><label>Mobile</label><input name="mobile" value="${attr(c.mobile)}"></div>
        <div class="field"><label>Email</label><input name="email" type="email" value="${attr(c.email)}"></div>
      </div>
      <div class="field">
        <label class="checkbox"><input type="checkbox" name="is_primary" ${c.is_primary ? 'checked' : ''}> Primary contact for this clinic</label>
      </div>
      <div class="field">
        <label>Notes</label>
        <textarea name="notes" rows="3" placeholder="Best time to call, preferences, background...">${esc(c.notes)}</textarea>
      </div>
    </form>`;

  const modal = openModal({
    title: isEdit ? `Edit ${c.first_name} ${c.last_name || ''}`.trim() : 'New contact',
    body,
    footer: `${isEdit ? '<button class="btn btn-danger left" data-act="delete">Delete</button>' : ''}
             <button class="btn" data-act="cancel">Cancel</button>
             <button class="btn btn-primary" data-act="save">${isEdit ? 'Save changes' : 'Add contact'}</button>`,
  });
  const form = modal.body.querySelector('#contact-form');
  modal.root.querySelector('[data-act=cancel]').onclick = () => modal.close();
  const del = modal.root.querySelector('[data-act=delete]');
  if (del) del.onclick = async () => {
    if (!(await confirmDialog(`Delete contact ${c.first_name} ${c.last_name || ''}?`))) return;
    await contacts.remove(contact.id);
    toast('Contact deleted');
    modal.close();
    onSaved && onSaved(null);
  };
  const save = async () => {
    const data = formData(form);
    if (!data.first_name.trim()) { showFormError(form, 'First name is required.'); return; }
    data.clinic_id = data.clinic_id ? Number(data.clinic_id) : null;
    try {
      const saved = isEdit ? await contacts.update(contact.id, data) : await contacts.create(data);
      toast(isEdit ? 'Contact updated' : 'Contact added', 'success');
      modal.close();
      onSaved && onSaved(saved);
    } catch (e) { showFormError(form, e.message); }
  };
  modal.root.querySelector('[data-act=save]').onclick = save;
  form.addEventListener('submit', (e) => { e.preventDefault(); save(); });
  return modal;
}

// ---- Appointment ---------------------------------------------------------

function defaultStart(start) {
  if (start) return start;
  const d = new Date();
  d.setDate(d.getDate() + 1);
  d.setHours(9, 0, 0, 0);
  return toLocalInput(d);
}

function addHour(v) {
  const d = new Date(v);
  if (isNaN(d.getTime())) return '';
  d.setHours(d.getHours() + 1);
  return toLocalInput(d);
}

export async function openAppointmentForm({ appointment = null, clinicId = null, start = null, onSaved, lockClinic = false } = {}) {
  const meta = await getMeta();
  const a = { appt_type: 'visit', status: 'scheduled', ...(appointment || {}) };
  if (!appointment) {
    a.clinic_id = clinicId || '';
    a.start_time = defaultStart(start);
    a.end_time = addHour(a.start_time);
  }
  const isEdit = !!appointment;
  const allClinics = await clinics.list();
  const clinicOpts = `<option value="">— Select a clinic —</option>` + allClinics.map(c =>
    `<option value="${c.id}"${String(c.id) === String(a.clinic_id) ? ' selected' : ''}>${esc(c.name)}</option>`).join('');

  const body = `
    <form id="appt-form" autocomplete="off">
      <div class="field-row">
        <div class="field" style="grid-column: span 2">
          <label>Clinic *</label>
          <select name="clinic_id" ${lockClinic && a.clinic_id ? 'disabled' : ''}>${clinicOpts}</select>
        </div>
        <div class="field">
          <label>Contact at clinic</label>
          <select name="contact_id"><option value="">—</option></select>
        </div>
      </div>
      <div class="field">
        <label>Title *</label>
        <input name="title" required value="${attr(a.title)}" placeholder="e.g. Intro visit, Network assessment, Quarterly check-in">
      </div>
      <div class="field-row">
        <div class="field"><label>Type</label><select name="appt_type">${options(meta.appointment_types, a.appt_type)}</select></div>
        <div class="field"><label>Status</label><select name="status">${options(meta.appointment_statuses, a.status)}</select></div>
      </div>
      <div class="field-row">
        <div class="field"><label>Start *</label><input name="start_time" type="datetime-local" required value="${attr(a.start_time)}"></div>
        <div class="field"><label>End</label><input name="end_time" type="datetime-local" value="${attr(a.end_time)}"></div>
      </div>
      <div class="field">
        <label>Location</label>
        <input name="location" value="${attr(a.location)}" placeholder="Defaults to the clinic address">
      </div>
      <div class="field">
        <label>Planning notes (before)</label>
        <textarea name="notes" rows="3" placeholder="Agenda, who you're meeting, what to bring...">${esc(a.notes)}</textarea>
      </div>
      <div class="field">
        <label>Outcome / appointment notes (after)</label>
        <textarea name="outcome" rows="4" placeholder="What happened, next steps, objections, follow-up needed...">${esc(a.outcome)}</textarea>
      </div>
    </form>`;

  const modal = openModal({
    title: isEdit ? 'Edit appointment' : 'New appointment',
    body,
    footer: `${isEdit ? '<button class="btn btn-danger left" data-act="delete">Delete</button>' : ''}
             <button class="btn" data-act="cancel">Cancel</button>
             <button class="btn btn-primary" data-act="save">${isEdit ? 'Save changes' : 'Create appointment'}</button>`,
  });
  const form = modal.body.querySelector('#appt-form');
  const clinicSel = form.elements.clinic_id;
  const contactSel = form.elements.contact_id;

  const loadContacts = async () => {
    const cid = clinicSel.value;
    contactSel.innerHTML = '<option value="">—</option>';
    if (!cid) return;
    const list = await contacts.list({ clinic_id: cid });
    contactSel.innerHTML += list.map(ct =>
      `<option value="${ct.id}"${String(ct.id) === String(a.contact_id) ? ' selected' : ''}>${esc(ct.full_name)} (${esc(ct.role_label)})</option>`).join('');
  };
  clinicSel.addEventListener('change', loadContacts);
  loadContacts();

  form.elements.start_time.addEventListener('change', () => {
    const s = form.elements.start_time.value, e = form.elements.end_time.value;
    if (s && (!e || e < s)) form.elements.end_time.value = addHour(s);
  });

  modal.root.querySelector('[data-act=cancel]').onclick = () => modal.close();
  const del = modal.root.querySelector('[data-act=delete]');
  if (del) del.onclick = async () => {
    if (!(await confirmDialog(`Delete appointment "${a.title}"?`))) return;
    await appointments.remove(appointment.id);
    toast('Appointment deleted');
    modal.close();
    onSaved && onSaved(null);
  };
  const save = async () => {
    const data = formData(form);
    data.clinic_id = clinicSel.value ? Number(clinicSel.value) : null;
    if (!data.clinic_id) { showFormError(form, 'Choose a clinic.'); return; }
    if (!data.title.trim()) { showFormError(form, 'Title is required.'); return; }
    if (!data.start_time) { showFormError(form, 'Start time is required.'); return; }
    data.contact_id = data.contact_id ? Number(data.contact_id) : null;
    try {
      const saved = isEdit ? await appointments.update(appointment.id, data) : await appointments.create(data);
      toast(isEdit ? 'Appointment updated' : 'Appointment created', 'success');
      modal.close();
      onSaved && onSaved(saved);
    } catch (e) { showFormError(form, e.message); }
  };
  modal.root.querySelector('[data-act=save]').onclick = save;
  form.addEventListener('submit', (e) => { e.preventDefault(); save(); });
  return modal;
}

// Quick "I was just there" logging: creates a completed visit right now.
export async function openLogVisit({ clinic, onSaved }) {
  const meta = await getMeta();
  const now = toLocalInput(new Date());
  const body = `
    <form id="visit-form">
      <div class="field-row">
        <div class="field"><label>When</label><input name="start_time" type="datetime-local" value="${attr(now)}"></div>
        <div class="field"><label>Type</label><select name="appt_type">${options(meta.appointment_types, 'visit')}</select></div>
      </div>
      <div class="field"><label>Title</label><input name="title" value="Drop-in visit"></div>
      <div class="field"><label>What happened?</label><textarea name="outcome" rows="4" placeholder="Who you spoke with, interest level, next steps..."></textarea></div>
    </form>`;
  const modal = openModal({
    title: `Log a visit · ${clinic.name}`,
    body,
    footer: `<button class="btn" data-act="cancel">Cancel</button><button class="btn btn-primary" data-act="save">Log visit</button>`,
  });
  const form = modal.body.querySelector('#visit-form');
  modal.root.querySelector('[data-act=cancel]').onclick = () => modal.close();
  const save = async () => {
    const data = formData(form);
    try {
      const saved = await appointments.create({ ...data, clinic_id: clinic.id, status: 'completed' });
      toast('Visit logged', 'success');
      modal.close();
      onSaved && onSaved(saved);
    } catch (e) { showFormError(form, e.message); }
  };
  modal.root.querySelector('[data-act=save]').onclick = save;
  form.addEventListener('submit', (e) => { e.preventDefault(); save(); });
}

export const debouncedSearch = debounce;
