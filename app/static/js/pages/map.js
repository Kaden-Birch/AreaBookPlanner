// Map page: the hub. Coloured pins, clustering, heat map, near-me and route planning.
import { clinics, getMeta, planRoute, driveTime } from '../api.js';
import {
  esc, attr, dot, fmtDate, fmtMoney, relativeDays, fullAddress, directionsUrl, pinIcon, toast,
  COLOR_ORDER, COLOR_HEX, debounce, navigate, setTitle, haversineKm, getCurrentPosition, fmtKm, fmtMinutes,
} from '../ui.js';
import { openClinicForm, openAppointmentForm } from '../forms.js';

let map = null;
let markers = new Map();        // clinic id -> L.marker
let plainLayer = null;          // L.layerGroup (no clustering)
let clusterLayer = null;        // L.markerClusterGroup
let heatLayer = null;
let routeLayer = null;          // polyline + numbered stops
let nearLayer = null;           // circle + centre marker
let allClinics = [];
let driveCache = { key: null, data: null };

const state = {
  q: '', colors: new Set(COLOR_ORDER), placing: false, focusId: null,
  cluster: true, heat: false,
  // Near-me filter
  near: { on: false, centre: null, mode: 'km', km: 5, min: 15, staleOnly: false, picking: false },
  // Route planner
  route: { on: false, ids: [], start: null, startMode: 'first', picking: false, loop: false, result: null },
};

