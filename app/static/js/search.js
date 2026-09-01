// Global search palette (Ctrl/⌘+K) across clinics, contacts, notes, tasks and locations.
import { api } from './api.js';
import { esc, dot, fmtDate, navigate, debounce } from './ui.js';

let overlay = null;
let items = [];
let active = 0;

export function initSearch() {
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); open(); }
    if (e.key === '/' && !overlay && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) { e.preventDefault(); open(); }
  });
  const btn = document.getElementById('global-search');
  if (btn) btn.onclick = open;
}

export function open() {
  if (overlay) return;
  overlay = document.createElement('div');
  overlay.className = 'palette-backdrop';
  overlay.innerHTML = `
    <div class="palette" role="dialog" aria-label="Search">
      <input type="search" id="palette-input" placeholder="Search clinics, shorthand, contacts, notes, tasks…" autocomplete="off">
      <div class="palette-results" id="palette-results"><div class="palette-hint">Type to search · ↑↓ to move · Enter to open · Esc to close</div></div>
    </div>`;
  document.body.appendChild(overlay);
  const input = overlay.querySelector('#palette-input');
  overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) close(); });
  input.addEventListener('input', debounce(() => run(input.value), 150));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { close(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); move(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
    else if (e.key === 'Enter') { e.preventDefault(); pick(active); }
  });
  setTimeout(() => input.focus(), 20);
}

function close() { if (overlay) { overlay.remove(); overlay = null; items = []; active = 0; } }

async function run(q) {
  const box = overlay && overlay.querySelector('#palette-results');
  if (!box) return;
  if (q.trim().length < 2) { box.innerHTML = '<div class="palette-hint">Type at least 2 characters.</div>'; items = []; return; }
  let r;
  try { r = await api.get('/api/search', { q }); } catch (e) { box.innerHTML = `<div class="palette-hint">${esc(e.message)}</div>`; return; }
  items = [];
  const groups = [];
  const add = (title, list, fn) => { if (!list.length) return; groups.push({ title, start: items.length, n: list.length }); list.forEach(x => items.push(fn(x))); };
  add('Clinics', r.clinics, c => ({ url: `#/clinics/${c.id}`, html: `${dot(c.color, c.color_label)}<strong>${esc(c.name)}</strong>${c.shorthand ? ` <span class="badge">${esc(c.shorthand)}</span>` : ''}<span class="muted"> · ${esc(c.address || '')}</span>` }));
  add('Contacts', r.contacts, c => ({ url: c.clinic_id ? `#/clinics/${c.clinic_id}` : '#/contacts', html: `👤 <strong>${esc(c.first_name)} ${esc(c.last_name || '')}</strong><span class="muted"> · ${esc(c.role)}${c.clinic_name ? ' · ' + esc(c.clinic_name) : ''}</span>` }));
  add('Locations', r.locations, l => ({ url: `#/clinics/${l.clinic_id}`, html: `📍 <strong>${esc(l.name)}</strong><span class="muted"> · ${esc(l.address || '')} · ${esc(l.clinic_name)}</span>` }));
  add('Tasks', r.tasks, t => ({ url: t.clinic_id ? `#/clinics/${t.clinic_id}` : '#/tasks', html: `☑ <span class="${t.done ? 'muted' : ''}">${esc(t.title)}</span><span class="muted"> · ${t.clinic_name ? esc(t.clinic_name) + ' · ' : ''}${t.due_date ? 'due ' + esc(t.due_date) : 'no date'}</span>` }));
  add('Notes', r.notes, n => ({ url: `#/clinics/${n.clinic_id}`, html: `📝 ${esc(n.body.length > 90 ? n.body.slice(0, 90) + '…' : n.body)}<span class="muted"> · ${esc(n.clinic_name)} · ${esc(fmtDate(n.created_at))}</span>` }));
  if (!items.length) { box.innerHTML = '<div class="palette-hint">No matches.</div>'; return; }
  active = 0;
  box.innerHTML = groups.map(g => `<div class="palette-group">${esc(g.title)}</div>` +
    items.slice(g.start, g.start + g.n).map((it, i) => `<div class="palette-item" data-i="${g.start + i}">${it.html}</div>`).join('')).join('');
  box.querySelectorAll('.palette-item').forEach(el => {
    el.onmouseenter = () => { active = Number(el.dataset.i); highlight(); };
    el.onclick = () => pick(Number(el.dataset.i));
  });
  highlight();
}

function move(d) { if (!items.length) return; active = (active + d + items.length) % items.length; highlight(); }
function highlight() {
  overlay.querySelectorAll('.palette-item').forEach(el => el.classList.toggle('active', Number(el.dataset.i) === active));
  const el = overlay.querySelector('.palette-item.active');
  if (el) el.scrollIntoView({ block: 'nearest' });
}
function pick(i) { const it = items[i]; if (!it) return; close(); navigate(it.url); }
