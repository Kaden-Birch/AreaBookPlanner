// Calendar page: month grid + agenda, appointments linked to clinics.
import { appointments, getMeta } from '../api.js';
import { esc, attr, dot, fmtTime, fmtDateTime, toLocalInput, toDateInput, setTitle, isPast } from '../ui.js';
import { openAppointmentForm } from '../forms.js';

let state = { year: null, month: null, view: 'month' };

export async function render(container) {
  setTitle('Calendar');
  const today = new Date();
  if (state.year === null) { state.year = today.getFullYear(); state.month = today.getMonth(); }

  container.innerHTML = `
    <div class="page-header">
      <h1>Calendar</h1>
      <div class="actions">
        <a class="btn" href="/api/export/appointments.ics" download title="Import into Outlook / Google Calendar">Export .ics</a>
        <button class="btn btn-primary" id="new-appt">+ New appointment</button>
      </div>
    </div>
    <div class="calendar-layout">
      <div>
        <div class="cal-toolbar">
          <button class="btn" id="prev">‹</button>
          <button class="btn" id="today">Today</button>
          <button class="btn" id="next">›</button>
          <h2 id="month-title"></h2>
          <div class="flex" style="margin-left:auto">
            <button class="btn ${state.view === 'month' ? 'active' : ''}" data-view="month">Month</button>
            <button class="btn ${state.view === 'agenda' ? 'active' : ''}" data-view="agenda">Agenda</button>
          </div>
        </div>
        <div id="cal-body"></div>
      </div>
      <div class="card">
        <div class="card-header"><h3>Upcoming</h3></div>
        <ul class="list" id="upcoming"></ul>
      </div>
    </div>`;

  container.querySelector('#new-appt').onclick = () => openAppointmentForm({ onSaved: load });
  container.querySelector('#prev').onclick = () => { shift(-1); load(); };
  container.querySelector('#next').onclick = () => { shift(1); load(); };
  container.querySelector('#today').onclick = () => { state.year = today.getFullYear(); state.month = today.getMonth(); load(); };
  container.querySelectorAll('[data-view]').forEach(b => {
    b.onclick = () => { state.view = b.dataset.view; container.querySelectorAll('[data-view]').forEach(x => x.classList.toggle('active', x === b)); load(); };
  });
  await load();
}

function shift(n) {
  const d = new Date(state.year, state.month + n, 1);
  state.year = d.getFullYear(); state.month = d.getMonth();
}

async function load() {
  const meta = await getMeta();
  const first = new Date(state.year, state.month, 1);
  document.getElementById('month-title').textContent = first.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });

  // Grid spans from the Sunday before the 1st to the Saturday after month end.
  const gridStart = new Date(first); gridStart.setDate(1 - first.getDay());
  const monthEnd = new Date(state.year, state.month + 1, 0);
  const gridEnd = new Date(monthEnd); gridEnd.setDate(monthEnd.getDate() + (6 - monthEnd.getDay()) + 1);

  const [list, upcoming] = await Promise.all([
    appointments.list({ start: toLocalInput(gridStart), end: toLocalInput(gridEnd) }),
    appointments.list({ upcoming: true, limit: 12 }),
  ]);

  const byDay = {};
  for (const a of list) { (byDay[a.start_time.slice(0, 10)] ||= []).push(a); }

  const body = document.getElementById('cal-body');
  if (state.view === 'month') renderMonth(body, gridStart, gridEnd, byDay, meta);
  else renderAgenda(body, list, meta);

  const up = document.getElementById('upcoming');
  up.innerHTML = upcoming.length ? upcoming.map(a => `
    <li data-id="${a.id}" style="cursor:pointer">
      <span class="when">${esc(fmtDateTime(a.start_time))}</span>
      <div class="body"><div class="title">${esc(a.title)}</div><div class="muted small">${dot(a.clinic_color)}<a href="#/clinics/${a.clinic_id}">${esc(a.clinic_name)}</a> · ${esc(a.type_label)}</div></div>
    </li>`).join('') : '<li class="muted">No upcoming appointments.</li>';
  up.querySelectorAll('li[data-id]').forEach(li => {
    li.onclick = (e) => { if (e.target.tagName === 'A') return; openAppointmentForm({ appointment: upcoming.find(a => a.id === Number(li.dataset.id)), onSaved: load }); };
  });
}