export async function render(container, params) {
  setTitle('Map');
  container.classList.add('full');
  const meta = await getMeta();
  state.focusId = params.get('focus') ? Number(params.get('focus')) : null;
  state.colors = params.get('color') ? new Set(params.get('color').split(',')) : new Set(COLOR_ORDER);
  if (params.get('route')) { state.route.on = true; state.route.ids = params.get('route').split(',').map(Number); }

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
          <div class="map-tools">
            <button class="btn btn-sm" id="toggle-all">All / none</button>
            <button class="btn btn-sm" id="fit-btn" title="Zoom to fit all visible pins">Fit</button>
            <button class="btn btn-sm ${state.cluster ? 'active' : ''}" id="cluster-btn" title="Group nearby pins when zoomed out">Cluster</button>
            <button class="btn btn-sm ${state.heat ? 'active' : ''}" id="heat-btn" title="Density heat map of visible clinics">Heat</button>
            <button class="btn btn-sm ${state.near.on ? 'active' : ''}" id="near-btn" title="Filter by distance or drive time from a point">Near me</button>
            <button class="btn btn-sm ${state.route.on ? 'active' : ''}" id="route-btn" title="Pick clinics and plan a driving route">Route</button>
            <button class="btn btn-sm btn-primary" id="place-btn" title="Click on the map to add a clinic at that spot">+ Place pin</button>
          </div>
        </div>
        <div class="sidebar-section ${state.near.on ? '' : 'hidden'}" id="near-panel"></div>
        <div class="sidebar-section ${state.route.on ? '' : 'hidden'}" id="route-panel"></div>
        <div class="sidebar-list" id="clinic-list"></div>
      </aside>
      <div class="map-container" id="map-container">
        <div id="map"></div>
        <div class="map-banner hidden" id="map-banner"><span id="banner-text"></span><button class="btn btn-sm" id="cancel-pick">Cancel</button></div>
      </div>
    </div>`;

  map = L.map(container.querySelector('#map')).setView([meta.map_default.lat, meta.map_default.lng], meta.map_default.zoom);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);
  plainLayer = L.layerGroup();
  clusterLayer = L.markerClusterGroup({
    maxClusterRadius: 50, disableClusteringAtZoom: 14, showCoverageOnHover: false, spiderfyOnMaxZoom: true,
    iconCreateFunction: clusterIcon,
  });
  routeLayer = L.layerGroup().addTo(map);
  nearLayer = L.layerGroup().addTo(map);
  (state.cluster ? clusterLayer : plainLayer).addTo(map);
  markers = new Map();

  map.on('click', onMapClick);

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
  container.querySelector('#cluster-btn').onclick = () => { state.cluster = !state.cluster; setActive('cluster-btn', state.cluster); swapPinLayer(); };
  container.querySelector('#heat-btn').onclick = () => { state.heat = !state.heat; setActive('heat-btn', state.heat); applyFilters(); };
  container.querySelector('#near-btn').onclick = () => { state.near.on = !state.near.on; setActive('near-btn', state.near.on); document.getElementById('near-panel').classList.toggle('hidden', !state.near.on); if (state.near.on) renderNearPanel(); else { nearLayer.clearLayers(); } applyFilters(); };
  container.querySelector('#route-btn').onclick = () => { state.route.on = !state.route.on; setActive('route-btn', state.route.on); document.getElementById('route-panel').classList.toggle('hidden', !state.route.on); if (state.route.on) renderRoutePanel(); else clearRoute(); applyFilters(); };
  container.querySelector('#place-btn').onclick = () => setPlacing(!state.placing);
  container.querySelector('#cancel-pick').onclick = () => { setPlacing(false); state.near.picking = false; state.route.picking = false; updateBanner(); };

  await load();
  if (state.near.on) renderNearPanel();
  if (state.route.on) renderRoutePanel();
  if (state.focusId) focusClinic(state.focusId);
}

export function destroy(container) {
  if (map) { map.remove(); map = null; }
  markers = new Map();
  container.classList.remove('full');
  state.placing = false;
  state.near.picking = false;
  state.route.picking = false;
}

// ---- Helpers -------------------------------------------------------------

function setActive(id, on) { document.getElementById(id).classList.toggle('active', on); }

function updateBanner() {
  const banner = document.getElementById('map-banner');
  const text = document.getElementById('banner-text');
  const cont = document.getElementById('map-container');
  let msg = null;
  if (state.placing) msg = 'Click anywhere on the map to add a clinic there';
  else if (state.near.picking) msg = 'Click the map to set the centre point';
  else if (state.route.picking) msg = 'Click the map to set the route start';
  banner.classList.toggle('hidden', !msg);
  cont.classList.toggle('picking', !!msg);
  if (msg) text.textContent = msg;
}

function setPlacing(on) {
  state.placing = on;
  document.getElementById('place-btn').classList.toggle('active', on);
  updateBanner();
}

function onMapClick(e) {
  const p = { lat: Number(e.latlng.lat.toFixed(6)), lng: Number(e.latlng.lng.toFixed(6)) };
  if (state.placing) {
    setPlacing(false);
    openClinicForm({ initial: p, onSaved: async (saved) => { await load(); focusClinic(saved.id); } });
  } else if (state.near.picking) {
    state.near.picking = false;
    state.near.centre = p;
    updateBanner();
    renderNearPanel();
    applyFilters();
  } else if (state.route.picking) {
    state.route.picking = false;
    state.route.start = p;
    state.route.startMode = 'point';
    updateBanner();
    renderRoutePanel();
    drawRoute();
  }
}

async function load() {
  allClinics = await clinics.list();
  plainLayer.clearLayers();
  clusterLayer.clearLayers();
  markers = new Map();
  const today = new Date().toISOString().slice(0, 10);
  for (const c of allClinics) {
    if (c.lat == null || c.lng == null) continue;
    const overdue = c.next_follow_up && c.next_follow_up < today && c.relationship !== 'do_not_contact';
    const m = L.marker([c.lat, c.lng], { icon: pinIcon(c.color, overdue ? 'pin-overdue' : ''), title: c.name });
    m.clinic = c;
    m.bindPopup(() => popupHtml(c), { maxWidth: 320 });
    m.on('popupopen', (e) => wirePopup(e.popup.getElement(), c, m));
    m.on('dragend', async () => {
      const p = m.getLatLng();
      try { await clinics.setLocation(c.id, p.lat, p.lng); c.lat = p.lat; c.lng = p.lng; toast('Pin moved', 'success'); }
      catch (err) { toast(err.message, 'error'); }
      m.dragging.disable();
    });
    markers.set(c.id, m);
  }
  driveCache = { key: null, data: null };
  applyFilters();
}

function swapPinLayer() {
  if (state.cluster) { map.removeLayer(plainLayer); clusterLayer.addTo(map); }
  else { map.removeLayer(clusterLayer); plainLayer.addTo(map); }
  applyFilters();
}

// Metric (km or minutes) from the near-me centre to a clinic, or null when unavailable.
function nearMetric(c) {
  const n = state.near;
  if (!n.centre || c.lat == null) return null;
  if (n.mode === 'min') {
    const d = driveCache.data && driveCache.data.clinics[c.id];
    return d ? d.minutes : null;
  }
  return haversineKm(n.centre, c);
}

function matches(c) {
  if (!state.colors.has(c.color)) return false;
  if (state.q) {
    const q = state.q.toLowerCase();
    if (![c.name, c.address, c.postal_code, c.tags, c.clinic_type, c.emr_system, c.notes].some(v => v && String(v).toLowerCase().includes(q))) return false;
  }
  if (state.near.on && state.near.centre) {
    const m = nearMetric(c);
    if (m == null) return false;
    if (m > (state.near.mode === 'min' ? state.near.min : state.near.km)) return false;
    if (state.near.staleOnly && (c.color === 'blue' || c.color === 'red')) return false;
  }
  return true;
}

function applyFilters() {
  const counts = {};
  COLOR_ORDER.forEach(c => { counts[c] = 0; });
  allClinics.forEach(c => { counts[c.color]++; });
  document.querySelectorAll('[data-count]').forEach(el => { el.textContent = counts[el.dataset.count] || 0; });

  let visible = allClinics.filter(matches);
  if (state.near.on && state.near.centre) {
    visible.sort((a, b) => (nearMetric(a) ?? 1e9) - (nearMetric(b) ?? 1e9));
  }
  const visibleIds = new Set(visible.map(c => c.id));
  const target = state.cluster ? clusterLayer : plainLayer;
  const toAdd = [];
  markers.forEach((m, id) => {
    const inLayer = target.hasLayer(m);
    if (visibleIds.has(id) && !inLayer) toAdd.push(m);
    else if (!visibleIds.has(id) && inLayer) target.removeLayer(m);
  });
  if (toAdd.length) { if (state.cluster) clusterLayer.addLayers(toAdd); else toAdd.forEach(m => plainLayer.addLayer(m)); }

  // Heat map of the visible set
  if (heatLayer) { map.removeLayer(heatLayer); heatLayer = null; }
  if (state.heat) {
    const pts = visible.filter(c => c.lat != null).map(c => [c.lat, c.lng, 0.6 + Math.min(1, (c.deal_value || 0) / 20000)]);
    heatLayer = L.heatLayer(pts, { radius: 35, blur: 25, minOpacity: 0.35, maxZoom: 15 }).addTo(map);
  }
  drawNear();
  renderList(visible);
}

function renderList(list) {
  const el = document.getElementById('clinic-list');
  if (!list.length) {
    el.innerHTML = `<div class="empty">No clinics match.<br><span class="small">${state.near.on && !state.near.centre ? 'Set a centre point in the “Near me” panel.' : 'Adjust the filters, or add one with “+ Place pin”.'}</span></div>`;
    return;
  }
  const routeOn = state.route.on;
  el.innerHTML = list.map(c => {
    const metric = state.near.on && state.near.centre ? nearMetric(c) : null;
    const metricText = metric == null ? '' : (state.near.mode === 'min' ? fmtMinutes(metric) : fmtKm(metric));
    return `
    <div class="clinic-item ${state.route.ids.includes(c.id) ? 'active' : ''}" data-id="${c.id}">
      ${routeOn ? `<input type="checkbox" data-route-id="${c.id}" ${state.route.ids.includes(c.id) ? 'checked' : ''} ${c.lat == null ? 'disabled' : ''} title="Add to route">` : ''}
      ${dot(c.color, c.color_label)}
      <div class="grow">
        <div class="name">${esc(c.name)}</div>
        <div class="sub">${esc(c.address || 'No address')}${c.lat == null ? ' · <em>not on map</em>' : ''}</div>
        <div class="sub">${c.last_visit ? `Last visit ${esc(relativeDays(c.last_visit))}` : 'Never visited'}${c.next_appointment ? ` · Next ${esc(fmtDate(c.next_appointment.start_time))}` : ''}</div>
      </div>
      ${metricText ? `<span class="metric">${metricText}</span>` : ''}
    </div>`;
  }).join('');
  el.querySelectorAll('.clinic-item').forEach(item => {
    item.onclick = (e) => {
      if (e.target.matches('input[type=checkbox]')) return;
      const id = Number(item.dataset.id);
      const c = allClinics.find(x => x.id === id);
      if (c.lat == null) { navigate(`#/clinics/${id}`); return; }
      focusClinic(id);
    };
  });
  el.querySelectorAll('[data-route-id]').forEach(cb => {
    cb.onchange = () => toggleRouteClinic(Number(cb.dataset.routeId), cb.checked);
  });
}

