// Map page: the hub. Coloured pins for every clinic with a filterable sidebar.
import { clinics, getMeta } from '../api.js';
import {
  esc, attr, dot, fmtDate, relativeDays, fullAddress, directionsUrl, pinIcon, toast,
  COLOR_ORDER, debounce, navigate, setTitle,
} from '../ui.js';
import { openClinicForm, openAppointmentForm } from '../forms.js';

let map = null;
let markers = new Map(); // clinic id -> L.marker
let allClinics = [];
let state = { q: '', colors: new Set(COLOR_ORDER), placing: false, focusId: null };

export async function render(container, params) {
  setTitle('Map');
  container.classList.add('full');
  const meta = await getMeta();
  state.focusId = params.get('focus') ? Number(params.get('focus')) : null;
  if (params.get('color')) state.colors = new Set(params.get('color').split(','));
  else state.colors = new Set(COLOR_ORDER);

  container.innerHTML = `
    <div class="map-layout">
      <aside class="map-sidebar">
        <div class="sidebar-top">
          <input type="search" id="map-search" placeholder="Search clinics, addresses, tags…" value="${attr(state.q)}">
          <div class="legend-filter" id="legend-filter">
            ${COLOR_ORDER.map(c => `
              <label><input type="checkbox" data-color="${c}" ${state.colors.has(c) ? 'checked' : ''}>
                ${dot(c)} ${esc(meta.colors[c])} <span class="count" data-count="${c}"></span></label>`).join('')}
          </div>
          <div class="flex mt">
            <button class="btn btn-sm" id="toggle-all">All / none</button>
            <button class="btn btn-sm" id="fit-btn" title="Zoom to fit all visible pins">Fit pins</button>
            <button class="btn btn-sm btn-primary" id="place-btn" title="Click on the map to add a clinic at that spot">+ Place pin</button>
          </div>
        </div>
        <div class="sidebar-list" id="clinic-list"></div>
      </aside>
      <div class="map-container" id="map-container">
        <div id="map"></div>
        <div class="map-banner hidden" id="place-banner">
          <span>Click anywhere on the map to add a clinic there</span>
          <button class="btn btn-sm" id="cancel-place">Cancel</button>
        </div>
      </div>
    </div>`;

  map = L.map(container.querySelector('#map')).setView([meta.map_default.lat, meta.map_default.lng], meta.map_default.zoom);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);
  markers = new Map();

  map.on('click', (e) => {
    if (!state.placing) return;
    setPlacing(false);
    openClinicForm({
      initial: { lat: Number(e.latlng.lat.toFixed(6)), lng: Number(e.latlng.lng.toFixed(6)) },
      onSaved: async (saved) => { await load(); focusClinic(saved.id); },
    });
  });

  const search = container.querySelector('#map-search');
  search.addEventListener('input', debounce(() => { state.q = search.value; applyFilters(); }, 150));
  container.querySelectorAll('#legend-filter input').forEach(cb => {
    cb.addEventListener('change', () => {
      if (cb.checked) state.colors.add(cb.dataset.color); else state.colors.delete(cb.dataset.color);
      applyFilters();
    });
  });
  container.querySelector('#toggle-all').onclick = () => {
    const all = state.colors.size === COLOR_ORDER.length;
    state.colors = new Set(all ? [] : COLOR_ORDER);
    container.querySelectorAll('#legend-filter input').forEach(cb => { cb.checked = !all; });
    applyFilters();
  };
  container.querySelector('#fit-btn').onclick = fitVisible;
  container.querySelector('#place-btn').onclick = () => setPlacing(!state.placing);
  container.querySelector('#cancel-place').onclick = () => setPlacing(false);

  await load();
  if (state.focusId) focusClinic(state.focusId);
  else if (allClinics.some(c => c.lat != null)) { /* keep Calgary default view */ }
}

export function destroy(container) {
  if (map) { map.remove(); map = null; }
  markers = new Map();
  container.classList.remove('full');
  state.placing = false;
}

function setPlacing(on) {
  state.placing = on;
  document.getElementById('map-container').classList.toggle('placing', on);
  document.getElementById('place-banner').classList.toggle('hidden', !on);
  document.getElementById('place-btn').classList.toggle('active', on);
}

async function load() {
  allClinics = await clinics.list();
  // rebuild markers
  markers.forEach(m => m.remove());
  markers = new Map();
  for (const c of allClinics) {
    if (c.lat == null || c.lng == null) continue;
    const m = L.marker([c.lat, c.lng], { icon: pinIcon(c.color), title: c.name });
    m.bindPopup(() => popupHtml(c), { maxWidth: 320 });
    m.on('popupopen', (e) => wirePopup(e.popup.getElement(), c, m));
    m.on('dragend', async () => {
      const p = m.getLatLng();
      try {
        await clinics.setLocation(c.id, p.lat, p.lng);
        c.lat = p.lat; c.lng = p.lng;
        toast('Pin moved', 'success');
      } catch (err) { toast(err.message, 'error'); }
      m.dragging.disable();
    });
    markers.set(c.id, m);
  }
  applyFilters();
}

