// Clinic profile: deal, details, locations, connections, attachments, activity timeline,
// tasks, contacts, appointments, mini map. Clients get a slimmer, client-specific view.
import { clinics, appointments, attachments, getMeta } from '../api.js';
import {
  esc, attr, dot, badge, tagList, fmtDate, fmtDateTime, fmtDateOnly, fmtMoney, relativeDays, isPast,
  fullAddress, directionsUrl, pinIcon, secondaryPinIcon, toast, confirmDialog, navigate, setTitle, options,
  stageBadge, shorthandBadge, getRepName,
} from '../ui.js';
import {
  openClinicForm, deleteClinic, openContactForm, openAppointmentForm, openLogVisit, openTaskForm, changeStage,
  openLocationForm, openLinkForm, quickLog, quickLogButtons, openEmailPicker, openCardScanner,
} from '../forms.js';
import { taskRow, wireTaskRows } from './tasks.js';
import { openDeviceForm, plural } from '../equipment.js';
import { devices as devicesApi } from '../api.js';
import { openInvoiceForm } from '../billing-forms.js';

let miniMap = null;
let tlFilter = 'all';

function renewalBadge(c) {
  if (c.renewal_overdue) return badge('Expired', 'badge-red');
  if (c.days_to_renewal != null && c.days_to_renewal <= 30) return badge(`Renews in ${c.days_to_renewal}d`, 'badge-high');
  if (c.renewal_due) return badge(`Renews in ${c.days_to_renewal}d`, 'badge-yellow');
  return '';
}

function competitorBadge(c) {
  if (c.competitor_days == null) return '';
  if (c.competitor_days < 0) return badge('Contract ended', 'badge-red');
  if (c.displacement_hot) return badge(`${c.competitor_days}d left`, 'badge-high');
  return badge(`${c.competitor_days}d`, 'badge-grey');
}

function contractSummary(c) {
  if (!c.contract_start && !c.contract_end && !c.contract_term_months) return '<span class="muted">— none recorded</span>';
  const range = [c.contract_start ? fmtDateOnly(c.contract_start) : '?', c.contract_end ? fmtDateOnly(c.contract_end) : '?'].join(' → ');
  return esc(range) + (c.contract_term_months ? ` <span class="muted">(${c.contract_term_months} mo)</span>` : '');
}