function focusClinic(id) {
  const m = markers.get(id);
  if (!m) return;
  map.setView(m.getLatLng(), Math.max(map.getZoom(), 15));
  // With clustering the marker may be inside a cluster; zoomToShowLayer handles that.
  if (state.cluster && clusterLayer.hasLayer(m)) clusterLayer.zoomToShowLayer(m, () => m.openPopup());
  else m.openPopup();
  document.querySelectorAll('.clinic-item').forEach(el => el.classList.toggle('active', Number(el.dataset.id) === id));
  const active = document.querySelector('.clinic-item.active');
  if (active) active.scrollIntoView({ block: 'nearest' });
}

function fitVisible() {
  const pts = [];
  const layer = state.cluster ? clusterLayer : plainLayer;
  markers.forEach(m => { if (layer.hasLayer(m)) pts.push(m.getLatLng()); });
  if (state.near.centre) pts.push(state.near.centre);
  if (!pts.length) return;
  map.fitBounds(L.latLngBounds(pts).pad(0.15));
}

function clusterIcon(cluster) {
  const kids = cluster.getAllChildMarkers();
  const counts = {};
  kids.forEach(k => { const col = k.clinic ? k.clinic.color : 'grey'; counts[col] = (counts[col] || 0) + 1; });
  let acc = 0;
  const stops = COLOR_ORDER.filter(c => counts[c]).map(c => {
    const from = acc / kids.length * 360; acc += counts[c];
    return `${COLOR_HEX[c]} ${from}deg ${acc / kids.length * 360}deg`;
  });
  return L.divIcon({
    html: `<div class="cluster-icon" style="background: conic-gradient(${stops.join(',')})"><span>${kids.length}</span></div>`,
    className: '', iconSize: [40, 40],
  });
}

