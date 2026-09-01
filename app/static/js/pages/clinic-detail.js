// Clinic profile: details, note log, contacts, appointments, mini map.
import { clinics, appointments, getMeta } from '../api.js';
import {
  esc, attr, dot, badge, tagList, fmtDate, fmtDateTime, fmtDateOnly, relativeDays, isPast,
  fullAddress, directionsUrl, pinIcon, toast, confirmDialog, navigate, setTitle,
} from '../ui.js';
import { openClinicForm, deleteClinic, openContactForm, openAppointmentForm, openLogVisit } from '../forms.js';

let miniMap = null;

export async function render(container, params, routeParams) {
  const id = Number(routeParams.id);
  let clinic;
  try { clinic = await clinics.get(id); }
  catch (e) { container.innerHTML = `<div class="card empty">Clinic not found. <a href="#/clinics">Back to clinics</a></div>`; return; }
  const meta = await getMeta();
  setTitle(clinic.name);
  const reload = () => render(container, params, routeParams);

  const upcoming = clinic.appointments.filter(a => a.status === 'scheduled' && !isPast(a.start_time)).sort((a, b) => a.start_time.localeCompare(b.start_time));
  const past = clinic.appointments.filter(a => !(a.status === 'scheduled' && !isPast(a.start_time)));
  const today = new Date().toISOString().slice(0, 10);

  container.innerHTML = `
    <div class="mb"><a href="#/clinics">← All clinics</a></div>
    <div class="card">
      <div class="clinic-header">
        <div class="grow">
          <div class="title">
            ${dot(clinic.color, clinic.color_label, true)}
            <h1>${esc(clinic.name)}</h1>
            <span class="badge badge-${esc(clinic.color)}">${esc(clinic.color_label)}</span>
            ${clinic.relationship_label !== clinic.color_label ? badge(clinic.relationship_label) : ''}
            ${badge(`${clinic.priority} priority`, `badge-${clinic.priority}`)}
          </div>
          <div class="meta">
            <span>${esc(fullAddress(clinic)) || 'No address on file'}</span>
            ${clinic.phone ? `<span>☎ <a href="tel:${attr(clinic.phone)}">${esc(clinic.phone)}</a></span>` : ''}
            ${clinic.email ? `<span>✉ <a href="mailto:${attr(clinic.email)}">${esc(clinic.email)}</a></span>` : ''}
            ${clinic.website ? `<span><a href="${attr(clinic.website)}" target="_blank" rel="noopener">Website</a></span>` : ''}
          </div>
        </div>
        <div class="actions flex flex-wrap">
          <button class="btn btn-primary" id="btn-appt">+ Appointment</button>
          <button class="btn" id="btn-visit">Log a visit</button>
          <button class="btn" id="btn-contact">+ Contact</button>
          ${clinic.lat != null ? `<a class="btn" href="#/map?focus=${clinic.id}">Show on map</a>` : ''}
          <a class="btn" href="${attr(directionsUrl(clinic))}" target="_blank" rel="noopener">Directions</a>
          <button class="btn" id="btn-edit">Edit</button>
          <button class="btn btn-danger" id="btn-delete">Delete</button>
        </div>
      </div>
    </div>

    <div class="grid-2 mt">
      <div>
        <div class="card">
          <div class="card-header"><h3>Details</h3></div>
          <dl class="kv">
            <dt>Clinic type</dt><dd>${esc(clinic.clinic_type || '—')}</dd>
            <dt>EMR system</dt><dd>${esc(clinic.emr_system || '—')}</dd>
            <dt>Current IT provider</dt><dd>${esc(clinic.it_provider || '—')}</dd>
            <dt>Providers</dt><dd>${clinic.provider_count ?? '—'}</dd>
            <dt>Fax</dt><dd>${esc(clinic.fax || '—')}</dd>
            <dt>Tags</dt><dd>${clinic.tag_list.length ? tagList(clinic.tag_list) : '—'}</dd>
            <dt>Last visit</dt><dd>${clinic.last_visit ? `${esc(fmtDateTime(clinic.last_visit))} <span class="muted">(${esc(relativeDays(clinic.last_visit))})</span>` : 'Never visited'}</dd>
            <dt>Next appointment</dt><dd>${clinic.next_appointment ? `${esc(fmtDateTime(clinic.next_appointment.start_time))} · ${esc(clinic.next_appointment.title)}` : '—'}</dd>
            <dt>Next follow-up</dt><dd>${clinic.next_follow_up ? `${esc(fmtDateOnly(clinic.next_follow_up))} ${clinic.next_follow_up < today ? badge('Overdue', 'badge-red') : ''}` : '—'}</dd>
            <dt>Added</dt><dd>${esc(fmtDate(clinic.created_at))}</dd>
          </dl>
        </div>

        <div class="card">
          <div class="card-header"><h3>General notes</h3><div class="actions"><button class="btn btn-sm" id="btn-edit-notes">Edit</button></div></div>
          ${clinic.notes ? `<pre class="wrap">${esc(clinic.notes)}</pre>` : '<p class="muted">No general notes yet.</p>'}
        </div>

        <div class="card">
          <div class="card-header"><h3>Note log</h3><span class="muted small">Dated entries: calls, conversations, observations</span></div>
          <form id="note-form" class="mb">
            <textarea name="body" rows="2" placeholder="Add a note… (e.g. Called, spoke with receptionist, manager back Tuesday)"></textarea>
            <div class="right mt"><button class="btn btn-primary btn-sm" type="submit">Add note</button></div>
          </form>
          <div id="note-log">
            ${clinic.note_log.length ? clinic.note_log.map(n => `
              <div class="note-entry" data-id="${n.id}">
                <div class="note-meta"><span>${esc(fmtDateTime(n.created_at))}</span>${n.author ? `<span>· ${esc(n.author)}</span>` : ''}
                  <span class="actions"><button class="btn btn-link btn-sm" data-act="del-note" data-id="${n.id}">Delete</button></span></div>
                <pre class="wrap">${esc(n.body)}</pre>
              </div>`).join('') : '<p class="muted">No log entries yet.</p>'}
          </div>
        </div>
      </div>

      <div>
        <div class="card">
          <div class="card-header"><h3>Contacts (${clinic.contacts.length})</h3><div class="actions"><button class="btn btn-sm" id="btn-contact-2">+ Add</button></div></div>
          ${clinic.contacts.length ? clinic.contacts.map(ct => `
            <div class="contact-row">
              <div class="body">
                <div class="name">${ct.is_primary ? '<span class="star" title="Primary contact">★</span> ' : ''}${esc(ct.first_name)} ${esc(ct.last_name || '')} <span class="badge">${esc(meta.contact_roles[ct.role] || ct.role)}</span></div>
                <div class="sub">${[ct.title, ct.phone ? `☎ ${ct.phone}` : null, ct.mobile ? `📱 ${ct.mobile}` : null, ct.email].filter(Boolean).map(esc).join(' · ')}</div>
                ${ct.notes ? `<div class="sub">${esc(ct.notes)}</div>` : ''}
              </div>
              <div class="actions"><button class="btn btn-sm" data-act="edit-contact" data-id="${ct.id}">Edit</button></div>
            </div>`).join('') : '<p class="muted">No contacts yet. Add the clinic manager, doctors, reception staff…</p>'}
        </div>

        <div class="card">
          <div class="card-header"><h3>Upcoming appointments (${upcoming.length})</h3><div class="actions"><button class="btn btn-sm" id="btn-appt-2">+ New</button></div></div>
          ${upcoming.length ? upcoming.map(a => apptRow(a, meta)).join('') : '<p class="muted">Nothing scheduled. Create an appointment to plan your next visit.</p>'}
        </div>

        <div class="card">
          <div class="card-header"><h3>Past appointments (${past.length})</h3></div>
          ${past.length ? past.map(a => apptRow(a, meta)).join('') : '<p class="muted">No past appointments or visits logged.</p>'}
        </div>

        <div class="card">
          <div class="card-header"><h3>Location</h3>
            <div class="actions">${clinic.lat != null ? `<span class="muted small">${clinic.lat.toFixed(5)}, ${clinic.lng.toFixed(5)}</span>` : ''}</div></div>
          ${clinic.lat != null
            ? `<div class="mini-map small" id="mini-map"></div><div class="help mt">Drag the pin to correct the location.</div>`
            : `<p class="muted">Not on the map yet. <button class="btn btn-sm" id="btn-locate">Set location</button></p>`}
        </div>
      </div>
    </div>`;

  // Wire actions
  const editClinic = () => openClinicForm({ clinic, onSaved: reload });
  container.querySelector('#btn-edit').onclick = editClinic;
  container.querySelector('#btn-edit-notes').onclick = editClinic;
  const locate = container.querySelector('#btn-locate');
  if (locate) locate.onclick = editClinic;
  container.querySelector('#btn-delete').onclick = async () => { if (await deleteClinic(clinic)) navigate('#/clinics'); };
  const newAppt = () => openAppointmentForm({ clinicId: clinic.id, lockClinic: true, onSaved: reload });
  container.querySelector('#btn-appt').onclick = newAppt;
  container.querySelector('#btn-appt-2').onclick = newAppt;
  const newContact = () => openContactForm({ clinicId: clinic.id, onSaved: reload });
  container.querySelector('#btn-contact').onclick = newContact;
  container.querySelector('#btn-contact-2').onclick = newContact;
  container.querySelector('#btn-visit').onclick = () => openLogVisit({ clinic, onSaved: reload });

  container.querySelectorAll('[data-act=edit-contact]').forEach(b => {
    b.onclick = () => openContactForm({ contact: clinic.contacts.find(c => c.id === Number(b.dataset.id)), onSaved: reload });
  });
  container.querySelectorAll('[data-act=edit-appt]').forEach(b => {
    b.onclick = () => openAppointmentForm({ appointment: clinic.appointments.find(a => a.id === Number(b.dataset.id)), lockClinic: true, onSaved: reload });
  });
  container.querySelectorAll('[data-act=complete]').forEach(b => {
    b.onclick = async () => { await appointments.patch(Number(b.dataset.id), { status: 'completed' }); toast('Marked completed', 'success'); reload(); };
  });
  container.querySelectorAll('[data-act=del-note]').forEach(b => {
    b.onclick = async () => {
      if (!(await confirmDialog('Delete this note?'))) return;
      await clinics.removeNote(clinic.id, Number(b.dataset.id));
      reload();
    };
  });
  const noteForm = container.querySelector('#note-form');
  noteForm.onsubmit = async (e) => {
    e.preventDefault();
    const body = noteForm.elements.body.value.trim();
    if (!body) return;
    await clinics.addNote(clinic.id, body);
    toast('Note added', 'success');
    reload();
  };

  // Mini map
  const mapEl = container.querySelector('#mini-map');
  if (mapEl) {
    if (miniMap) { miniMap.remove(); miniMap = null; }
    miniMap = L.map(mapEl, { scrollWheelZoom: false }).setView([clinic.lat, clinic.lng], 15);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }).addTo(miniMap);
    const m = L.marker([clinic.lat, clinic.lng], { draggable: true, icon: pinIcon(clinic.color) }).addTo(miniMap);
    m.on('dragend', async () => {
      const p = m.getLatLng();
      await clinics.setLocation(clinic.id, p.lat, p.lng);
      toast('Location updated', 'success');
    });
    setTimeout(() => miniMap.invalidateSize(), 50);
  }
}