export async function render(container, params, routeParams) {
  const id = Number(routeParams.id);
  let clinic;
  try { clinic = await clinics.get(id); }
  catch (e) { container.innerHTML = `<div class="card empty">Clinic not found. <a href="#/clinics">Back to clinics</a></div>`; return; }
  const meta = await getMeta();
  setTitle(clinic.shorthand ? `${clinic.shorthand} · ${clinic.name}` : clinic.name);
  const reload = () => render(container, params, routeParams);

  const upcoming = clinic.appointments.filter(a => a.status === 'scheduled' && !isPast(a.start_time)).sort((a, b) => a.start_time.localeCompare(b.start_time));
  const past = clinic.appointments.filter(a => !(a.status === 'scheduled' && !isPast(a.start_time)));
  const today = new Date().toISOString().slice(0, 10);
  const openTasks = clinic.tasks.filter(t => !t.done);
  const isClient = clinic.is_client;
  const isLead = clinic.stage === 'lead';
  const closed = clinic.stage === 'won' || clinic.stage === 'lost';
  const reasonLabel = closed && clinic.outcome_reason ? ((clinic.stage === 'won' ? meta.won_reasons : meta.lost_reasons)[clinic.outcome_reason] || clinic.outcome_reason) : null;
  const photos = clinic.attachments.filter(a => a.kind === 'photo');
  const docs = clinic.attachments.filter(a => a.kind !== 'photo');

  container.innerHTML = `
    <div class="mb"><a href="#/clinics">← All clinics</a> · <a href="#/pipeline">Pipeline</a></div>
    <div class="card">
      <div class="clinic-header">
        <div class="grow">
          <div class="title">
            ${dot(clinic.color, clinic.color_label, true)}
            ${shorthandBadge(clinic)}
            <h1>${esc(clinic.name)}</h1>
            <span class="badge badge-${esc(clinic.color)}">${esc(clinic.color_label)}</span>
            ${clinic.relationship_label !== clinic.color_label ? badge(clinic.relationship_label) : ''}
            ${!isClient ? stageBadge(clinic) : ''}
            ${!isClient ? badge(`${clinic.priority} priority`, `badge-${clinic.priority}`) : ''}
            ${clinic.archived ? badge('Off the board', 'badge-grey') : ''}
          </div>
          <div class="meta">
            <span>${esc(fullAddress(clinic)) || 'No address on file'}</span>
            ${clinic.phone ? `<span>☎ <a href="tel:${attr(clinic.phone)}">${esc(clinic.phone)}</a></span>` : ''}
            ${clinic.email ? `<span>✉ <a href="mailto:${attr(clinic.email)}">${esc(clinic.email)}</a></span>` : ''}
            ${clinic.website ? `<span><a href="${attr(clinic.website)}" target="_blank" rel="noopener">Website</a></span>` : ''}
            ${isClient && clinic.outcome_date ? `<span class="client-since">Client since ${esc(fmtDateOnly(clinic.outcome_date))}</span>` : ''}
            ${clinic.group ? `<span>Part of <strong>${esc(clinic.group.name)}</strong></span>` : ''}
            ${clinic.locations.length ? `<span>${clinic.locations.length + 1} locations</span>` : ''}
          </div>
        </div>
        <div class="actions flex flex-wrap">
          <button class="btn btn-primary" id="btn-appt">+ Appointment</button>
          ${!isClient ? '<button class="btn" id="btn-visit">Log a visit</button>' : ''}
          <button class="btn" id="btn-task">+ Task</button>
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
          <div class="card-header"><h3>${isClient ? 'Client' : (isLead ? 'Lead' : 'Deal')}</h3>
            <div class="actions">
              ${isLead ? `<button class="btn btn-sm btn-primary" id="btn-promote" title="Move this lead onto the pipeline board as Interested">Add to pipeline →</button>` : ''}
              ${isClient && clinic.stage === 'won' ? `<button class="btn btn-sm" id="btn-archive" title="${clinic.archived ? 'Show again on the pipeline board' : 'Hide from the Won column on the pipeline board'}">${clinic.archived ? 'Restore to board' : 'Dismiss from board'}</button>` : ''}
              <select class="stage-select" id="stage-move" title="Move to stage">${options(meta.stages, clinic.stage)}</select>
              <button class="btn btn-sm" id="btn-edit-deal">Edit</button>
            </div>
          </div>
          ${isLead ? '<p class="help mb">This clinic is a lead — added to your book but not yet contacted. It stays off the pipeline board until you add it as Interested.</p>' : ''}
          <dl class="kv">
            ${isClient ? `
            <dt>Shorthand</dt><dd>${clinic.shorthand ? shorthandBadge(clinic) : '<span class="muted">— set one under Edit</span>'}</dd>
            <dt>Client since</dt><dd>${clinic.outcome_date ? esc(fmtDateOnly(clinic.outcome_date)) : '<span class="muted">— set the onboarding date under Edit</span>'}</dd>
            <dt>Monthly revenue</dt><dd class="money">${clinic.mrr ? `${fmtMoney(clinic.mrr)}/mo` : '<span class="muted">— set MRR under Edit</span>'}</dd>
            <dt>Annual value</dt><dd class="money">${clinic.mrr ? fmtMoney(clinic.arr) : (clinic.deal_value ? fmtMoney(clinic.deal_value) : '—')}</dd>
            <dt>Contract</dt><dd>${contractSummary(clinic)}</dd>
            <dt>Renewal</dt><dd>${clinic.contract_end ? `${esc(fmtDateOnly(clinic.contract_end))} ${renewalBadge(clinic)}${clinic.auto_renew ? ' ' + badge('Auto-renew', 'badge-grey') : ''}` : '<span class="muted">— no end date set</span>'}</dd>
            <dt>How we won</dt><dd>${reasonLabel ? esc(reasonLabel) : '—'}</dd>
            ${clinic.outcome_notes ? `<dt>Notes</dt><dd><pre class="wrap">${esc(clinic.outcome_notes)}</pre></dd>` : ''}` : `
            <dt>Stage</dt><dd>${stageBadge(clinic)}</dd>
            <dt>Est. annual value</dt><dd class="money">${clinic.deal_value ? fmtMoney(clinic.deal_value) : '—'}</dd>
            ${clinic.competitor_contract_end ? `<dt>Competitor contract ends</dt><dd>${esc(fmtDateOnly(clinic.competitor_contract_end))} ${competitorBadge(clinic)}</dd>` : ''}
            ${!closed ? `<dt>Win probability</dt><dd>${clinic.effective_probability}%${clinic.win_probability == null ? ' <span class="muted">(stage default)</span>' : ''}</dd>
            <dt>Weighted value</dt><dd class="money">${clinic.weighted_value ? fmtMoney(clinic.weighted_value) : '—'}</dd>
            <dt>Expected close</dt><dd>${clinic.expected_close ? `${esc(fmtDateOnly(clinic.expected_close))} ${clinic.expected_close < today ? badge('Slipped', 'badge-red') : ''}` : '—'}</dd>` : `
            <dt>${clinic.stage === 'won' ? 'Won' : 'Lost'} on</dt><dd>${clinic.outcome_date ? esc(fmtDateOnly(clinic.outcome_date)) : '—'}</dd>
            <dt>Reason</dt><dd>${reasonLabel ? esc(reasonLabel) : '—'}</dd>
            ${clinic.outcome_notes ? `<dt>Outcome notes</dt><dd><pre class="wrap">${esc(clinic.outcome_notes)}</pre></dd>` : ''}`}`}
          </dl>
        </div>

        <div class="card">
          <div class="card-header"><h3>Details</h3></div>
          <dl class="kv">
            <dt>Clinic type</dt><dd>${esc(clinic.clinic_type || '—')}</dd>
            <dt>EMR system</dt><dd>${esc(clinic.emr_system || '—')}</dd>
            <dt>${isClient ? 'Previous IT provider' : 'Current IT provider'}</dt><dd>${esc(clinic.it_provider || '—')}</dd>
            <dt>Providers</dt><dd>${clinic.provider_count ?? '—'}</dd>
            <dt>Fax</dt><dd>${esc(clinic.fax || '—')}</dd>
            <dt>Tags</dt><dd>${clinic.tag_list.length ? tagList(clinic.tag_list) : '—'}</dd>
            ${!isClient ? `<dt>Last visit</dt><dd>${clinic.last_visit ? `${esc(fmtDateTime(clinic.last_visit))} <span class="muted">(${esc(relativeDays(clinic.last_visit))})</span>` : 'Never visited'}</dd>` : ''}
            <dt>Next appointment</dt><dd>${clinic.next_appointment ? `${esc(fmtDateTime(clinic.next_appointment.start_time))} · ${esc(clinic.next_appointment.title)}` : '—'}</dd>
            <dt>Next follow-up</dt><dd>${clinic.next_follow_up ? `${esc(fmtDateOnly(clinic.next_follow_up))} ${clinic.next_follow_up < today ? badge('Overdue', 'badge-red') : ''}` : '—'}</dd>
            <dt>Added</dt><dd>${esc(fmtDate(clinic.created_at))}</dd>
          </dl>
        </div>

        <div class="card">
          <div class="card-header"><h3>Equipment (${clinic.equipment.total})</h3>
            <div class="actions"><button class="btn btn-sm" id="btn-device">+ Device</button><a class="btn btn-sm" href="#/clinics/${clinic.id}/equipment">Manage</a><a class="btn btn-sm btn-primary" href="#/clinics/${clinic.id}/quote" title="Build a monthly services quote from this equipment">💲 Generate quote</a></div></div>
          <div id="equip-chips">${Object.values(clinic.equipment.by_type).length
            ? Object.values(clinic.equipment.by_type).map(b => `<span class="type-chip ${b.active ? '' : 'muted'}">${esc(b.icon)} ${esc(plural(b.label, b.total))} <span class="n">${b.active}${b.total !== b.active ? `/${b.total}` : ''}</span></span>`).join('')
            : '<p class="muted">No equipment recorded. Add the firewall/router first, then the switch, then everything plugged into it.</p>'}</div>
          ${clinic.equipment.total ? `<div class="muted small mt">${clinic.equipment.billable.workstations} workstations/laptops · ${clinic.equipment.billable.servers} servers · ${clinic.equipment.billable.network} network · ${clinic.equipment.billable.phones} phones · ${clinic.equipment.billable.printers} printers · <a href="#/clinics/${clinic.id}/equipment?view=topology">topology</a></div>` : ''}
        </div>

        <div class="card">
          <div class="card-header"><h3>Quotes (${clinic.quotes.length})</h3><div class="actions"><a class="btn btn-sm" href="#/clinics/${clinic.id}/quote">+ New quote</a></div></div>
          ${clinic.quotes.length ? clinic.quotes.map(q => `
            <div class="loc-row"><div class="body"><div class="name"><a href="#/quotes/${q.id}">${esc(q.number)}</a> · ${esc(q.title)} <span class="badge stamp-${esc(q.status)}" style="border:none;background:var(--surface-3)">${esc(q.status)}</span></div>
              <div class="sub money">${fmtMoney(q.monthly_total)}/month${q.onetime_total ? ` + ${fmtMoney(q.onetime_total)} one-time` : ''} · ${esc(fmtDate(q.created_at))}${q.valid_until ? ` · valid until ${esc(fmtDateOnly(q.valid_until))}` : ''}</div></div>
              <div class="actions"><a class="btn btn-sm" href="#/quotes/${q.id}">Open</a></div></div>`).join('') : '<p class="muted">No quotes yet. Map the equipment, then click “Generate quote”.</p>'}
        </div>

        <div class="card">
          <div class="card-header"><h3>Invoices (${(clinic.invoices || []).length})</h3><div class="actions"><button class="btn btn-sm" id="btn-invoice">+ New invoice</button></div></div>
          ${(clinic.invoices || []).length ? clinic.invoices.map(iv => `
            <div class="loc-row"><div class="body"><div class="name"><a href="#/invoices/${iv.id}">${esc(iv.number)}</a>${iv.title ? ` · ${esc(iv.title)}` : ''} <span class="badge badge-stage-${iv.status === 'paid' ? 'won' : (iv.status === 'void' ? 'lost' : (iv.status === 'sent' ? 'proposal' : 'lead'))}">${esc(iv.status)}</span>${iv.ticket_url ? ` <a href="${attr(iv.ticket_url)}" target="_blank" rel="noopener" title="Ticket">🎫</a>` : ''}</div>
              <div class="sub money">${fmtMoney(iv.total)}${iv.issue_date ? ` · ${esc(fmtDateOnly(iv.issue_date))}` : ''}${iv.due_date ? ` · due ${esc(fmtDateOnly(iv.due_date))}` : ''}</div></div>
              <div class="actions"><a class="btn btn-sm" href="#/invoices/${iv.id}">Open</a></div></div>`).join('') : '<p class="muted">No invoices yet. Bill toner, hardware or on-site work with “+ New invoice”.</p>'}
        </div>

        <div class="card">
          <div class="card-header"><h3>Locations (${clinic.locations.length + 1})</h3><div class="actions"><button class="btn btn-sm" id="btn-location">+ Location</button></div></div>
          <div class="loc-row">
            <div class="body"><div class="name">${dot(clinic.color)}${esc(clinic.name)} <span class="badge badge-blue">Main</span></div><div class="sub">${esc(fullAddress(clinic)) || 'No address'}${clinic.lat == null ? ' · <em>not on map</em>' : ''}</div></div>
          </div>
          ${clinic.locations.map(l => `
            <div class="loc-row" data-id="${l.id}">
              <div class="body"><div class="name"><span class="dot dot-${esc(clinic.color)}" style="border-style:dashed"></span>${esc(l.name)} <span class="badge">Secondary</span></div>
                <div class="sub">${esc([l.address, l.city, l.postal_code].filter(Boolean).join(', ')) || 'No address'}${l.phone ? ` · ☎ ${esc(l.phone)}` : ''}${l.lat == null ? ' · <em>not on map</em>' : ''}</div>
                ${l.notes ? `<div class="sub">${esc(l.notes)}</div>` : ''}</div>
              <div class="actions">${l.lat != null ? `<a class="btn btn-sm" href="https://www.google.com/maps/dir/?api=1&destination=${l.lat},${l.lng}" target="_blank" rel="noopener">Directions</a>` : ''}<button class="btn btn-sm" data-act="edit-loc" data-id="${l.id}">Edit</button></div>
            </div>`).join('')}
        </div>

        <div class="card">
          <div class="card-header"><h3>Connections (${clinic.links.length})</h3><div class="actions"><button class="btn btn-sm" id="btn-link">+ Link clinic</button></div></div>
          ${clinic.group ? `<div class="loc-row"><div class="body"><div class="name">Group: ${esc(clinic.group.name)}</div>
            <div class="sub">${clinic.group_members.length ? clinic.group_members.map(m => `${dot(m.color)}<a href="#/clinics/${m.id}">${esc(m.name)}</a>${m.shorthand ? ` (${esc(m.shorthand)})` : ''}`).join(' · ') : 'No other clinics in this group yet'}</div></div>
            <div class="actions"><a class="btn btn-sm" href="#/settings">Manage</a></div></div>` : ''}
          ${clinic.links.length ? clinic.links.map(l => `
            <div class="loc-row" data-id="${l.id}">
              <div class="body"><div class="name">${dot(l.other.color)}<a href="#/clinics/${l.other.id}">${esc(l.other.name)}</a>${l.other.shorthand ? ` <span class="badge badge-shorthand">${esc(l.other.shorthand)}</span>` : ''} <span class="badge badge-purple">${esc(l.link_label)}</span></div>
                <div class="sub">${esc(l.notes || l.other.address || '')}</div></div>
              <div class="actions"><button class="btn btn-sm btn-link" data-act="del-link" data-id="${l.id}">Unlink</button></div>
            </div>`).join('') : (clinic.group ? '' : '<p class="muted">Link clinics that share an owner, a building, or a manager who moved. Landing one often opens the others.</p>')}
        </div>

        <div class="card">
          <div class="card-header"><h3>General notes</h3><div class="actions"><button class="btn btn-sm" id="btn-edit-notes">Edit</button></div></div>
          ${clinic.notes ? `<pre class="wrap">${esc(clinic.notes)}</pre>` : '<p class="muted">No general notes yet.</p>'}
        </div>
      </div>

      <div>
        <div class="card">
          <div class="card-header"><h3>Activity</h3><span class="muted small">Notes, visits, tasks and status changes in one feed</span></div>
          ${quickLogButtons(meta)}
          <form id="note-form" class="mb">
            <textarea name="body" rows="2" placeholder="Add a note… (e.g. Called, spoke with receptionist, manager back Tuesday)"></textarea>
            <div class="right mt"><button class="btn btn-primary btn-sm" type="submit">Add note</button></div>
          </form>
          <div class="tl-filters" id="tl-filters">
            ${[['all', 'All'], ['note', 'Notes'], ['appointment', 'Appointments'], ['task', 'Tasks'], ['change', 'Changes']].map(([k, l]) =>
              `<button class="btn btn-sm ${tlFilter === k ? 'active' : ''}" data-filter="${k}">${l}</button>`).join('')}
          </div>
          <ul class="timeline" id="timeline"></ul>
        </div>

        <div class="card">
          <div class="card-header"><h3>Tasks (${openTasks.length} open)</h3><div class="actions"><button class="btn btn-sm" id="btn-task-2">+ Add</button></div></div>
          <div id="task-list">${openTasks.length ? openTasks.map(taskRow).join('') : '<p class="muted">No open tasks. Add a reminder like “Call back Friday”.</p>'}</div>
        </div>

        <div class="card">
          <div class="card-header"><h3>Contacts (${clinic.contacts.length})</h3><div class="actions"><button class="btn btn-sm" id="btn-scan-card" title="Photograph a business card and let AI fill in the contact">📇 Scan card</button><button class="btn btn-sm" id="btn-contact-2">+ Add</button></div></div>
          ${clinic.contacts.length ? clinic.contacts.map(ct => `
            <div class="contact-row" data-id="${ct.id}">
              <div class="body">
                <div class="name">${ct.is_primary ? '<span class="star" title="Primary contact">★</span> ' : ''}${esc(ct.first_name)} ${esc(ct.last_name || '')} <span class="badge">${esc(meta.contact_roles[ct.role] || ct.role)}</span>${ct.shared ? ' <span class="badge badge-purple" title="Shared across the clinic group">Group</span>' : ''}</div>
                <div class="sub">${[ct.title, ct.phone_display ? `☎ ${ct.phone_display}` : null, ct.mobile ? `📱 ${ct.mobile}` : null, ct.email].filter(Boolean).map(esc).join(' · ')}</div>
                ${ct.notes ? `<div class="sub">${esc(ct.notes)}</div>` : ''}
              </div>
              <div class="actions">
                ${ct.email ? `<span class="menu"><button class="btn btn-sm" data-act="email" data-id="${ct.id}">Email ▾</button></span>` : ''}
                ${!ct.shared || ct.clinic_id === clinic.id ? `<button class="btn btn-sm" data-act="edit-contact" data-id="${ct.id}">Edit</button>` : `<a class="btn btn-sm" href="#/clinics/${ct.clinic_id}">Via ${esc(ct.clinic_name || 'group')}</a>`}
              </div>
            </div>`).join('') : '<p class="muted">No contacts yet. Add the clinic manager, doctors, reception staff…</p>'}
        </div>

        <div class="card">
          <div class="card-header"><h3>Upcoming appointments (${upcoming.length})</h3><div class="actions"><button class="btn btn-sm" id="btn-appt-2">+ New</button></div></div>
          ${upcoming.length ? upcoming.map(a => apptRow(a, meta)).join('') : '<p class="muted">Nothing scheduled.</p>'}
        </div>

        <div class="card">
          <div class="card-header"><h3>Past appointments (${past.length})</h3></div>
          ${past.length ? past.slice(0, 8).map(a => apptRow(a, meta)).join('') : '<p class="muted">No past appointments or visits logged.</p>'}
          ${past.length > 8 ? `<p class="muted small mt">${past.length - 8} older appointments are in the activity feed.</p>` : ''}
        </div>

        <div class="card">
          <div class="card-header"><h3>Documents (${docs.length})</h3>
            <div class="actions"><label class="btn btn-sm" style="margin:0">Upload… <input type="file" id="doc-file" class="hidden" multiple accept=".pdf,.doc,.docx,.xls,.xlsx,.txt,.csv,image/*"></label></div></div>
          ${docs.length ? docs.map(d => `
            <div class="doc-row" data-id="${d.id}">
              <span>📄</span>
              <div class="body"><a href="${attachments.fileUrl(d.id)}" target="_blank" rel="noopener">${esc(d.filename)}</a>${d.caption ? ` <span class="muted">· ${esc(d.caption)}</span>` : ''}
                <div class="sub">${fmtSize(d.size)} · ${esc(fmtDate(d.created_at))}</div></div>
              <a class="btn btn-sm" href="${attachments.fileUrl(d.id, true)}">Download</a>
              <button class="btn btn-sm btn-link" data-act="del-att" data-id="${d.id}">Delete</button>
            </div>`).join('') : '<p class="muted">Proposals, quotes, signed contracts… up to 25 MB each.</p>'}
        </div>

        <div class="card">
          <div class="card-header"><h3>Photos (${photos.length})</h3>
            <div class="actions">
              <label class="btn btn-sm" style="margin:0">📷 Take photo <input type="file" id="photo-capture" class="hidden" accept="image/*" capture="environment"></label>
              <label class="btn btn-sm" style="margin:0">Upload… <input type="file" id="photo-file" class="hidden" accept="image/*" multiple></label>
            </div></div>
          ${photos.length ? `<div class="photo-grid">${photos.map(p => `
            <a href="${attachments.fileUrl(p.id)}" target="_blank" rel="noopener" data-id="${p.id}" title="${attr(p.caption || p.filename)}">
              <img src="${attachments.fileUrl(p.id)}" alt="${attr(p.caption || p.filename)}" loading="lazy">
              <span class="cap">${esc(p.caption || p.filename)}</span>
            </a>`).join('')}</div>
            <div class="mt small muted">Right-click a photo to delete it, or use the list: ${photos.map(p => `<button class="btn btn-link btn-sm" data-act="del-att" data-id="${p.id}">delete ${esc(p.caption || p.filename)}</button>`).join(' ')}</div>`
            : '<p class="muted">Storefront, parking, a business card… Photos taken on a phone are attached straight to this clinic.</p>'}
        </div>

        <div class="card">
          <div class="card-header"><h3>Map</h3>
            <div class="actions">${clinic.lat != null ? `<span class="muted small">${clinic.lat.toFixed(5)}, ${clinic.lng.toFixed(5)}</span>` : ''}</div></div>
          ${clinic.lat != null || clinic.locations.some(l => l.lat != null)
            ? `<div class="mini-map small" id="mini-map"></div><div class="help mt">Solid pin = main location (drag to correct). Dashed pins = secondary locations.</div>`
            : `<p class="muted">Not on the map yet. <button class="btn btn-sm" id="btn-locate">Set location</button></p>`}
        </div>
      </div>
    </div>`;

  // Wire actions
  const editClinic = () => openClinicForm({ clinic, onSaved: reload });
  container.querySelector('#btn-edit').onclick = editClinic;
  container.querySelector('#btn-edit-notes').onclick = editClinic;
  container.querySelector('#btn-edit-deal').onclick = editClinic;
  const locate = container.querySelector('#btn-locate');
  if (locate) locate.onclick = editClinic;
  const archiveBtn = container.querySelector('#btn-archive');
  if (archiveBtn) archiveBtn.onclick = async () => { await clinics.archive(clinic.id, !clinic.archived); toast(clinic.archived ? 'Back on the pipeline board' : 'Dismissed from the pipeline board', 'success'); reload(); };
  container.querySelector('#stage-move').onchange = (e) => changeStage(clinic, e.target.value, reload);
  const promoteBtn = container.querySelector('#btn-promote');
  if (promoteBtn) promoteBtn.onclick = () => changeStage(clinic, 'prospect', reload);
  container.querySelector('#btn-delete').onclick = async () => { if (await deleteClinic(clinic)) navigate('#/clinics'); };
  const newAppt = () => openAppointmentForm({ clinicId: clinic.id, lockClinic: true, onSaved: reload });
  container.querySelector('#btn-appt').onclick = newAppt;
  container.querySelector('#btn-appt-2').onclick = newAppt;
  const newContact = () => openContactForm({ clinicId: clinic.id, onSaved: reload });
  container.querySelector('#btn-contact').onclick = newContact;
  container.querySelector('#btn-contact-2').onclick = newContact;
  container.querySelector('#btn-scan-card').onclick = () => openCardScanner({ clinicId: clinic.id, onSaved: reload });
  const newTask = () => openTaskForm({ clinicId: clinic.id, onSaved: reload });
  container.querySelector('#btn-task').onclick = newTask;
  container.querySelector('#btn-task-2').onclick = newTask;
  const visitBtn = container.querySelector('#btn-visit');
  if (visitBtn) visitBtn.onclick = () => openLogVisit({ clinic, onSaved: reload });
  container.querySelector('#btn-location').onclick = () => openLocationForm({ clinic, onSaved: reload });
  container.querySelector('#btn-device').onclick = () => openDeviceForm({ clinic, onSaved: reload });
  container.querySelector('#btn-invoice').onclick = () => openInvoiceForm({ clinicId: clinic.id, onSaved: (iv) => iv && navigate(`#/invoices/${iv.id}`) });
  container.querySelector('#btn-link').onclick = () => openLinkForm({ clinic, onSaved: reload });
  wireTaskRows(container.querySelector('#task-list'), clinic.tasks, reload);
  container.querySelectorAll('[data-quick]').forEach(b => { b.onclick = () => quickLog(clinic, b.dataset.quick, reload); });

  container.querySelectorAll('[data-act=edit-loc]').forEach(b => {
    b.onclick = () => openLocationForm({ clinic, location: clinic.locations.find(l => l.id === Number(b.dataset.id)), onSaved: reload });
  });
  container.querySelectorAll('[data-act=del-link]').forEach(b => {
    b.onclick = async () => { if (!(await confirmDialog('Remove this connection?'))) return; await clinics.removeLink(clinic.id, Number(b.dataset.id)); reload(); };
  });
  container.querySelectorAll('[data-act=edit-contact]').forEach(b => {
    b.onclick = () => openContactForm({ contact: clinic.contacts.find(c => c.id === Number(b.dataset.id)), onSaved: reload });
  });
  container.querySelectorAll('[data-act=email]').forEach(b => {
    b.onclick = () => openEmailPicker({ contact: clinic.contacts.find(c => c.id === Number(b.dataset.id)), clinic, anchor: b, onSent: reload });
  });
  container.querySelectorAll('[data-act=edit-appt]').forEach(b => {
    b.onclick = () => openAppointmentForm({ appointment: clinic.appointments.find(a => a.id === Number(b.dataset.id)), lockClinic: true, onSaved: reload });
  });
  container.querySelectorAll('[data-act=complete]').forEach(b => {
    b.onclick = async () => { await appointments.patch(Number(b.dataset.id), { status: 'completed' }); toast('Marked completed', 'success'); reload(); };
  });
  container.querySelectorAll('[data-act=del-att]').forEach(b => {
    b.onclick = async (e) => { e.preventDefault(); if (!(await confirmDialog('Delete this file?'))) return; await attachments.remove(Number(b.dataset.id)); reload(); };
  });
  const uploadFiles = async (files, kind) => {
    for (const f of files) {
      try { await attachments.upload(clinic.id, f, null, kind); }
      catch (e) { toast(`${f.name}: ${e.message}`, 'error', 5000); }
    }
    toast(`${files.length} file${files.length === 1 ? '' : 's'} uploaded`, 'success');
    reload();
  };
  container.querySelector('#doc-file').onchange = (e) => { if (e.target.files.length) uploadFiles([...e.target.files], null); };
  container.querySelector('#photo-file').onchange = (e) => { if (e.target.files.length) uploadFiles([...e.target.files], 'photo'); };
  container.querySelector('#photo-capture').onchange = (e) => { if (e.target.files.length) uploadFiles([...e.target.files], 'photo'); };
  const noteForm = container.querySelector('#note-form');
  noteForm.onsubmit = async (e) => {
    e.preventDefault();
    const body = noteForm.elements.body.value.trim();
    if (!body) return;
    await clinics.addNote(clinic.id, body, 'note', getRepName() || null);
    toast('Note added', 'success');
    reload();
  };

  // Timeline
  const renderTimeline = () => {
    const items = clinic.timeline.filter(t => {
      if (tlFilter === 'all') return true;
      if (tlFilter === 'change') return !['note', 'appointment', 'task'].includes(t.type);
      return t.type === tlFilter;
    });
    const ul = container.querySelector('#timeline');
    ul.innerHTML = items.length ? items.map(timelineItem).join('') : '<li class="muted">Nothing here yet.</li>';
    ul.querySelectorAll('[data-act=del-note]').forEach(b => {
      b.onclick = async () => { if (!(await confirmDialog('Delete this note?'))) return; await clinics.removeNote(clinic.id, Number(b.dataset.id)); reload(); };
    });
    ul.querySelectorAll('[data-act=open-appt]').forEach(b => {
      b.onclick = () => openAppointmentForm({ appointment: clinic.appointments.find(a => a.id === Number(b.dataset.id)), lockClinic: true, onSaved: reload });
    });
    ul.querySelectorAll('[data-act=open-task]').forEach(b => {
      b.onclick = () => openTaskForm({ task: clinic.tasks.find(t => t.id === Number(b.dataset.id)), onSaved: reload });
    });
  };
  container.querySelectorAll('#tl-filters button').forEach(b => {
    b.onclick = () => { tlFilter = b.dataset.filter; container.querySelectorAll('#tl-filters button').forEach(x => x.classList.toggle('active', x === b)); renderTimeline(); };
  });
  renderTimeline();

  // Mini map with main + secondary locations
  const mapEl = container.querySelector('#mini-map');
  if (mapEl) {
    if (miniMap) { miniMap.remove(); miniMap = null; }
    miniMap = L.map(mapEl, { scrollWheelZoom: false });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }).addTo(miniMap);
    const pts = [];
    if (clinic.lat != null) {
      const m = L.marker([clinic.lat, clinic.lng], { draggable: true, icon: pinIcon(clinic.color) }).addTo(miniMap).bindTooltip('Main location');
      m.on('dragend', async () => { const p = m.getLatLng(); await clinics.setLocation(clinic.id, p.lat, p.lng); toast('Location updated', 'success'); });
      pts.push([clinic.lat, clinic.lng]);
    }
    clinic.locations.filter(l => l.lat != null).forEach(l => {
      L.marker([l.lat, l.lng], { icon: secondaryPinIcon(clinic.color) }).addTo(miniMap).bindTooltip(`${l.name} (secondary)`);
      pts.push([l.lat, l.lng]);
    });
    if (pts.length === 1) miniMap.setView(pts[0], 15); else miniMap.fitBounds(L.latLngBounds(pts).pad(0.3));
    const thisMap = miniMap;
    setTimeout(() => { if (miniMap === thisMap) thisMap.invalidateSize(); }, 50);
  }
}