function popupHtml(c) {
  return `
    <div class="popup-title">${dot(c.color, c.color_label)}${esc(c.name)}</div>
    <p><span class="badge badge-${esc(c.color)}">${esc(c.color_label)}</span> <span class="badge badge-stage-${esc(c.stage)}">${esc(c.stage_label)}</span> ${c.clinic_type ? `<span class="badge">${esc(c.clinic_type)}</span>` : ''}</p>
    <p class="muted">${esc(fullAddress(c)) || 'No address'}</p>
    ${c.phone ? `<p>☎ <a href="tel:${attr(c.phone)}">${esc(c.phone)}</a></p>` : ''}
    ${c.deal_value ? `<p class="small money">Deal: ${fmtMoney(c.deal_value)} · ${c.effective_probability}%</p>` : ''}
    <p class="small">Last visit: ${c.last_visit ? `${esc(fmtDate(c.last_visit))} (${esc(relativeDays(c.last_visit))})` : 'never'}</p>
    ${c.next_appointment ? `<p class="small">Next: ${esc(c.next_appointment.title)} · ${esc(fmtDate(c.next_appointment.start_time))}</p>` : ''}
    ${c.contact_count ? `<p class="small">${c.contact_count} contact${c.contact_count === 1 ? '' : 's'}</p>` : ''}
    <div class="popup-actions">
      <a class="btn btn-sm btn-primary" href="#/clinics/${c.id}">Open</a>
      <button class="btn btn-sm" data-act="appt">+ Appt</button>
      <button class="btn btn-sm" data-act="route">${state.route.ids.includes(c.id) ? '− Route' : '+ Route'}</button>
      <button class="btn btn-sm" data-act="move" title="Drag the pin to a new spot">Move pin</button>
      <a class="btn btn-sm" href="${attr(directionsUrl(c))}" target="_blank" rel="noopener">Directions</a>
    </div>`;
}

