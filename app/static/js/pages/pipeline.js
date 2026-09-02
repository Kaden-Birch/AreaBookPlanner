// Pipeline page: Kanban board of clinics by sales stage, with deal totals and won/lost reasons.
import { clinics, dashboard, getMeta } from '../api.js';
import { esc, attr, dot, fmtMoney, fmtDate, fmtDateOnly, relativeDays, options, debounce, setTitle, badge, toast, shorthandBadge } from '../ui.js';
import { changeStage, openClinicForm } from '../forms.js';

let state = { q: '', color: '', showClosed: true, showEarlierClosed: false, showArchived: false, sort: 'value' };
let allClinics = [];
let meta = null;

export async function render(container) {
  setTitle('Pipeline');
  container.classList.add('wide');
  meta = await getMeta();
  container.innerHTML = `
    <div class="page-header">
      <h1>Pipeline</h1>
      <span class="muted" id="pipe-summary"></span>
      <div class="actions">
        <button class="btn btn-primary" id="add-clinic">+ New interested clinic</button>
      </div>
    </div>
    <div id="leads-chip"></div>
    <div class="grid-4 mb" id="forecast"></div>
    <div class="toolbar">
      <input type="search" class="search" id="q" placeholder="Search clinics…" value="${attr(state.q)}">
      <select id="color">${options(meta.colors, state.color, { blank: 'All colours' })}</select>
      <select id="sort">
        <option value="value" ${state.sort === 'value' ? 'selected' : ''}>Sort: Value</option>
        <option value="close" ${state.sort === 'close' ? 'selected' : ''}>Sort: Expected close</option>
        <option value="name" ${state.sort === 'name' ? 'selected' : ''}>Sort: Name</option>
        <option value="activity" ${state.sort === 'activity' ? 'selected' : ''}>Sort: Recently updated</option>
      </select>
      <label class="checkbox"><input type="checkbox" id="show-closed" ${state.showClosed ? 'checked' : ''}> Show Won / Lost</label>
      <label class="checkbox"><input type="checkbox" id="show-earlier" ${state.showEarlierClosed ? 'checked' : ''}> Include earlier months <span class="muted" id="earlier-count"></span></label>
      <label class="checkbox"><input type="checkbox" id="show-archived" ${state.showArchived ? 'checked' : ''}> Show dismissed clients <span class="muted" id="archived-count"></span></label>
      <span class="muted small">Drag cards between columns to move them along the pipeline. Won / Lost clear at month-end.</span>
    </div>
    <div id="board"></div>
    <div class="grid-2 mt" id="reasons"></div>`;

  container.querySelector('#add-clinic').onclick = () => openClinicForm({ initial: { stage: 'prospect' }, onSaved: load });
  const q = container.querySelector('#q');
  q.addEventListener('input', debounce(() => { state.q = q.value; renderBoard(); }, 150));
  container.querySelector('#color').onchange = (e) => { state.color = e.target.value; renderBoard(); };
  container.querySelector('#sort').onchange = (e) => { state.sort = e.target.value; renderBoard(); };
  container.querySelector('#show-closed').onchange = (e) => { state.showClosed = e.target.checked; renderBoard(); };
  container.querySelector('#show-earlier').onchange = (e) => { state.showEarlierClosed = e.target.checked; renderBoard(); };
  container.querySelector('#show-archived').onchange = (e) => { state.showArchived = e.target.checked; renderBoard(); };
  await load();
}

export function destroy(container) { container.classList.remove('wide'); }

async function load() {
  const [list, d] = await Promise.all([clinics.list(), dashboard()]);
  allClinics = list;
  renderForecast(d);
  renderLeads();
  renderBoard();
  renderReasons(d);
}

function renderLeads() {
  const el = document.getElementById('leads-chip');
  if (!el) return;
  const leads = allClinics.filter(c => c.stage === 'lead' && !c.archived && c.relationship !== 'do_not_contact');
  if (!leads.length) { el.innerHTML = ''; return; }
  el.innerHTML = `<div class="lead-banner">
    <span><strong>${leads.length}</strong> lead${leads.length === 1 ? '' : 's'} waiting to be contacted — not on the board yet.</span>
    <a class="btn btn-sm" href="#/clinics?stage=lead">Review leads →</a>
  </div>`;
}