export function destroy() {
  if (miniMap) { miniMap.remove(); miniMap = null; }
}

function fmtSize(b) { return b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : b > 1024 ? `${Math.round(b / 1024)} KB` : `${b} B`; }

const TL_ICONS = { note: '📝', appointment: '📍', task: '☑', stage_change: '➜', relationship_change: '◆', created: '＋', location: '🏥', link: '🔗', attachment: '📎' };

function timelineItem(t) {
  let actions = '';
  if (t.type === 'note') actions = `<button class="btn btn-link btn-sm" data-act="del-note" data-id="${t.id}">Delete</button>`;
  if (t.type === 'appointment') actions = `<button class="btn btn-link btn-sm" data-act="open-appt" data-id="${t.id}">Open</button>`;
  if (t.type === 'task') actions = `<button class="btn btn-link btn-sm" data-act="open-task" data-id="${t.id}">Open</button>`;
  const extra = t.type === 'appointment' ? `<span class="badge badge-${esc(t.status)}">${esc(t.status)}</span>` : (t.kind === 'quick' ? '<span class="badge">quick</span>' : t.kind === 'email' ? '<span class="badge badge-blue">email</span>' : '');
  const iconCls = t.type === 'note' && t.kind === 'quick' ? 'note' : t.type;
  return `
    <li class="tl-item ${t.future ? 'future' : ''}">
      <div class="tl-icon tl-icon-${esc(iconCls)}">${TL_ICONS[t.type] || '•'}</div>
      <div class="tl-body">
        <div class="tl-title">${esc(t.title)} ${extra}<span class="tl-time">${esc(fmtDateTime(t.at))}${t.future ? ' · upcoming' : ''}</span><span class="tl-actions">${actions}</span></div>
        ${t.body ? `<div class="tl-text">${esc(t.body)}</div>` : ''}
      </div>
    </li>`;
}

function apptRow(a, meta) {
  const overdue = a.status === 'scheduled' && isPast(a.start_time);
  return `
    <div class="appt-row">
      <div class="when">${esc(fmtDateTime(a.start_time))}<div>${esc(relativeDays(a.start_time))}</div></div>
      <div class="body">
        <div class="title">${esc(a.title)} <span class="badge">${esc(meta.appointment_types[a.appt_type] || a.appt_type)}</span> <span class="badge badge-${esc(a.status)}">${esc(meta.appointment_statuses[a.status] || a.status)}</span>${a.reminder_minutes ? ` <span class="badge" title="Reminder">🔔 ${a.reminder_minutes} min</span>` : ''}</div>
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