function wirePopup(el, c, marker) {
  if (!el) return;
  const appt = el.querySelector('[data-act=appt]');
  if (appt) appt.onclick = () => openAppointmentForm({ clinicId: c.id, lockClinic: true, onSaved: load });
  const move = el.querySelector('[data-act=move]');
  if (move) move.onclick = () => { marker.closePopup(); marker.dragging.enable(); toast('Drag the pin to its new location'); };
  const route = el.querySelector('[data-act=route]');
  if (route) route.onclick = () => {
    if (!state.route.on) { state.route.on = true; setActive('route-btn', true); document.getElementById('route-panel').classList.remove('hidden'); }
    toggleRouteClinic(c.id, !state.route.ids.includes(c.id));
    marker.closePopup();
  };
}

// ---- Near me -------------------------------------------------------------

function renderNearPanel() {
  const n = state.near;
  const panel = document.getElementById('near-panel');
  const isMin = n.mode === 'min';
  panel.innerHTML = `
    <h4>Near a point <button class="btn btn-sm" id="near-close">×</button></h4>
    <div class="flex mb">
      <button class="btn btn-sm" id="near-geo">📍 My location</button>
      <button class="btn btn-sm" id="near-pick">Click map</button>
      <span class="muted small grow">${n.centre ? `${n.centre.lat.toFixed(4)}, ${n.centre.lng.toFixed(4)}` : 'No centre set'}</span>
    </div>
    <div class="flex mb">
      <label class="checkbox"><input type="radio" name="near-mode" value="km" ${!isMin ? 'checked' : ''}> Distance</label>
      <label class="checkbox"><input type="radio" name="near-mode" value="min" ${isMin ? 'checked' : ''}> Drive time</label>
    </div>
    <div class="range-row">
      <input type="range" id="near-range" min="1" max="${isMin ? 60 : 30}" step="1" value="${isMin ? n.min : n.km}">
      <span class="val" id="near-val">${isMin ? fmtMinutes(n.min) : fmtKm(n.km)}</span>
    </div>
    <label class="checkbox mt"><input type="checkbox" id="near-stale" ${n.staleOnly ? 'checked' : ''}> Only clinics not visited in 3+ months</label>
    <div class="muted small mt" id="near-note">${isMin ? (driveCache.data ? (driveCache.data.source === 'osrm' ? 'Drive times from OpenStreetMap routing.' : 'Routing service unreachable — drive times are estimates.') : '') : 'Straight-line distance.'}</div>`;
  panel.querySelector('#near-close').onclick = () => document.getElementById('near-btn').click();
  panel.querySelector('#near-geo').onclick = async () => {
    try { n.centre = await getCurrentPosition(); renderNearPanel(); await ensureDriveTimes(); applyFilters(); map.setView(n.centre, Math.max(map.getZoom(), 12)); }
    catch (e) { toast(e.message, 'error'); }
  };
  panel.querySelector('#near-pick').onclick = () => { n.picking = true; state.route.picking = false; updateBanner(); };
  panel.querySelectorAll('[name=near-mode]').forEach(r => {
    r.onchange = async () => { n.mode = r.value; renderNearPanel(); await ensureDriveTimes(); applyFilters(); };
  });
  const range = panel.querySelector('#near-range');
  range.oninput = () => {
    if (isMin) n.min = Number(range.value); else n.km = Number(range.value);
    panel.querySelector('#near-val').textContent = isMin ? fmtMinutes(n.min) : fmtKm(n.km);
    applyFilters();
  };
  panel.querySelector('#near-stale').onchange = (e) => { n.staleOnly = e.target.checked; applyFilters(); };
}

