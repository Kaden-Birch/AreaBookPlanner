// Call sheet: a print-friendly list of a day's stops with addresses, contacts and notes.
import { api } from '../api.js';
import { esc, attr, dot, fmtDateOnly, fmtDateTime, fmtTime, fmtDate, relativeDays, fullAddress, setTitle, getRepName, toDateInput } from '../ui.js';

export async function render(container, params) {
  setTitle('Call sheet');
  const ids = params.get('ids');
  const date = params.get('date');
  let data;
  try { data = await api.get('/api/call-sheet', { ids, date }); }
  catch (e) { container.innerHTML = `<div class="card empty">${esc(e.message)}</div>`; return; }
  const title = date ? `Call sheet · ${fmtDateOnly(date)}` : 'Call sheet';
  const rep = getRepName();
  container.innerHTML = `
    <div class="page-header no-print">
      <h1>${esc(title)}</h1>
      <span class="muted">${data.items.length} stop${data.items.length === 1 ? '' : 's'}</span>
      <div class="actions">
        ${date ? `<input type="date" id="sheet-date" value="${attr(date)}" style="width:auto">` : ''}
        <button class="btn btn-primary" id="print-btn">🖨 Print / Save as PDF</button>
        <a class="btn" href="#/map${ids ? `?route=${ids}` : ''}">Map</a>
      </div>
    </div>
    <div class="sheet">
      <div class="sheet-head">
        <div><h1>${esc(title)}</h1><div class="muted small">${data.items.length} stop${data.items.length === 1 ? '' : 's'}${rep ? ` · ${esc(rep)}` : ''}</div></div>
        <div class="meta">Area Book Planner<br>Printed ${esc(fmtDateTime(new Date().toISOString()))}</div>
      </div>
      ${data.items.length ? data.items.map((it, i) => item(it, i)).join('') : `<p class="muted">${date ? 'No scheduled appointments on this day.' : 'No clinics selected.'}</p>`}
      <p class="muted small mt">${esc(data.items.map(it => it.clinic.name).join(' → '))}</p>
    </div>`;
  container.querySelector('#print-btn').onclick = () => window.print();
  const d = container.querySelector('#sheet-date');
  if (d) d.onchange = () => { window.location.hash = `#/call-sheet?date=${d.value}`; };
}

function item(it, i) {
  const c = it.clinic;
  const contacts = it.contacts || [];
  return `
    <div class="sheet-item">
      <div><span class="num">${i + 1}</span></div>
      <div>
        <h2>${dot(c.color, c.color_label)}${c.shorthand ? `<span class="badge badge-shorthand">${esc(c.shorthand)}</span>` : ''}${esc(c.name)}
          <span class="badge">${esc(c.color_label)}</span>${!c.is_client ? `<span class="badge">${esc(c.stage_label)}</span>` : ''}${c.follow_up_overdue ? '<span class="badge badge-overdue">Follow-up overdue</span>' : ''}</h2>
        <div class="line">${esc(fullAddress(c)) || 'No address'}${c.phone ? ` · ☎ ${esc(c.phone)}` : ''}${c.clinic_type ? ` · ${esc(c.clinic_type)}` : ''}</div>
        ${it.locations && it.locations.length ? `<div class="line muted">Also: ${it.locations.map(l => `${esc(l.name)} (${esc(l.address || '')})`).join('; ')}</div>` : ''}
        ${it.appointments && it.appointments.length ? `<div class="line"><strong>${it.appointments.map(a => `${esc(fmtTime(a.start_time))} ${esc(a.title)}${a.contact_first_name ? ` with ${esc(a.contact_first_name)} ${esc(a.contact_last_name || '')}` : ''}${a.notes ? ` — ${esc(a.notes)}` : ''}`).join(' · ')}</strong></div>` : ''}
        <div class="sheet-cols">
          <div>
            <div class="label">Contacts</div>
            ${contacts.length ? `<ul>${contacts.slice(0, 5).map(ct => `<li>${ct.is_primary ? '★ ' : ''}<strong>${esc(ct.first_name)} ${esc(ct.last_name || '')}</strong>${ct.title ? ` — ${esc(ct.title)}` : ''}${ct.phone_display ? ` · ${esc(ct.phone_display)}` : ''}${ct.mobile ? ` · m ${esc(ct.mobile)}` : ''}${ct.email ? ` · ${esc(ct.email)}` : ''}</li>`).join('')}</ul>` : '<div class="line muted">No contacts on file</div>'}
            ${it.open_tasks && it.open_tasks.length ? `<div class="label">To do</div><ul>${it.open_tasks.map(t => `<li><span class="sheet-checkbox"></span>${esc(t.title)}${t.due_date ? ` <span class="muted">(${esc(fmtDateOnly(t.due_date))})</span>` : ''}</li>`).join('')}</ul>` : ''}
          </div>
          <div>
            <div class="label">Background</div>
            <div class="line">${it.last_appointment ? `Last: ${esc(fmtDate(it.last_appointment.start_time))} (${esc(relativeDays(it.last_appointment.start_time))}) — ${esc(it.last_appointment.title)}${it.last_appointment.outcome ? `: ${esc(it.last_appointment.outcome)}` : ''}` : 'Never visited'}</div>
            ${c.it_provider ? `<div class="line">IT: ${esc(c.it_provider)}${c.emr_system ? ` · EMR: ${esc(c.emr_system)}` : ''}</div>` : (c.emr_system ? `<div class="line">EMR: ${esc(c.emr_system)}</div>` : '')}
            ${c.notes ? `<div class="line">${esc(c.notes.length > 240 ? c.notes.slice(0, 240) + '…' : c.notes)}</div>` : ''}
            ${it.recent_notes && it.recent_notes.length ? `<ul>${it.recent_notes.map(n => `<li><span class="muted">${esc(fmtDate(n.created_at))}:</span> ${esc(n.body.length > 140 ? n.body.slice(0, 140) + '…' : n.body)}</li>`).join('')}</ul>` : ''}
          </div>
        </div>
        <div class="label print-only">Notes from this visit</div>
        <div class="scribble print-only"></div><div class="scribble print-only"></div><div class="scribble print-only"></div>
      </div>
    </div>`;
}