function matches(c) {
  if (!state.colors.has(c.color)) return false;
  if (!state.q) return true;
  const q = state.q.toLowerCase();
  return [c.name, c.address, c.postal_code, c.tags, c.clinic_type, c.emr_system, c.notes]
    .some(v => v && String(v).toLowerCase().includes(q));
}

function applyFilters() {
  const counts = {};
  COLOR_ORDER.forEach(c => { counts[c] = 0; });
  allClinics.forEach(c => { counts[c.color]++; });
  document.querySelectorAll('[data-count]').forEach(el => { el.textContent = counts[el.dataset.count] || 0; });

  const visible = allClinics.filter(matches);
  const visibleIds = new Set(visible.map(c => c.id));
  markers.forEach((m, id) => {
    if (visibleIds.has(id)) { if (!map.hasLayer(m)) m.addTo(map); }
    else if (map.hasLayer(m)) m.remove();
  });
  renderList(visible);
}

function renderList(list) {
  const el = document.getElementById('clinic-list');
  if (!list.length) { el.innerHTML = '<div class="empty">No clinics match.<br><span class="small">Add one with “+ Place pin” or the “+ Clinic” button.</span></div>'; return; }
  el.innerHTML = list.map(c => `
    <div class="clinic-item" data-id="${c.id}">
      ${dot(c.color, c.color_label)}
      <div class="grow">
        <div class="name">${esc(c.name)}</div>
        <div class="sub">${esc(c.address || 'No address')}${c.lat == null ? ' · <em>not on map</em>' : ''}</div>
        <div class="sub">${c.last_visit ? `Last visit ${esc(relativeDays(c.last_visit))}` : 'Never visited'}${c.next_appointment ? ` · Next ${esc(fmtDate(c.next_appointment.start_time))}` : ''}</div>
      </div>
    </div>`).join('');
  el.querySelectorAll('.clinic-item').forEach(item => {
    item.onclick = () => {
      const id = Number(item.dataset.id);
      const c = allClinics.find(x => x.id === id);
      if (c.lat == null) { navigate(`#/clinics/${id}`); return; }
      focusClinic(id);
    };
  });
}

function focusClinic(id) {
  const m = markers.get(id);
  if (!m) return;
  if (!map.hasLayer(m)) m.addTo(map);
  map.setView(m.getLatLng(), Math.max(map.getZoom(), 14));
  m.openPopup();
  document.querySelectorAll('.clinic-item').forEach(el => el.classList.toggle('active', Number(el.dataset.id) === id));
  const active = document.querySelector('.clinic-item.active');
  if (active) active.scrollIntoView({ block: 'nearest' });
}

function fitVisible() {
  const pts = [];
  markers.forEach(m => { if (map.hasLayer(m)) pts.push(m.getLatLng()); });
  if (!pts.length) return;
  map.fitBounds(L.latLngBounds(pts).pad(0.15));
}

function popupHtml(c) {
  return `
    <div class="popup-title">${dot(c.color, c.color_label)}${esc(c.name)}</div>
    <p><span class="badge badge-${esc(c.color)}">${esc(c.color_label)}</span> ${c.clinic_type ? `<span class="badge">${esc(c.clinic_type)}</span>` : ''}</p>
    <p class="muted">${esc(fullAddress(c)) || 'No address'}</p>
    ${c.phone ? `<p>☎ <a href="tel:${attr(c.phone)}">${esc(c.phone)}</a></p>` : ''}
    <p class="small">Last visit: ${c.last_visit ? `${esc(fmtDate(c.last_visit))} (${esc(relativeDays(c.last_visit))})` : 'never'}</p>
    ${c.next_appointment ? `<p class="small">Next: ${esc(c.next_appointment.title)} · ${esc(fmtDate(c.next_appointment.start_time))}</p>` : ''}
    ${c.contact_count ? `<p class="small">${c.contact_count} contact${c.contact_count === 1 ? '' : 's'}</p>` : ''}
    <div class="popup-actions">
      <a class="btn btn-sm btn-primary" href="#/clinics/${c.id}">Open</a>
      <button class="btn btn-sm" data-act="appt">+ Appt</button>
      <button class="btn btn-sm" data-act="move" title="Drag the pin to a new spot">Move pin</button>
      <a class="btn btn-sm" href="${attr(directionsUrl(c))}" target="_blank" rel="noopener">Directions</a>
    </div>`;
}

function wirePopup(el, c, marker) {
  if (!el) return;
  const appt = el.querySelector('[data-act=appt]');
  if (appt) appt.onclick = () => openAppointmentForm({ clinicId: c.id, lockClinic: true, onSaved: load });
  const move = el.querySelector('[data-act=move]');
  if (move) move.onclick = () => {
    marker.closePopup();
    marker.dragging.enable();
    toast('Drag the pin to its new location');
  };
}