export function destroy() {
  if (miniMap) { miniMap.remove(); miniMap = null; }
}

function apptRow(a, meta) {
  const overdue = a.status === 'scheduled' && isPast(a.start_time);
  return `
    <div class="appt-row">
      <div class="when">${esc(fmtDateTime(a.start_time))}<div>${esc(relativeDays(a.start_time))}</div></div>
      <div class="body">
        <div class="title">${esc(a.title)} <span class="badge">${esc(meta.appointment_types[a.appt_type] || a.appt_type)}</span> <span class="badge badge-${esc(a.status)}">${esc(meta.appointment_statuses[a.status] || a.status)}</span></div>
        ${a.contact_first_name ? `<div class="muted small">With ${esc(a.contact_first_name)} ${esc(a.contact_last_name || '')}</div>` : ''}
        ${a.location ? `<div class="muted small">📍 ${esc(a.location)}</div>` : ''}
        ${a.notes ? `<div class="small"><strong>Plan:</strong> ${esc(a.notes)}</div>` : ''}
        ${a.outcome ? `<div class="small"><strong>Outcome:</strong> ${esc(a.outcome)}</div>` : ''}
        ${overdue ? `<div class="small muted">This appointment is in the past but still marked scheduled.</div>` : ''}
      </div>
      <div class="actions">
        ${overdue ? `<button class="btn btn-sm" data-act="complete" data-id="${a.id}">Mark done</button>` : ''}
        <button class="btn btn-sm" data-act="edit-appt" data-id="${a.id}">Edit</button>
      </div>
    </div>`;
}
