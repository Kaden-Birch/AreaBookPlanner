// Tasks page: every reminder across clinics, grouped by urgency.
import { tasks } from '../api.js';
import { esc, attr, badge, fmtDateOnly, toDateInput, toast, debounce, setTitle } from '../ui.js';
import { openTaskForm } from '../forms.js';

let state = { q: '', filter: 'open' };

export async function render(container) {
  setTitle('Tasks');
  container.innerHTML = `
    <div class="page-header">
      <h1>Tasks</h1>
      <span class="muted" id="task-count"></span>
      <div class="actions"><button class="btn btn-primary" id="add-task">+ New task</button></div>
    </div>
    <div class="toolbar">
      <input type="search" class="search" id="q" placeholder="Search tasks…" value="${attr(state.q)}">
      <select id="filter">
        <option value="open" ${state.filter === 'open' ? 'selected' : ''}>Open</option>
        <option value="done" ${state.filter === 'done' ? 'selected' : ''}>Done</option>
        <option value="all" ${state.filter === 'all' ? 'selected' : ''}>All</option>
      </select>
    </div>
    <div class="card" id="task-list"></div>`;
  container.querySelector('#add-task').onclick = () => openTaskForm({ onSaved: load });
  const q = container.querySelector('#q');
  q.addEventListener('input', debounce(() => { state.q = q.value; load(); }, 200));
  container.querySelector('#filter').onchange = (e) => { state.filter = e.target.value; load(); };
  await load();
}

async function load() {
  const params = { q: state.q };
  if (state.filter !== 'all') params.done = state.filter === 'done';
  const list = await tasks.list(params);
  document.getElementById('task-count').textContent = `${list.length} task${list.length === 1 ? '' : 's'}`;
  const el = document.getElementById('task-list');
  if (!list.length) { el.innerHTML = '<div class="empty">No tasks here. Add reminders like “Call back Friday” from a clinic page or with “+ New task”.</div>'; return; }

  const today = toDateInput(new Date());
  const week = toDateInput(new Date(Date.now() + 7 * 86400000));
  const groups = [
    ['Overdue', t => !t.done && t.due_date && t.due_date < today],
    ['Today', t => !t.done && t.due_date === today],
    ['This week', t => !t.done && t.due_date && t.due_date > today && t.due_date <= week],
    ['Later', t => !t.done && t.due_date && t.due_date > week],
    ['No due date', t => !t.done && !t.due_date],
    ['Done', t => t.done],
  ];
  el.innerHTML = groups.map(([name, fn]) => {
    const items = list.filter(fn);
    if (!items.length) return '';
    return `<div class="task-group"><h3>${name} <span class="muted">(${items.length})</span></h3>${items.map(taskRow).join('')}</div>`;
  }).join('');
  wireTaskRows(el, list, load);
}

export function taskRow(t) {
  const dueCls = t.overdue ? 'overdue' : (t.due_today ? 'today' : '');
  return `
    <div class="task-row ${t.done ? 'done' : ''}" data-id="${t.id}">
      <input type="checkbox" ${t.done ? 'checked' : ''} title="Mark ${t.done ? 'not done' : 'done'}">
      <div class="body">
        <div class="title">${esc(t.title)} ${t.priority === 'high' ? badge('High', 'badge-high') : ''}</div>
        <div class="sub">
          ${t.clinic_id ? `<a href="#/clinics/${t.clinic_id}">${esc(t.clinic_name)}</a>` : ''}
          ${t.contact_name ? ` · ${esc(t.contact_name)}` : ''}
          ${t.notes ? ` · ${esc(t.notes)}` : ''}
        </div>
      </div>
      <span class="task-due ${dueCls}">${t.due_date ? (t.overdue ? 'Overdue · ' : '') + esc(fmtDateOnly(t.due_date)) : ''}</span>
      <div class="actions"><button class="btn btn-sm" data-act="edit">Edit</button></div>
    </div>`;
}

export function wireTaskRows(root, list, reload) {
  root.querySelectorAll('.task-row').forEach(row => {
    const t = list.find(x => x.id === Number(row.dataset.id));
    row.querySelector('input[type=checkbox]').onchange = async (e) => {
      try { await tasks.patch(t.id, { done: e.target.checked }); toast(e.target.checked ? 'Task done' : 'Task reopened', 'success'); reload(); }
      catch (err) { toast(err.message, 'error'); }
    };
    row.querySelector('[data-act=edit]').onclick = () => openTaskForm({ task: t, onSaved: reload });
  });
}
