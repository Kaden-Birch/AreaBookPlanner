// Shared UI helpers: escaping, formatting, modals, toasts, confirm dialogs.

export const COLOR_HEX = {
  yellow: '#f5c400', green: '#2e9e44', blue: '#2b6fd6', grey: '#8a8f98', white: '#ffffff', red: '#d9342b',
};
export const COLOR_ORDER = ['yellow', 'green', 'blue', 'grey', 'white', 'red'];

export function esc(v) {
  if (v === null || v === undefined) return '';
  return String(v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

export function attr(v) { return esc(v); }

// ---- Dates ------------------------------------------------------------
const DATE_OPTS = { year: 'numeric', month: 'short', day: 'numeric' };
const TIME_OPTS = { hour: 'numeric', minute: '2-digit' };

export function parseDate(v) {
  if (!v) return null;
  const d = new Date(v);
  return isNaN(d.getTime()) ? null : d;
}
export function fmtDate(v) {
  const d = parseDate(v);
  return d ? d.toLocaleDateString(undefined, DATE_OPTS) : '';
}
export function fmtTime(v) {
  const d = parseDate(v);
  return d ? d.toLocaleTimeString(undefined, TIME_OPTS) : '';
}
export function fmtDateTime(v) {
  const d = parseDate(v);
  return d ? `${d.toLocaleDateString(undefined, { weekday: 'short', ...DATE_OPTS })}, ${d.toLocaleTimeString(undefined, TIME_OPTS)}` : '';
}
export function fmtDateOnly(v) {
  // v is YYYY-MM-DD; avoid timezone shift by constructing local date
  if (!v) return '';
  const [y, m, d] = v.split('-').map(Number);
  if (!y || !m || !d) return v;
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { weekday: 'short', ...DATE_OPTS });
}
export function relativeDays(v) {
  const d = parseDate(v);
  if (!d) return '';
  const days = Math.round((Date.now() - d.getTime()) / 86400000);
  if (days === 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days === -1) return 'tomorrow';
  if (days > 0) return `${days} days ago`;
  return `in ${-days} days`;
}
export function toLocalInput(d) {
  // Date -> YYYY-MM-DDTHH:MM for datetime-local inputs
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}
export function toDateInput(d) {
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
export function isPast(v) {
  const d = parseDate(v);
  return d ? d.getTime() < Date.now() : false;
}

// ---- Small components --------------------------------------------------
export function dot(color, title, large = false) {
  return `<span class="dot dot-${esc(color)}${large ? ' dot-lg' : ''}" title="${attr(title || '')}"></span>`;
}
export function badge(text, cls = '') {
  return `<span class="badge ${esc(cls)}">${esc(text)}</span>`;
}
export function colorBadge(clinic) {
  return `<span class="badge badge-${esc(clinic.color)}">${dot(clinic.color)}${esc(clinic.color_label)}</span>`;
}
export function tagList(tags) {
  return (tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join('');
}
export function directionsUrl(clinic) {
  if (clinic.lat != null && clinic.lng != null) {
    return `https://www.google.com/maps/dir/?api=1&destination=${clinic.lat},${clinic.lng}`;
  }
  const q = [clinic.address, clinic.city, clinic.province, clinic.postal_code].filter(Boolean).join(', ');
  return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(q)}`;
}
export function fullAddress(c) {
  return [c.address, c.city, c.province, c.postal_code].filter(Boolean).join(', ');
}
export function options(map, selected, { blank } = {}) {
  let html = blank !== undefined ? `<option value="">${esc(blank)}</option>` : '';
  for (const [value, label] of Object.entries(map)) {
    html += `<option value="${attr(value)}"${String(value) === String(selected) ? ' selected' : ''}>${esc(label)}</option>`;
  }
  return html;
}

// ---- Toasts ------------------------------------------------------------
export function toast(message, type = 'info', ms = 3000) {
  const root = document.getElementById('toast-root');
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = message;
  root.appendChild(el);
  setTimeout(() => el.remove(), ms);
}

// ---- Modals ------------------------------------------------------------
export function openModal({ title, body, footer, size = '', onMount, onClose }) {
  const root = document.getElementById('modal-root');
  const backdrop = document.createElement('div');
  backdrop.className = 'modal-backdrop';
  backdrop.innerHTML = `
    <div class="modal ${size}" role="dialog" aria-modal="true">
      <div class="modal-header"><h2>${esc(title)}</h2><button class="close" aria-label="Close">&times;</button></div>
      <div class="modal-body"></div>
      ${footer !== undefined ? `<div class="modal-footer">${footer}</div>` : ''}
    </div>`;
  const bodyEl = backdrop.querySelector('.modal-body');
  if (typeof body === 'string') bodyEl.innerHTML = body; else bodyEl.appendChild(body);
  root.appendChild(backdrop);

  let closed = false;
  const close = (result) => {
    if (closed) return;
    closed = true;
    backdrop.remove();
    document.removeEventListener('keydown', onKey);
    onClose && onClose(result);
  };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', onKey);
  backdrop.querySelector('.close').addEventListener('click', () => close());
  backdrop.addEventListener('mousedown', (e) => { if (e.target === backdrop) close(); });

  const modal = { root: backdrop, body: bodyEl, close };
  onMount && onMount(modal);
  const first = bodyEl.querySelector('input:not([type=hidden]), select, textarea');
  if (first) setTimeout(() => first.focus(), 30);
  return modal;
}

export function confirmDialog(message, { title = 'Please confirm', okLabel = 'Delete', danger = true } = {}) {
  return new Promise((resolve) => {
    const modal = openModal({
      title,
      size: 'modal-sm',
      body: `<p>${esc(message)}</p>`,
      footer: `<button class="btn" data-act="cancel">Cancel</button>
               <button class="btn ${danger ? 'btn-danger' : 'btn-primary'}" data-act="ok">${esc(okLabel)}</button>`,
      onClose: () => resolve(false),
    });
    modal.root.querySelector('[data-act=cancel]').onclick = () => modal.close();
    modal.root.querySelector('[data-act=ok]').onclick = () => { resolve(true); modal.close(); };
  });
}

// Read all named fields of a form element into a plain object.
export function formData(form) {
  const out = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === 'checkbox') out[el.name] = el.checked;
    else if (el.type === 'number') out[el.name] = el.value === '' ? null : Number(el.value);
    else out[el.name] = el.value;
  }
  return out;
}

export function showFormError(form, message) {
  let box = form.querySelector('.form-error');
  if (!message) { box && box.remove(); return; }
  if (!box) {
    box = document.createElement('div');
    box.className = 'form-error';
    form.prepend(box);
  }
  box.textContent = message;
  box.scrollIntoView({ block: 'nearest' });
}

export function navigate(hash) { window.location.hash = hash; }

// ---- Money ---------------------------------------------------------------
const moneyFmt = new Intl.NumberFormat('en-CA', { style: 'currency', currency: 'CAD', maximumFractionDigits: 0 });
export function fmtMoney(v) {
  if (v === null || v === undefined || v === '' || isNaN(Number(v))) return '';
  return moneyFmt.format(Number(v));
}
export function fmtKm(km) { return km == null ? '' : `${Number(km).toFixed(km < 10 ? 1 : 0)} km`; }
export function fmtMinutes(m) {
  if (m == null) return '';
  m = Math.round(m);
  return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`;
}

// ---- Theme ---------------------------------------------------------------
export function getTheme() { return document.documentElement.getAttribute('data-theme') || 'light'; }
export function setTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  try { localStorage.setItem('theme', t); } catch { /* private mode */ }
  document.dispatchEvent(new CustomEvent('themechange', { detail: t }));
}
export function toggleTheme() { setTheme(getTheme() === 'dark' ? 'light' : 'dark'); }

// ---- Geo -----------------------------------------------------------------
export function haversineKm(a, b) {
  const R = 6371, toRad = d => d * Math.PI / 180;
  const dLat = toRad(b.lat - a.lat), dLng = toRad(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
export function getCurrentPosition() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) { reject(new Error('Geolocation is not available in this browser')); return; }
    navigator.geolocation.getCurrentPosition(
      p => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }),
      err => reject(new Error(err.code === 1 ? 'Location permission denied. Click the map to set a point instead.' : 'Could not get your location. Click the map to set a point instead.')),
      { enableHighAccuracy: true, timeout: 8000 },
    );
  });
}
// ---- Rep name (per browser) ---------------------------------------------
export function getRepName() { try { return localStorage.getItem('rep_name') || ''; } catch { return ''; } }
export function setRepName(v) { try { localStorage.setItem('rep_name', v || ''); } catch { /* ignore */ } }

