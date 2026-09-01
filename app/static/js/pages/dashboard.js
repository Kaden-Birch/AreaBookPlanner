// Dashboard: numbers, pipeline, this week's plan, what needs attention, data tools.
import { dashboard, getMeta, api, tasks } from '../api.js';
import { esc, dot, badge, fmtDate, fmtDateTime, fmtDateOnly, fmtMoney, relativeDays, COLOR_ORDER, COLOR_HEX, toast, confirmDialog, setTitle, navigate } from '../ui.js';
import { openClinicForm, openAppointmentForm, openTaskForm } from '../forms.js';

export async function render(container) {
  setTitle('Dashboard');
  const [d, meta] = await Promise.all([dashboard(), getMeta()]);
  const total = d.totals.clinics || 1;
  const f = d.forecast;

  container.innerHTML = `
    <div class="page-header">
      <h1>Dashboard</h1>
      <div class="actions">
        <button class="btn btn-primary" id="add-clinic">+ Clinic</button>
        <button class="btn" id="add-appt">+ Appointment</button>
        <button class="btn" id="add-task">+ Task</button>
      </div>
    </div>

    <div class="grid-4">
      <div class="card stat"><div class="value">${d.totals.clinics}</div><div class="label">Clinics</div><div class="sub">${d.totals.contacts} contacts</div></div>
      <div class="card stat"><div class="value">${d.totals.appointments_upcoming}</div><div class="label">Upcoming appointments</div><div class="sub">${d.totals.visits_this_month} visits this month</div></div>
      <div class="card stat"><div class="value money">${fmtMoney(f.weighted_value) || '$0'}</div><div class="label">Weighted forecast</div><div class="sub">${f.open_deals} open deals · ${fmtMoney(f.open_value) || '$0'} total</div></div>
      <div class="card stat"><div class="value money">${fmtMoney(f.won_value_this_year) || '$0'}</div><div class="label">Won this year</div><div class="sub">${d.totals.tasks_open} open tasks</div></div>
    </div>

    <div class="grid-2 mt">
      <div class="card">
        <div class="card-header"><h3>Pipeline</h3><div class="actions"><a class="btn btn-sm" href="#/pipeline">Open board</a></div></div>
        <div class="stage-bar">${Object.entries(meta.stages).map(([s, label]) => `
          <a href="#/pipeline"><span class="n">${d.pipeline[s].count}</span>${esc(label)}<span class="v">${d.pipeline[s].value ? fmtMoney(d.pipeline[s].value) : '&nbsp;'}</span></a>`).join('')}</div>
      </div>
      <div class="card">
        <div class="card-header"><h3>Clinics by status</h3><div class="actions"><a class="btn btn-sm" href="#/map">Open map</a></div></div>
        <div class="color-bar">${COLOR_ORDER.map(c => `<span style="width:${(d.by_color[c] / total) * 100}%;background:${COLOR_HEX[c]}" title="${esc(meta.colors[c])}: ${d.by_color[c]}"></span>`).join('')}</div>
        <div class="legend">${COLOR_ORDER.map(c => `<a class="legend-item" href="#/map?color=${c}">${dot(c)} ${esc(meta.colors[c])} <span class="count">${d.by_color[c]}</span></a>`).join('')}</div>
      </div>
    </div>

    <div class="grid-2 mt">
      <div>
        <div class="card">
          <div class="card-header"><h3>Tasks due</h3><span class="muted small">Overdue, today and next 7 days</span><div class="actions"><a class="btn btn-sm" href="#/tasks">All tasks</a></div></div>
          ${listOrEmpty(d.tasks_due, t => `
            <li><input type="checkbox" data-task="${t.id}" title="Mark done" style="margin-top:3px">
              <div class="body"><div class="title">${esc(t.title)} ${t.priority === 'high' ? badge('High', 'badge-high') : ''}</div>
              <div class="muted small">${t.clinic_id ? `<a href="#/clinics/${t.clinic_id}">${esc(t.clinic_name)}</a> · ` : ''}<span class="task-due ${t.overdue ? 'overdue' : (t.due_today ? 'today' : '')}">${t.due_date ? (t.overdue ? 'Overdue · ' : '') + esc(fmtDateOnly(t.due_date)) : 'No due date'}</span></div></div></li>`,
            'No tasks due. Add reminders from a clinic page or the Tasks page.')}
        </div>
        <div class="card">
          <div class="card-header"><h3>Next 7 days</h3><div class="actions"><a class="btn btn-sm" href="#/calendar">Calendar</a></div></div>
          ${listOrEmpty(d.upcoming, a => `
            <li><span class="when">${esc(fmtDateTime(a.start_time))}</span>
              <div class="body"><div class="title">${esc(a.title)}</div><div class="muted small"><a href="#/clinics/${a.clinic_id}">${esc(a.clinic_name)}</a> · ${esc(meta.appointment_types[a.appt_type] || a.appt_type)}</div></div></li>`,
            'Nothing scheduled this week. Open the calendar to plan visits.')}
        </div>
        <div class="card">
          <div class="card-header"><h3>Follow-ups due</h3><span class="muted small">Due within 7 days</span></div>
          ${listOrEmpty(d.follow_ups, f => `
            <li><span class="when">${esc(fmtDateOnly(f.next_follow_up))}</span>
              <div class="body"><div class="title">${dot(f.color)}<a href="#/clinics/${f.id}">${esc(f.name)}</a> ${f.overdue ? badge('Overdue', 'badge-red') : ''} ${f.priority === 'high' ? badge('High', 'badge-high') : ''}</div></div></li>`,
            'No follow-ups due. Set a “next follow-up” date on a clinic to see it here.')}
        </div>
      </div>
      <div>
        <div class="card">
          <div class="card-header"><h3>Closing soon</h3><span class="muted small">Open deals expected to close within 30 days</span></div>
          ${listOrEmpty(d.closing_soon, c => `
            <li><span class="when">${esc(fmtDateOnly(c.expected_close))}</span>
              <div class="body"><div class="title">${dot(c.color)}<a href="#/clinics/${c.id}">${esc(c.name)}</a> <span class="badge badge-stage-${esc(c.stage)}">${esc(c.stage_label)}</span></div>
              <div class="muted small money">${c.deal_value ? fmtMoney(c.deal_value) : 'No value set'}</div></div></li>`,
            'No deals closing in the next 30 days.')}
        </div>
        <div class="card">
          <div class="card-header"><h3>Needs an outcome</h3><span class="muted small">Past appointments still marked scheduled</span></div>
          ${listOrEmpty(d.needs_outcome, a => `
            <li><span class="when">${esc(fmtDate(a.start_time))}</span>
              <div class="body"><div class="title">${esc(a.title)}</div><div class="muted small"><a href="#/clinics/${a.clinic_id}">${esc(a.clinic_name)}</a></div></div>
              <div class="actions"><button class="btn btn-sm" data-complete="${a.id}">Mark done</button></div></li>`,
            'All caught up.')}
        </div>
        <div class="card">
          <div class="card-header"><h3>Due for a visit</h3><span class="muted small">Clients & prospects not seen in 3+ months</span></div>
          ${listOrEmpty(d.stale, s => `
            <li><span class="when">${s.last_visit ? esc(relativeDays(s.last_visit)) : 'never'}</span>
              <div class="body"><div class="title">${dot(s.color)}<a href="#/clinics/${s.id}">${esc(s.name)}</a></div></div></li>`,
            'Everyone has been visited recently.')}
        </div>
        ${d.unmapped.length ? `
        <div class="card">
          <div class="card-header"><h3>Not on the map</h3><span class="muted small">Clinics without a pin</span></div>
          <ul class="list">${d.unmapped.map(c => `<li><div class="body"><a href="#/clinics/${c.id}">${esc(c.name)}</a></div></li>`).join('')}</ul>
        </div>` : ''}
      </div>
    </div>

    <div class="card mt">
      <div class="card-header"><h3>Data</h3><span class="muted small">Everything is stored locally in a SQLite database</span></div>
      <div class="flex flex-wrap">
        <a class="btn" href="/api/export/backup.json" download>Download backup (JSON)</a>
        <a class="btn" href="/api/export/clinics.csv" download>Clinics CSV</a>
        <a class="btn" href="/api/export/contacts.csv" download>Contacts CSV</a>
        <a class="btn" href="/api/export/appointments.ics" download>Calendar .ics</a>
        <label class="btn" style="margin:0">Restore backup… <input type="file" id="restore-file" accept="application/json" class="hidden"></label>
      </div>
    </div>`;

  container.querySelector('#add-clinic').onclick = () => openClinicForm({ onSaved: c => navigate(`#/clinics/${c.id}`) });
  container.querySelector('#add-appt').onclick = () => openAppointmentForm({ onSaved: () => render(container) });
  container.querySelector('#add-task').onclick = () => openTaskForm({ onSaved: () => render(container) });
  container.querySelectorAll('[data-complete]').forEach(b => {
    b.onclick = async () => { await api.patch(`/api/appointments/${b.dataset.complete}`, { status: 'completed' }); toast('Marked completed', 'success'); render(container); };
  });
  container.querySelectorAll('[data-task]').forEach(cb => {
    cb.onchange = async () => { await tasks.patch(Number(cb.dataset.task), { done: true }); toast('Task done', 'success'); render(container); };
  });
  container.querySelector('#restore-file').onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    let data;
    try { data = JSON.parse(await file.text()); } catch { toast('Not a valid backup file', 'error'); return; }
    const replace = await confirmDialog(
      'Replace ALL current data with this backup? Choose "Replace" to wipe and restore, or Cancel to merge the backup into the existing data instead.',
      { title: 'Restore backup', okLabel: 'Replace everything' });
    try {
      const res = await api.post('/api/import/backup', data, { replace: replace ? 'true' : 'false' });
      toast(`Backup ${res.status}: ${res.counts.clinics} clinics, ${res.counts.contacts} contacts, ${res.counts.appointments} appointments`, 'success', 5000);
      render(container);
    } catch (err) { toast(err.message, 'error'); }
    e.target.value = '';
  };
}

function listOrEmpty(items, fn, emptyText) {
  if (!items.length) return `<p class="muted">${esc(emptyText)}</p>`;
  return `<ul class="list">${items.map(fn).join('')}</ul>`;
}