function renderForecast(d) {
  const f = d.forecast;
  document.getElementById('forecast').innerHTML = `
    <div class="card stat"><div class="value">${f.open_deals}</div><div class="label">Open deals</div></div>
    <div class="card stat"><div class="value money">${fmtMoney(f.open_value) || '$0'}</div><div class="label">Open pipeline value</div><div class="sub">Sum of estimated annual value</div></div>
    <div class="card stat"><div class="value money">${fmtMoney(f.weighted_value) || '$0'}</div><div class="label">Weighted forecast</div><div class="sub">Value × win probability</div></div>
    <div class="card stat"><div class="value money">${fmtMoney(f.won_value_this_year) || '$0'}</div><div class="label">Won this year</div></div>`;
  const onBoard = allClinics.filter(c => c.stage !== 'lead').length;
  document.getElementById('pipe-summary').textContent = `${onBoard} in pipeline`;
}

function isClosed(c) { return c.stage === 'won' || c.stage === 'lost'; }

function visible(c) {
  if (c.stage === 'lead') return false; // leads are pre-pipeline, never on the board
  if (isClosed(c)) {
    if (!state.showClosed) return false;
    // Won / Lost only linger for the calendar month they closed in.
    if (!c.closed_recent && !state.showEarlierClosed) return false;
  }
  if (c.archived && !state.showArchived) return false;
  if (state.color && c.color !== state.color) return false;
  if (state.q) {
    const q = state.q.toLowerCase();
    if (![c.name, c.address, c.tags, c.clinic_type].some(v => v && String(v).toLowerCase().includes(q))) return false;
  }
  return true;
}

function sorter(a, b) {
  switch (state.sort) {
    case 'close': return (a.expected_close || '9999').localeCompare(b.expected_close || '9999');
    case 'name': return a.name.localeCompare(b.name);
    case 'activity': return (b.updated_at || '').localeCompare(a.updated_at || '');
    default: return (b.deal_value || 0) - (a.deal_value || 0) || a.name.localeCompare(b.name);
  }
}

function renderBoard() {
  const archivedN = allClinics.filter(c => c.archived).length;
  document.getElementById('archived-count').textContent = archivedN ? `(${archivedN})` : '';
  const earlierN = allClinics.filter(c => isClosed(c) && !c.closed_recent && !c.archived).length;
  document.getElementById('earlier-count').textContent = earlierN ? `(${earlierN})` : '';
  const pipeline = meta.pipeline_stages || Object.keys(meta.stages).filter(s => s !== 'lead');
  const stages = pipeline.filter(s => state.showClosed || !['won', 'lost'].includes(s));
  const board = document.getElementById('board');
  const today = new Date().toISOString().slice(0, 10);
  board.innerHTML = `<div class="kanban" style="grid-template-columns: repeat(${stages.length}, minmax(200px, 1fr))">${stages.map(stage => {
    const cards = allClinics.filter(c => c.stage === stage && visible(c)).sort(sorter);
    const value = cards.reduce((s, c) => s + (c.deal_value || 0), 0);
    const weighted = cards.reduce((s, c) => s + (c.weighted_value || 0), 0);
    const isOpen = meta.open_stages.includes(stage);
    return `
      <div class="kanban-col" data-stage="${stage}">
        <div class="kanban-col-header stage-${stage}">
          <div class="name">${esc(meta.stages[stage])}<span class="count">${cards.length}</span></div>
          <div class="totals">${value ? `${fmtMoney(value)}${isOpen ? ` · weighted ${fmtMoney(weighted)}` : ''}` : '&nbsp;'}</div>
        </div>
        <div class="kanban-cards">
          ${cards.length ? cards.map(c => card(c, today)).join('') : '<div class="kanban-empty">Drop a clinic here</div>'}
        </div>
      </div>`;
  }).join('')}</div>`;

  // Drag & drop
  board.querySelectorAll('.kanban-card').forEach(el => {
    el.addEventListener('dragstart', (e) => { e.dataTransfer.setData('text/plain', el.dataset.id); e.dataTransfer.effectAllowed = 'move'; el.classList.add('dragging'); });
    el.addEventListener('dragend', () => el.classList.remove('dragging'));
    el.querySelector('select.stage-select').onchange = (e) => {
      const c = allClinics.find(x => x.id === Number(el.dataset.id));
      changeStage(c, e.target.value, load);
    };
    const dismiss = el.querySelector('[data-act=dismiss]');
    if (dismiss) dismiss.onclick = async () => {
      const c = allClinics.find(x => x.id === Number(el.dataset.id));
      await clinics.archive(c.id, !c.archived);
      toast(c.archived ? `${c.name} restored to the board` : `${c.name} dismissed from the board`, 'success');
      load();
    };
  });
  board.querySelectorAll('.kanban-col').forEach(col => {
    col.addEventListener('dragover', (e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; col.classList.add('drag-over'); });
    col.addEventListener('dragleave', (e) => { if (!col.contains(e.relatedTarget)) col.classList.remove('drag-over'); });
    col.addEventListener('drop', (e) => {
      e.preventDefault();
      col.classList.remove('drag-over');
      const id = Number(e.dataTransfer.getData('text/plain'));
      const c = allClinics.find(x => x.id === id);
      if (c) changeStage(c, col.dataset.stage, load);
    });
  });
}

