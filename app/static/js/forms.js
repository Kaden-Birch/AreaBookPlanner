// Modal forms for clinics, contacts and appointments (shared across pages).
import { clinics, contacts, appointments, tasks, geocode, getMeta, groups, locations, templates } from './api.js';
import {
  esc, attr, openModal, confirmDialog, toast, formData, showFormError, options,
  toLocalInput, toDateInput, pinIcon, debounce, getRepName, fillTemplate, mailtoUrl,
} from './ui.js';
import { openGroupForm } from './pages/settings.js';

// ---- Clinic --------------------------------------------------------------

export async function openClinicForm({ clinic = null, initial = {}, onSaved } = {}) {
  const meta = await getMeta();
  const groupList = await groups.list();
  const c = { city: 'Calgary', province: 'AB', relationship: 'prospect', priority: 'medium', ...(clinic || {}), ...initial };
  const isEdit = !!clinic;
  const groupOpts = (sel) => `<option value="">— None —</option>` + groupList.map(g => `<option value="${g.id}" ${String(g.id) === String(sel) ? 'selected' : ''}>${esc(g.name)}</option>`).join('');

  const body = `
    <form id="clinic-form" autocomplete="off">
      <div class="field-row">
        <div class="field" style="grid-column: span 2">
          <label>Clinic name *</label>
          <input name="name" required value="${attr(c.name)}" placeholder="e.g. Crowfoot Medical Clinic">
          <div id="dup-warning" class="form-warn hidden"></div>
        </div>
        <div class="field">
          <label>Relationship to ChinookIT</label>
          <select name="relationship" id="rel-select">${options(meta.relationships, c.relationship)}</select>
          <div class="help">Prospects are coloured by visit recency (blue / grey / white).</div>
        </div>
        <div class="field" id="priority-field">
          <label>Priority</label>
          <select name="priority">${options({ high: 'High', medium: 'Medium', low: 'Low' }, c.priority)}</select>
        </div>
        <div class="field hidden" id="shorthand-field">
          <label>Shorthand code</label>
          <input name="shorthand" maxlength="10" value="${attr(c.shorthand)}" placeholder="e.g. COC" style="text-transform:uppercase">
          <div class="help">Short code you use for this client (3 letters works well).</div>
        </div>
      </div>
      <div class="field-row">
        <div class="field">
          <label>Clinic group / chain</label>
          <div class="flex"><select name="group_id" id="group-select" class="grow">${groupOpts(c.group_id)}</select><button type="button" class="btn" id="new-group-btn" title="Create a new group">+</button></div>
          <div class="help">Multi-location groups share contacts and decision makers.</div>
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
        <h3>Deal / pipeline</h3>
        <div class="field-row">
          <div class="field">
            <label>Pipeline stage</label>
            <select name="stage" id="stage-select">${options(meta.stages, c.stage || 'prospect')}</select>
            <div class="help">Won sets the relationship to Current client.</div>
          </div>
          <div class="field">
            <label>Est. annual value (CAD)</label>
            <input name="deal_value" type="number" min="0" step="100" value="${attr(c.deal_value ?? '')}" placeholder="e.g. 12000">
          </div>
          <div class="field open-only">
            <label>Win probability %</label>
            <input name="win_probability" type="number" min="0" max="100" step="5" value="${attr(c.win_probability ?? '')}" id="prob-input" placeholder="${meta.default_probability[c.stage || 'prospect']}">
            <div class="help">Blank uses the stage default.</div>
          </div>
          <div class="field open-only">
            <label>Expected close</label>
            <input name="expected_close" type="date" value="${attr(c.expected_close)}">
          </div>
        </div>
        <div id="outcome-fields" class="${['won', 'lost'].includes(c.stage) ? '' : 'hidden'}">
          <div class="field-row">
            <div class="field">
              <label id="outcome-label">${c.stage === 'lost' ? 'Why lost?' : 'Why won?'}</label>
              <select name="outcome_reason" id="outcome-reason"></select>
            </div>
            <div class="field">
              <label id="outcome-date-label">${c.stage === 'lost' ? 'Lost on' : 'Client since (onboarded)'}</label>
              <input name="outcome_date" type="date" value="${attr(c.outcome_date)}">
              <div class="help">Can be any past date, e.g. when they first signed on.</div>
            </div>
          </div>
          <div class="field">
            <label>Outcome notes</label>
            <textarea name="outcome_notes" rows="2" placeholder="What tipped it? Who decided? Anything to learn for next time?">${esc(c.outcome_notes)}</textarea>
          </div>
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

  // Stage-dependent outcome fields + client mode (shorthand instead of priority)
  const stageSel = form.querySelector('#stage-select');
  const relSel = form.querySelector('#rel-select');
  const outcomeBox = form.querySelector('#outcome-fields');
  const reasonSel = form.querySelector('#outcome-reason');
  const fillReasons = () => {
    const stage = stageSel.value;
    const closed = stage === 'won' || stage === 'lost';
    outcomeBox.classList.toggle('hidden', !closed);
    form.querySelectorAll('.open-only').forEach(el => el.classList.toggle('hidden', closed));
    form.querySelector('#prob-input').placeholder = meta.default_probability[stage];
    if (!closed) return;
    form.querySelector('#outcome-label').textContent = stage === 'lost' ? 'Why lost?' : 'Why won?';
    form.querySelector('#outcome-date-label').textContent = stage === 'lost' ? 'Lost on' : 'Client since (onboarded)';
    reasonSel.innerHTML = options(stage === 'lost' ? meta.lost_reasons : meta.won_reasons, c.outcome_reason, { blank: '— Select a reason —' });
    if (!form.elements.outcome_date.value) form.elements.outcome_date.value = toDateInput(new Date());
  };
  const syncClientMode = () => {
    const isClient = relSel.value === 'current_client' || stageSel.value === 'won';
    form.querySelector('#priority-field').classList.toggle('hidden', isClient);
    form.querySelector('#shorthand-field').classList.toggle('hidden', !isClient);
  };
  stageSel.addEventListener('change', () => {
    if (stageSel.value === 'won' && relSel.value !== 'do_not_contact') relSel.value = 'current_client';
    fillReasons(); syncClientMode();
  });
  relSel.addEventListener('change', () => {
    if (relSel.value === 'current_client' && stageSel.value !== 'won') { stageSel.value = 'won'; fillReasons(); }
    syncClientMode();
  });
  fillReasons();
  syncClientMode();

  // New group inline
  form.querySelector('#new-group-btn').onclick = () => openGroupForm({ onSaved: (g) => {
    if (!g) return;
    const sel = form.querySelector('#group-select');
    sel.insertAdjacentHTML('beforeend', `<option value="${g.id}" selected>${esc(g.name)}</option>`);
  } });

  // Duplicate detection while typing
  const dupBox = form.querySelector('#dup-warning');
  const checkDup = debounce(async () => {
    const name = form.elements.name.value.trim();
    const address = form.elements.address.value.trim();
    if (name.length < 3 && address.length < 5) { dupBox.classList.add('hidden'); return; }
    try {
      const dups = await clinics.duplicates({ name, address, postal_code: form.elements.postal_code.value, exclude_id: clinic ? clinic.id : undefined });
      if (!dups.length) { dupBox.classList.add('hidden'); return; }
      dupBox.innerHTML = `⚠ Possible duplicate: ${dups.slice(0, 3).map(d => `<a href="#/clinics/${d.id}" target="_blank">${esc(d.name)}</a> (${esc(d.reasons.join(', '))})`).join(' · ')}`;
      dupBox.classList.remove('hidden');
    } catch { /* ignore */ }
  }, 400);
  form.elements.name.addEventListener('input', checkDup);
  form.elements.address.addEventListener('input', checkDup);
  if (!isEdit) checkDup();

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
    if (!['won', 'lost'].includes(data.stage)) { data.outcome_reason = null; data.outcome_notes = null; data.outcome_date = null; }
    data.group_id = data.group_id ? Number(data.group_id) : null;
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

let clinicCache = null;
async function clinicList() { clinicCache = await clinics.list(); return clinicCache; }
async function clinicOptions(selected) {
  const list = await clinicList();
  return `<option value="">— No clinic —</option>` + list.map(c =>
    `<option value="${c.id}"${String(c.id) === String(selected) ? ' selected' : ''}>${esc(c.name)}${c.shorthand ? ` (${esc(c.shorthand)})` : ''}</option>`).join('');
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
        <label class="checkbox mt hidden" id="shared-row"><input type="checkbox" name="shared_with_group" ${c.shared_with_group ? 'checked' : ''}> Shared across the clinic group (<span id="shared-group-name"></span>)</label>
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
        <div class="field" style="grid-column: span 2">
          <label>Phone</label>
          <div class="flex">
            <input name="phone" value="${attr(c.phone)}" class="grow" id="phone-input">
            <span class="muted small">ext.</span>
            <input name="extension" value="${attr(c.extension)}" placeholder="204" style="width:90px">
          </div>
          <label class="checkbox mt"><input type="checkbox" name="use_main_line" ${c.use_main_line ? 'checked' : ''}> Use the clinic's main line with an extension <span class="muted" id="main-line-hint"></span></label>
        </div>
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
  // Main-line + extension and group sharing depend on the chosen clinic
  const clinicSel = form.elements.clinic_id;
  const mainCb = form.elements.use_main_line;
  const phoneInput = form.querySelector('#phone-input');
  const extInput = form.elements.extension;
  let savedPhone = c.phone || '';
  const syncClinic = () => {
    const cl = (clinicCache || []).find(x => String(x.id) === clinicSel.value);
    const hint = form.querySelector('#main-line-hint');
    hint.textContent = cl && cl.phone ? `(${cl.phone})` : (cl ? '(clinic has no phone on file)' : '');
    mainCb.disabled = !(cl && cl.phone);
    if (mainCb.disabled) mainCb.checked = false;
    if (mainCb.checked && cl) {
      if (!phoneInput.disabled) savedPhone = phoneInput.value;
      phoneInput.value = cl.phone || '';
      phoneInput.disabled = true;
      extInput.focus();
    } else if (phoneInput.disabled) {
      phoneInput.disabled = false;
      phoneInput.value = savedPhone;
    }
    const sharedRow = form.querySelector('#shared-row');
    sharedRow.classList.toggle('hidden', !(cl && cl.group_id));
    if (cl && cl.group_id) {
      const g = form.querySelector('#shared-group-name');
      groups.list().then(list => { const grp = list.find(x => x.id === cl.group_id); g.textContent = grp ? grp.name : 'group'; });
    } else form.elements.shared_with_group.checked = false;
  };
  clinicSel.addEventListener('change', syncClinic);
  mainCb.addEventListener('change', syncClinic);
  syncClinic();

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
    if (data.use_main_line) data.phone = null;
    else data.phone = phoneInput.value;
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
      <div class="field-row">
        <div class="field" style="grid-column: span 2">
          <label>Location</label>
          <input name="location" value="${attr(a.location)}" placeholder="Defaults to the clinic address">
        </div>
        <div class="field">
          <label>Remind me</label>
          <select name="reminder_minutes">${options({ '': 'At start only', 15: '15 min before', 30: '30 min before', 45: '45 min before', 60: '1 hour before' }, a.reminder_minutes ?? '')}</select>
        </div>
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
    data.reminder_minutes = data.reminder_minutes ? Number(data.reminder_minutes) : null;
    data.rep = isEdit ? (a.rep || getRepName() || null) : (getRepName() || null);
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
      const saved = await appointments.create({ ...data, clinic_id: clinic.id, status: 'completed', rep: getRepName() || null });
      toast('Visit logged', 'success');
      modal.close();
      onSaved && onSaved(saved);
    } catch (e) { showFormError(form, e.message); }
  };
  modal.root.querySelector('[data-act=save]').onclick = save;
  form.addEventListener('submit', (e) => { e.preventDefault(); save(); });
}

// ---- Pipeline stage change (Kanban drop / select) -----------------------

export async function changeStage(clinic, stage, onSaved) {
  if (stage === clinic.stage) return;
  if (stage === 'won' || stage === 'lost') {
    return openOutcomeDialog({ clinic, stage, onSaved });
  }
  try {
    const saved = await clinics.setStage(clinic.id, { stage });
    toast(`${clinic.name} → ${saved.stage_label}`, 'success');
    onSaved && onSaved(saved);
  } catch (e) { toast(e.message, 'error'); }
}

export async function openOutcomeDialog({ clinic, stage, onSaved }) {
  const meta = await getMeta();
  const won = stage === 'won';
  const reasons = won ? meta.won_reasons : meta.lost_reasons;
  const modal = openModal({
    title: won ? `Mark ${clinic.name} as Won 🎉` : `Mark ${clinic.name} as Lost`,
    size: 'modal-sm',
    body: `
      <form id="outcome-form">
        <div class="field">
          <label>${won ? 'Why did we win?' : 'Why did we lose?'}</label>
          <select name="outcome_reason">${options(reasons, '', { blank: '— Select a reason —' })}</select>
        </div>
        <div class="field">
          <label>${won ? 'Client since (onboarded on)' : 'Lost on'}</label>
          <input name="outcome_date" type="date" value="${toDateInput(new Date())}">
          <div class="help">Back-date this if they signed on a while ago.</div>
        </div>
        <div class="field">
          <label>Notes</label>
          <textarea name="outcome_notes" rows="3" placeholder="${won ? 'What sealed it? Contract details, start date...' : 'Who did they go with? Any chance to revisit later?'}"></textarea>
        </div>
        ${won ? '<p class="help">The clinic will be marked as a <strong>Current client</strong> (yellow on the map).</p>' : '<p class="help">The map colour is left unchanged. Set “Do not contact” on the clinic if they asked not to be called again.</p>'}
      </form>`,
    footer: `<button class="btn" data-act="cancel">Cancel</button>
             <button class="btn btn-primary" data-act="save">${won ? 'Mark won' : 'Mark lost'}</button>`,
  });
  const form = modal.body.querySelector('#outcome-form');
  modal.root.querySelector('[data-act=cancel]').onclick = () => modal.close();
  const save = async () => {
    const data = formData(form);
    try {
      const saved = await clinics.setStage(clinic.id, { stage, ...data });
      toast(`${clinic.name} marked ${saved.stage_label}`, 'success');
      modal.close();
      onSaved && onSaved(saved);
    } catch (e) { showFormError(form, e.message); }
  };
  modal.root.querySelector('[data-act=save]').onclick = save;
  form.addEventListener('submit', (e) => { e.preventDefault(); save(); });
  return modal;
}

// ---- Tasks -------------------------------------------------------------------

export async function openTaskForm({ task = null, clinicId = null, onSaved } = {}) {
  const t = { priority: 'medium', ...(task || {}) };
  if (!task && clinicId) t.clinic_id = clinicId;
  const isEdit = !!task;
  const clinicOpts = await clinicOptions(t.clinic_id);
  const body = `
    <form id="task-form" autocomplete="off">
      <div class="field"><label>Task *</label><input name="title" required value="${attr(t.title)}" placeholder="e.g. Call Sarah about the quote"></div>
      <div class="field-row">
        <div class="field"><label>Clinic</label><select name="clinic_id">${clinicOpts}</select></div>
        <div class="field"><label>Contact</label><select name="contact_id"><option value="">—</option></select></div>
      </div>
      <div class="field-row">
        <div class="field"><label>Due date</label><input name="due_date" type="date" value="${attr(t.due_date)}"></div>
        <div class="field"><label>Time</label><input name="due_time" type="time" value="${attr(t.due_time)}"><div class="help">Reminders use 9:00 AM if blank.</div></div>
        <div class="field"><label>Remind me</label><select name="reminder_minutes">${options({ '': 'At due time only', 15: '15 min before', 30: '30 min before', 45: '45 min before', 60: '1 hour before' }, t.reminder_minutes ?? '')}</select></div>
        <div class="field"><label>Priority</label><select name="priority">${options({ high: 'High', medium: 'Medium', low: 'Low' }, t.priority)}</select></div>
      </div>
      <div class="field"><label>Notes</label><textarea name="notes" rows="3">${esc(t.notes)}</textarea></div>
      ${isEdit ? `<div class="field"><label class="checkbox"><input type="checkbox" name="done" ${t.done ? 'checked' : ''}> Done</label></div>` : ''}
    </form>`;
  const modal = openModal({
    title: isEdit ? 'Edit task' : 'New task',
    body,
    footer: `${isEdit ? '<button class="btn btn-danger left" data-act="delete">Delete</button>' : ''}
             <button class="btn" data-act="cancel">Cancel</button>
             <button class="btn btn-primary" data-act="save">${isEdit ? 'Save changes' : 'Add task'}</button>`,
  });
  const form = modal.body.querySelector('#task-form');
  const clinicSel = form.elements.clinic_id, contactSel = form.elements.contact_id;
  const loadContacts = async () => {
    contactSel.innerHTML = '<option value="">—</option>';
    if (!clinicSel.value) return;
    const list = await contacts.list({ clinic_id: clinicSel.value });
    contactSel.innerHTML += list.map(ct => `<option value="${ct.id}"${String(ct.id) === String(t.contact_id) ? ' selected' : ''}>${esc(ct.full_name)}</option>`).join('');
  };
  clinicSel.addEventListener('change', loadContacts);
  loadContacts();
  // Quick due-date shortcuts
  const dueEl = form.elements.due_date;
  const shortcuts = document.createElement('div');
  shortcuts.className = 'flex mt';
  shortcuts.innerHTML = ['Today', 'Tomorrow', 'Next week'].map((l, i) => `<button type="button" class="btn btn-sm" data-days="${[0, 1, 7][i]}">${l}</button>`).join('');
  dueEl.parentElement.appendChild(shortcuts);
  shortcuts.querySelectorAll('button').forEach(b => { b.onclick = () => { const d = new Date(); d.setDate(d.getDate() + Number(b.dataset.days)); dueEl.value = toDateInput(d); }; });

  modal.root.querySelector('[data-act=cancel]').onclick = () => modal.close();
  const del = modal.root.querySelector('[data-act=delete]');
  if (del) del.onclick = async () => {
    if (!(await confirmDialog(`Delete task "${t.title}"?`))) return;
    await tasks.remove(task.id);
    toast('Task deleted');
    modal.close();
    onSaved && onSaved(null);
  };
  const save = async () => {
    const data = formData(form);
    if (!data.title.trim()) { showFormError(form, 'Task title is required.'); return; }
    data.clinic_id = data.clinic_id ? Number(data.clinic_id) : null;
    data.contact_id = data.contact_id ? Number(data.contact_id) : null;
    data.reminder_minutes = data.reminder_minutes ? Number(data.reminder_minutes) : null;
    data.rep = isEdit ? (t.rep || getRepName() || null) : (getRepName() || null);
    if (!isEdit) data.done = false;
    try {
      const saved = isEdit ? await tasks.update(task.id, data) : await tasks.create(data);
      toast(isEdit ? 'Task updated' : 'Task added', 'success');
      modal.close();
      onSaved && onSaved(saved);
    } catch (e) { showFormError(form, e.message); }
  };
  modal.root.querySelector('[data-act=save]').onclick = save;
  form.addEventListener('submit', (e) => { e.preventDefault(); save(); });
  return modal;
}

// ---- Secondary locations ---------------------------------------------------------

export async function openLocationForm({ clinic, location = null, onSaved }) {
  const meta = await getMeta();
  const l = { city: 'Calgary', province: 'AB', ...(location || {}) };
  const isEdit = !!location;
  const modal = openModal({
    title: isEdit ? `Edit location · ${l.name}` : `Add a location for ${clinic.name}`,
    size: 'modal-lg',
    body: `<form id="loc-form" autocomplete="off">
      <p class="small muted">A sister or secondary site of this clinic. It shows on the map with a dashed pin and links back to this profile.</p>
      <div class="field"><label>Location name *</label><input name="name" required value="${attr(l.name)}" placeholder="e.g. ${esc(clinic.shorthand || clinic.name)} South"></div>
      <div class="field"><label>Street address</label>
        <div class="flex"><input name="address" value="${attr(l.address)}" class="grow"><button type="button" class="btn" id="loc-geocode">Find on map</button></div>
        <div class="geocode-results hidden" id="loc-geocode-results"></div></div>
      <div class="field-row">
        <div class="field"><label>City</label><input name="city" value="${attr(l.city)}"></div>
        <div class="field"><label>Province</label><input name="province" value="${attr(l.province)}"></div>
        <div class="field"><label>Postal code</label><input name="postal_code" value="${attr(l.postal_code)}"></div>
        <div class="field"><label>Phone</label><input name="phone" value="${attr(l.phone)}"></div>
      </div>
      <div class="field-row">
        <div class="field"><label>Latitude</label><input name="lat" type="number" step="any" value="${attr(l.lat ?? '')}"></div>
        <div class="field"><label>Longitude</label><input name="lng" type="number" step="any" value="${attr(l.lng ?? '')}"></div>
      </div>
      <div class="help mb">Click the map to place the pin, or drag it.</div>
      <div class="mini-map" id="loc-map"></div>
      <div class="field mt"><label>Notes</label><textarea name="notes" rows="2">${esc(l.notes)}</textarea></div>
    </form>`,
    footer: `${isEdit ? '<button class="btn btn-danger left" data-act="delete">Delete</button>' : ''}<button class="btn" data-act="cancel">Cancel</button><button class="btn btn-primary" data-act="save">${isEdit ? 'Save' : 'Add location'}</button>`,
  });
  const form = modal.body.querySelector('#loc-form');
  const latEl = form.elements.lat, lngEl = form.elements.lng;
  const map = L.map(modal.body.querySelector('#loc-map'));
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }).addTo(map);
  let marker = null;
  const setPin = (lat, lng, pan = true) => {
    latEl.value = Number(lat).toFixed(6); lngEl.value = Number(lng).toFixed(6);
    if (!marker) { marker = L.marker([lat, lng], { draggable: true, icon: pinIcon(clinic.color || 'blue', 'pin-secondary') }).addTo(map); marker.on('dragend', () => { const p = marker.getLatLng(); setPin(p.lat, p.lng, false); }); }
    else marker.setLatLng([lat, lng]);
    if (pan) map.setView([lat, lng], Math.max(map.getZoom(), 14));
  };
  const centre = l.lat != null ? [l.lat, l.lng] : (clinic.lat != null ? [clinic.lat, clinic.lng] : [meta.map_default.lat, meta.map_default.lng]);
  map.setView(centre, l.lat != null || clinic.lat != null ? 13 : meta.map_default.zoom);
  if (clinic.lat != null) L.marker([clinic.lat, clinic.lng], { icon: pinIcon(clinic.color || 'blue'), interactive: false, opacity: 0.6 }).addTo(map);
  if (l.lat != null) setPin(l.lat, l.lng);
  map.on('click', (e) => setPin(e.latlng.lat, e.latlng.lng, false));
  setTimeout(() => map.invalidateSize(), 50);
  const resultsEl = form.querySelector('#loc-geocode-results');
  form.querySelector('#loc-geocode').onclick = async () => {
    const q = [form.elements.address.value, form.elements.city.value, form.elements.province.value, form.elements.postal_code.value].filter(v => v && v.trim()).join(', ');
    if (q.length < 3) { toast('Enter an address first', 'error'); return; }
    resultsEl.classList.remove('hidden'); resultsEl.innerHTML = '<div class="muted">Searching…</div>';
    try {
      const results = await geocode(q);
      if (!results.length) { resultsEl.innerHTML = '<div class="muted">No matches. Click the map to place the pin.</div>'; return; }
      resultsEl.innerHTML = results.map((r, i) => `<div data-i="${i}">${esc(r.display_name)}</div>`).join('');
      resultsEl.querySelectorAll('[data-i]').forEach(el => { el.onclick = () => { const r = results[Number(el.dataset.i)]; setPin(r.lat, r.lng); if (r.postal_code && !form.elements.postal_code.value) form.elements.postal_code.value = r.postal_code; resultsEl.classList.add('hidden'); }; });
    } catch (e) { resultsEl.innerHTML = `<div class="muted">${esc(e.message)}</div>`; }
  };
  modal.root.querySelector('[data-act=cancel]').onclick = () => modal.close();
  const del = modal.root.querySelector('[data-act=delete]');
  if (del) del.onclick = async () => { if (!(await confirmDialog(`Remove location "${l.name}"?`))) return; await locations.remove(clinic.id, location.id); toast('Location removed'); modal.close(); onSaved && onSaved(null); };
  const save = async () => {
    const data = formData(form);
    if (!data.name.trim()) { showFormError(form, 'Name is required.'); return; }
    try {
      const saved = isEdit ? await locations.update(clinic.id, location.id, data) : await locations.create(clinic.id, data);
      toast(isEdit ? 'Location updated' : 'Location added', 'success'); modal.close(); onSaved && onSaved(saved);
    } catch (e) { showFormError(form, e.message); }
  };
  modal.root.querySelector('[data-act=save]').onclick = save;
  form.addEventListener('submit', (e) => { e.preventDefault(); save(); });
}

// ---- Connections between clinics -------------------------------------------------

export async function openLinkForm({ clinic, onSaved }) {
  const meta = await getMeta();
  const list = (await clinicList()).filter(c => c.id !== clinic.id);
  const modal = openModal({
    title: `Connect ${clinic.name} to another clinic`,
    body: `<form id="link-form">
      <div class="field"><label>Other clinic</label>
        <input list="link-clinics" name="other" placeholder="Start typing a clinic name…" required autocomplete="off">
        <datalist id="link-clinics">${list.map(c => `<option value="${attr(c.name)}"></option>`).join('')}</datalist></div>
      <div class="field"><label>How are they connected?</label><select name="link_type">${options(meta.link_types, 'referral')}</select></div>
      <div class="field"><label>Notes</label><textarea name="notes" rows="2" placeholder="e.g. Dr. Lee owns both; the manager moved here from there in 2025"></textarea></div>
    </form>`,
    footer: `<button class="btn" data-act="cancel">Cancel</button><button class="btn btn-primary" data-act="save">Link clinics</button>`,
  });
  const form = modal.body.querySelector('#link-form');
  modal.root.querySelector('[data-act=cancel]').onclick = () => modal.close();
  const save = async () => {
    const data = formData(form);
    const other = list.find(c => c.name.toLowerCase() === data.other.trim().toLowerCase());
    if (!other) { showFormError(form, 'Pick a clinic from the list.'); return; }
    try { await clinics.addLink(clinic.id, { other_clinic_id: other.id, link_type: data.link_type, notes: data.notes }); toast('Clinics linked', 'success'); modal.close(); onSaved && onSaved(); }
    catch (e) { showFormError(form, e.message); }
  };
  modal.root.querySelector('[data-act=save]').onclick = save;
  form.addEventListener('submit', (e) => { e.preventDefault(); save(); });
}

// ---- Quick log (one tap) -----------------------------------------------------------

export async function quickLog(clinic, preset, onSaved) {
  const meta = await getMeta();
  try {
    await clinics.quickLog(clinic.id, preset, getRepName() || null);
    toast(`Logged: ${meta.quick_logs[preset]}`, 'success');
    onSaved && onSaved();
  } catch (e) { toast(e.message, 'error'); }
}

export function quickLogButtons(meta, presets = null) {
  const keys = presets || Object.keys(meta.quick_logs);
  return `<div class="quick-log">${keys.map(k => `<button class="btn btn-sm" data-quick="${k}" title="One tap: adds a dated note">${esc(meta.quick_logs[k])}</button>`).join('')}</div>`;
}

// ---- Email templates -> mailto ---------------------------------------------------------

export async function openEmailPicker({ contact, clinic, anchor, onSent }) {
  const list = await templates.list();
  if (!list.length) { toast('No email templates yet. Add one under Settings.', 'error'); return; }
  document.querySelectorAll('.menu-list').forEach(m => m.remove());
  const menu = document.createElement('div');
  menu.className = 'menu-list';
  menu.innerHTML = list.map(t => `<button data-id="${t.id}">${esc(t.name)}</button>`).join('') + `<button data-id="">Blank email</button>`;
  anchor.parentElement.classList.add('menu');
  anchor.parentElement.appendChild(menu);
  const closeMenu = (e) => { if (!menu.contains(e.target) && e.target !== anchor) { menu.remove(); document.removeEventListener('mousedown', closeMenu); } };
  setTimeout(() => document.addEventListener('mousedown', closeMenu), 0);
  menu.querySelectorAll('button').forEach(b => {
    b.onclick = async () => {
      menu.remove();
      const t = list.find(x => String(x.id) === b.dataset.id);
      const ctx = {
        contact_first_name: contact.first_name, contact_name: `${contact.first_name} ${contact.last_name || ''}`.trim(),
        clinic_name: clinic.name, shorthand: clinic.shorthand || clinic.name, rep_name: getRepName() || 'ChinookIT',
      };
      const subject = t ? fillTemplate(t.subject, ctx) : '';
      const body = t ? fillTemplate(t.body, ctx) : '';
      window.location.href = mailtoUrl(contact.email, subject, body);
      try {
        await clinics.addNote(clinic.id, `Emailed ${ctx.contact_name}${t ? `: ${t.name}` : ''}${subject ? ` — "${subject}"` : ''}`, 'email');
        onSent && onSent();
      } catch { /* ignore */ }
    };
  });
}

export const debouncedSearch = debounce;