async function ensureDriveTimes() {
  const n = state.near;
  if (n.mode !== 'min' || !n.centre) return;
  const key = `${n.centre.lat.toFixed(4)},${n.centre.lng.toFixed(4)}`;
  if (driveCache.key === key) return;
  const note = document.getElementById('near-note');
  if (note) note.textContent = 'Calculating drive times…';
  try {
    driveCache = { key, data: await driveTime(n.centre.lat, n.centre.lng) };
  } catch (e) { toast(e.message, 'error'); return; }
  if (note) note.textContent = driveCache.data.source === 'osrm' ? 'Drive times from OpenStreetMap routing.' : 'Routing service unreachable — drive times are estimates.';
}

function drawNear() {
  nearLayer.clearLayers();
  const n = state.near;
  if (!n.on || !n.centre) return;
  L.marker(n.centre, { icon: L.divIcon({ className: '', html: '<div class="start-pin"></div>', iconSize: [16, 16], iconAnchor: [8, 8] }), interactive: false }).addTo(nearLayer);
  if (n.mode === 'km') {
    L.circle(n.centre, { radius: n.km * 1000, color: '#2b6fd6', weight: 1.5, fillOpacity: 0.06, interactive: false }).addTo(nearLayer);
  }
}

// ---- Route planner -------------------------------------------------------

function toggleRouteClinic(id, on) {
  const r = state.route;
  if (on && !r.ids.includes(id)) r.ids.push(id);
  if (!on) r.ids = r.ids.filter(x => x !== id);
  r.result = null;
  renderRoutePanel();
  renderList(allClinics.filter(matches));
  drawRoute();
}

function clearRoute() {
  state.route = { ...state.route, on: false, ids: [], result: null, picking: false };
  routeLayer.clearLayers();
  updateBanner();
}