function renderMonth(body, gridStart, gridEnd, byDay, meta) {
  const todayKey = toDateInput(new Date());
  let html = '<div class="cal-grid">' + ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map(d => `<div class="cal-dow">${d}</div>`).join('');
  for (let d = new Date(gridStart); d < gridEnd; d.setDate(d.getDate() + 1)) {
    const key = toDateInput(d);
    const items = byDay[key] || [];
    const cls = ['cal-day'];
    if (d.getMonth() !== state.month) cls.push('other-month');
    if (key === todayKey) cls.push('today');
    if (d.getDay() === 0 || d.getDay() === 6) cls.push('weekend');
    html += `<div class="${cls.join(' ')}" data-date="${key}">
      <span class="day-num">${d.getDate()}</span>
      ${items.map(a => `<span class="chip chip-${esc(a.clinic_color)} status-${esc(a.status)}" data-id="${a.id}" title="${attr(a.title)} · ${attr(a.clinic_name)}"><span class="time">${esc(fmtTime(a.start_time))}</span>${esc(a.clinic_name)}: ${esc(a.title)}</span>`).join('')}
    </div>`;
  }
  html += '</div><p class="muted small mt">Click a day to schedule an appointment. Click an appointment to edit it. Chip colour matches the clinic\'s map colour.</p>';
  body.innerHTML = html;

  const all = Object.values(byDay).flat();
  body.querySelectorAll('.cal-day').forEach(cell => {
    cell.onclick = (e) => {
      if (e.target.closest('.chip')) return;
      openAppointmentForm({ start: `${cell.dataset.date}T09:00`, onSaved: load });
    };
  });
  body.querySelectorAll('.chip').forEach(chip => {
    chip.onclick = () => openAppointmentForm({ appointment: all.find(a => a.id === Number(chip.dataset.id)), onSaved: load });
  });
}

function renderAgenda(body, list, meta) {
  if (!list.length) { body.innerHTML = '<div class="card empty">No appointments this month.</div>'; return; }
  const groups = {};
  for (const a of list) (groups[a.start_time.slice(0, 10)] ||= []).push(a);
  body.innerHTML = `<div class="card">${Object.entries(groups).map(([day, items]) => `
    <div class="agenda-day">
      <h3>${esc(new Date(day + 'T00:00').toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' }))}</h3>
      ${items.map(a => `
        <div class="appt-row" data-id="${a.id}" style="cursor:pointer">
          <div class="when">${esc(fmtTime(a.start_time))}${a.end_time ? ` – ${esc(fmtTime(a.end_time))}` : ''}</div>
          <div class="body">
            <div class="title">${esc(a.title)} <span class="badge badge-${esc(a.status)}">${esc(a.status_label)}</span></div>
            <div class="muted small">${dot(a.clinic_color)}<a href="#/clinics/${a.clinic_id}">${esc(a.clinic_name)}</a> · ${esc(a.type_label)}${a.contact_name ? ` · with ${esc(a.contact_name)}` : ''}</div>
            ${a.notes ? `<div class="small">${esc(a.notes)}</div>` : ''}
          </div>
        </div>`).join('')}
    </div>`).join('')}</div>`;
  body.querySelectorAll('.appt-row').forEach(row => {
    row.onclick = (e) => { if (e.target.tagName === 'A') return; openAppointmentForm({ appointment: list.find(a => a.id === Number(row.dataset.id)), onSaved: load }); };
  });
}