function card(c, today) {
  const closeOverdue = c.expected_close && c.expected_close < today && meta.open_stages.includes(c.stage);
  const closed = c.stage === 'won' || c.stage === 'lost';
  const reasonLabel = closed && c.outcome_reason ? (c.stage === 'won' ? meta.won_reasons : meta.lost_reasons)[c.outcome_reason] || c.outcome_reason : null;
  return `
    <div class="kanban-card" draggable="true" data-id="${c.id}">
      <div class="name">${dot(c.color, c.color_label)}<a href="#/clinics/${c.id}">${esc(c.name)}</a>${c.shorthand ? ` ${shorthandBadge(c)}` : ''}${c.archived ? ' ' + badge('Dismissed', 'badge-grey') : ''}</div>
      <div class="row">
        ${c.deal_value ? `<span class="value money">${fmtMoney(c.deal_value)}</span>` : '<span>No value set</span>'}
        ${!closed ? `<span>· ${c.effective_probability}%</span>` : ''}
        ${c.priority === 'high' ? badge('High', 'badge-high') : ''}
      </div>
      ${c.expected_close && !closed ? `<div class="row">Close ${esc(fmtDateOnly(c.expected_close))} ${closeOverdue ? badge('Slipped', 'badge-red') : ''}</div>` : ''}
      ${closed && c.outcome_date ? `<div class="row">${c.stage === 'won' ? 'Won' : 'Lost'} ${esc(fmtDateOnly(c.outcome_date))}${reasonLabel ? ` · ${esc(reasonLabel)}` : ''}</div>` : ''}
      <div class="row">${c.next_appointment ? `Next: ${esc(fmtDate(c.next_appointment.start_time))}` : (c.last_visit ? `Last visit ${esc(relativeDays(c.last_visit))}` : 'Never visited')}</div>
      <div class="foot">
        ${c.clinic_type ? `<span class="badge">${esc(c.clinic_type)}</span>` : ''}
        ${c.stage === 'won' ? `<button class="btn btn-sm btn-link" data-act="dismiss" title="${c.archived ? 'Show on the board again' : 'Hide from the board (stays a client)'}">${c.archived ? 'Restore' : 'Dismiss'}</button>` : ''}
        <select class="stage-select" title="Move to stage">${options(meta.stages, c.stage)}</select>
      </div>
    </div>`;
}

function renderReasons(d) {
  const el = document.getElementById('reasons');
  const block = (title, map, cls) => {
    const entries = Object.entries(map).sort((a, b) => b[1] - a[1]);
    const max = Math.max(1, ...entries.map(e => e[1]));
    return `<div class="card"><div class="card-header"><h3>${title}</h3></div>
      ${entries.length ? `<div class="reasons">${entries.map(([k, v]) => `<div>${esc(k)}<div class="bar ${cls}" style="width:${(v / max) * 100}%"></div></div><div class="right"><strong>${v}</strong></div>`).join('')}</div>` : '<p class="muted">No closed deals with a reason recorded yet.</p>'}
    </div>`;
  };
  el.innerHTML = block('Why we win', d.outcome_reasons.won, '') + block('Why we lose', d.outcome_reasons.lost, '');
  el.querySelectorAll('.card:last-child .bar').forEach(b => { b.style.background = 'var(--c-red)'; });
}