// ---- Email templates -----------------------------------------------------
export function fillTemplate(text, ctx) {
  return (text || '').replace(/\{(\w+)\}/g, (m, k) => (ctx[k] !== undefined && ctx[k] !== null ? String(ctx[k]) : m));
}
export function mailtoUrl(email, subject, body) {
  return `mailto:${encodeURIComponent(email || '')}?subject=${encodeURIComponent(subject || '')}&body=${encodeURIComponent(body || '')}`;
}
export function shorthandBadge(clinic) {
  return clinic.shorthand ? `<span class="badge badge-shorthand" title="Client shorthand">${esc(clinic.shorthand)}</span>` : '';
}

export function stageBadge(clinic) {
  return `<span class="badge badge-stage-${esc(clinic.stage)}">${esc(clinic.stage_label || clinic.stage)}</span>`;
}

export function setTitle(t) { document.title = t ? `${t} · Area Book Planner` : 'Area Book Planner'; }

export function debounce(fn, ms = 250) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

// Leaflet marker icon for a clinic colour.
export function pinIcon(color, extraClass = '', label = '') {
  return L.divIcon({
    className: '',
    html: `<div class="pin pin-${esc(color)} ${esc(extraClass)}">${label ? `<span class="pin-label">${esc(label)}</span>` : ''}</div>`,
    iconSize: [20, 20],
    iconAnchor: [10, 10],
    popupAnchor: [0, -10],
  });
}
// Smaller, dashed pin for a secondary (sister) location of a clinic.
export function secondaryPinIcon(color) {
  return L.divIcon({
    className: '',
    html: `<div class="pin pin-secondary pin-${esc(color)}"></div>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
    popupAnchor: [0, -8],
  });
}