function renderRoutePanel() {
  const r = state.route;
  const panel = document.getElementById('route-panel');
  const selected = r.ids.map(id => allClinics.find(c => c.id === id)).filter(Boolean);
  const res = r.result;
  panel.innerHTML = `
    <h4>Route planner <button class="btn btn-sm" id="route-close">×</button></h4>
    <div class="muted small mb">Tick clinics in the list below (or “+ Route” in a pin popup), then optimise.</div>
    <div class="flex mb flex-wrap">
      <span class="small"><strong>Start:</strong></span>
      <button class="btn btn-sm ${r.startMode === 'geo' ? 'active' : ''}" id="route-geo">📍 My location</button>
      <button class="btn btn-sm ${r.startMode === 'point' ? 'active' : ''}" id="route-pick">Click map</button>
      <button class="btn btn-sm ${r.startMode === 'first' ? 'active' : ''}" id="route-first">First stop</button>
    </div>
    <label class="checkbox mb"><input type="checkbox" id="route-loop" ${r.loop ? 'checked' : ''} ${r.startMode === 'first' ? 'disabled' : ''}> Return to start</label>
    <div class="flex mb">
      <button class="btn btn-sm btn-primary" id="route-go" ${selected.length < 1 ? 'disabled' : ''}>Optimise ${selected.length ? `(${selected.length})` : ''}</button>
      <button class="btn btn-sm" id="route-clear" ${selected.length ? '' : 'disabled'}>Clear</button>
      ${res ? `<a class="btn btn-sm" href="${attr(res.google_maps_url)}" target="_blank" rel="noopener">Open in Google Maps</a>` : ''}
    </div>
    ${res ? `
      <div class="small mb"><strong>${fmtKm(res.total_km)}</strong> · about <strong>${fmtMinutes(res.total_minutes)}</strong> driving${res.source === 'estimate' ? ' <span class="muted">(estimated)</span>' : ''}${res.stops.length > 10 ? ' <span class="muted">· Google Maps link limited to the first 10 stops</span>' : ''}</div>
      <div id="route-stops">${res.stops.map((s, i) => `
        <div class="route-stop" data-id="${s.id}">
          <span class="num">${i + 1}</span>
          <div><div><strong>${esc(s.name)}</strong></div><div class="muted">${esc(s.address || '')}</div></div>
          <span class="leg">${i === 0 && !r.start ? 'start' : `+${fmtKm(s.leg_km)} · ${fmtMinutes(s.leg_minutes)}`}</span>
        </div>`).join('')}</div>`
    : (selected.length ? `<div class="small muted">${selected.map(c => esc(c.name)).join(' · ')}</div>` : '')}`;

  panel.querySelector('#route-close').onclick = () => document.getElementById('route-btn').click();
  panel.querySelector('#route-geo').onclick = async () => {
    try { r.start = await getCurrentPosition(); r.startMode = 'geo'; r.result = null; renderRoutePanel(); drawRoute(); }
    catch (e) { toast(e.message, 'error'); }
  };
  panel.querySelector('#route-pick').onclick = () => { r.picking = true; state.near.picking = false; updateBanner(); };
  panel.querySelector('#route-first').onclick = () => { r.start = null; r.startMode = 'first'; r.loop = false; r.result = null; renderRoutePanel(); drawRoute(); };
  panel.querySelector('#route-loop').onchange = (e) => { r.loop = e.target.checked; r.result = null; renderRoutePanel(); };
  panel.querySelector('#route-clear').onclick = () => { r.ids = []; r.result = null; renderRoutePanel(); renderList(allClinics.filter(matches)); drawRoute(); };
  panel.querySelector('#route-go').onclick = optimiseRoute;
  panel.querySelectorAll('.route-stop').forEach(el => { el.onclick = () => focusClinic(Number(el.dataset.id)); el.style.cursor = 'pointer'; });
}

async function optimiseRoute() {
  const r = state.route;
  const btn = document.getElementById('route-go');
  btn.disabled = true; btn.textContent = 'Optimising…';
  try {
    r.result = await planRoute({ clinic_ids: r.ids, start: r.startMode === 'first' ? null : r.start, return_to_start: r.loop && r.startMode !== 'first' });
    // keep selection in optimised order so re-runs are stable
    r.ids = r.result.stops.map(s => s.id);
    if (r.result.skipped.length) toast(`${r.result.skipped.length} clinic(s) skipped: not on the map`, 'error');
    renderRoutePanel();
    drawRoute();
    const pts = r.result.stops.map(s => [s.lat, s.lng]);
    if (r.start) pts.push([r.start.lat, r.start.lng]);
    map.fitBounds(L.latLngBounds(pts).pad(0.2));
  } catch (e) {
    toast(e.message, 'error');
    renderRoutePanel();
  }
}

function drawRoute() {
  routeLayer.clearLayers();
  const r = state.route;
  if (!r.on) return;
  if (r.start) {
    L.marker(r.start, { icon: L.divIcon({ className: '', html: '<div class="start-pin" title="Start"></div>', iconSize: [16, 16], iconAnchor: [8, 8] }), interactive: false }).addTo(routeLayer);
  }
  if (!r.result) return;
  const stops = r.result.stops;
  const line = r.result.geometry || [
    ...(r.start ? [[r.start.lat, r.start.lng]] : []),
    ...stops.map(s => [s.lat, s.lng]),
    ...(r.loop && r.start ? [[r.start.lat, r.start.lng]] : []),
  ];
  L.polyline(line, { color: '#2b6fd6', weight: 4, opacity: 0.8 }).addTo(routeLayer);
  stops.forEach((s, i) => {
    L.marker([s.lat, s.lng], {
      icon: L.divIcon({ className: '', html: `<div class="route-num">${i + 1}</div>`, iconSize: [22, 22], iconAnchor: [11, 30] }),
      interactive: false, zIndexOffset: 1000,
    }).addTo(routeLayer);
  });
}
