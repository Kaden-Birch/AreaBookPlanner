// Equipment page for one clinic: list view and network topology view.
import { clinics, devices } from '../api.js';
import { esc, attr, options, debounce, setTitle, shorthandBadge, dot } from '../ui.js';
import { openDeviceForm, openDeviceDetail, accentClass, deviceSubtitle, plural } from '../equipment.js';

let state = { view: 'list', q: '', type: '', status: '', zoom: 1 };
let clinic = null, meta = null;

export async function render(container, params, routeParams) {
  const id = Number(routeParams.id);
  try { clinic = await clinics.get(id); } catch { container.innerHTML = '<div class="card empty">Clinic not found.</div>'; return; }
  meta = await devices.meta();
  setTitle(`Equipment · ${clinic.shorthand || clinic.name}`);
  container.classList.add('wide');
  if (params.get('view')) state.view = params.get('view');
  if (params.get('type')) state.type = params.get('type');

  container.innerHTML = `
    <div class="mb"><a href="#/clinics/${clinic.id}">← ${esc(clinic.name)}</a></div>
    <div class="page-header">
      <h1>${shorthandBadge(clinic)} Equipment</h1>
      <span class="muted" id="equip-count"></span>
      <div class="actions">
        <div class="seg" style="display:inline-flex;border:1px solid var(--border);border-radius:7px;overflow:hidden">
          <button class="btn ${state.view === 'list' ? 'active' : ''}" data-view="list" style="border:none;border-radius:0">☰ List</button>
          <button class="btn ${state.view === 'topology' ? 'active' : ''}" data-view="topology" style="border:none;border-radius:0;border-left:1px solid var(--border)">🕸 Topology</button>
        </div>
        <a class="btn" href="${devices.csvUrl(clinic.id)}" download>Export CSV</a>
        <button class="btn btn-primary" id="add-device">+ Add equipment</button>
      </div>
    </div>
    <div id="summary" class="mb"></div>
    <div class="equip-toolbar" id="list-tools">
      <input type="search" class="search" id="q" placeholder="Search name, IP, user, serial, model…" value="${attr(state.q)}">
      <select id="type"><option value="">All types</option>${Object.entries(meta.types).map(([k, v]) => `<option value="${k}" ${state.type === k ? 'selected' : ''}>${esc(v.icon)} ${esc(v.label)}</option>`).join('')}</select>
      <select id="status">${options({ '': 'Active + spare', active: 'Active only', spare: 'Spare', retired: 'Retired', all: 'Everything' }, state.status)}</select>
    </div>
    <div id="equip-body"></div>`;

  container.querySelectorAll('[data-view]').forEach(b => { b.onclick = () => { state.view = b.dataset.view; container.querySelectorAll('[data-view]').forEach(x => x.classList.toggle('active', x === b)); load(); }; });
  container.querySelector('#add-device').onclick = () => openDeviceForm({ clinic, onSaved: load });
  const q = container.querySelector('#q');
  q.addEventListener('input', debounce(() => { state.q = q.value; load(); }, 150));
  container.querySelector('#type').onchange = (e) => { state.type = e.target.value; load(); };
  container.querySelector('#status').onchange = (e) => { state.status = e.target.value; load(); };
  await load();
  if (params.get('device')) openDeviceDetail({ deviceId: Number(params.get('device')), clinic, onChanged: load });
}

export function destroy(container) { container.classList.remove('wide'); }

async function load() {
  const data = await devices.list(clinic.id, { q: state.q, device_type: state.type });
  let list = data.devices;
  if (state.status === '') list = list.filter(d => d.status !== 'retired');
  else if (state.status !== 'all') list = list.filter(d => d.status === state.status);
  document.getElementById('equip-count').textContent = `${data.summary.active} active · ${data.summary.total} total`;
  renderSummary(data.summary);
  document.getElementById('list-tools').classList.toggle('hidden', state.view !== 'list');
  const body = document.getElementById('equip-body');
  if (state.view === 'list') renderList(body, list, data);
  else await renderTopology(body);
}

function renderSummary(s) {
  const el = document.getElementById('summary');
  const chips = Object.entries(meta.types).map(([k, v]) => {
    const b = s.by_type[k];
    if (!b) return '';
    return `<span class="type-chip ${b.active ? '' : 'muted'}" title="${b.active} active, ${b.spare} spare, ${b.retired} retired">${esc(v.icon)} ${esc(plural(v.label, b.total))} <span class="n">${b.active}${b.total !== b.active ? `/${b.total}` : ''}</span></span>`;
  }).join('');
  const bl = s.billable;
  el.innerHTML = `${chips || '<span class="muted">No equipment recorded yet.</span>'}
    <div class="muted small mt">For billing later: <strong>${bl.workstations}</strong> workstations/laptops · <strong>${bl.servers}</strong> servers · <strong>${bl.network}</strong> network devices · <strong>${bl.phones}</strong> phones · <strong>${bl.printers}</strong> printers (active only)</div>`;
}

function renderList(body, list, data) {
  if (!list.length) { body.innerHTML = '<div class="card empty">No devices match. Click “+ Add equipment” to record the first one — a firewall or router is a good place to start.</div>'; return; }
  const groups = {};
  for (const d of list) (groups[d.device_type] ||= []).push(d);
  const order = Object.keys(meta.types).filter(t => groups[t]);
  body.innerHTML = `<div class="table-wrap"><table class="table equip-table">
    <thead><tr><th>Name</th><th>Designation / model</th><th>User</th><th>IP</th><th>Uplink</th><th>Status</th><th></th></tr></thead>
    <tbody>${order.map(t => `
      <tr class="group-row"><td colspan="7">${esc(meta.types[t].icon)} ${esc(plural(meta.types[t].label, groups[t].length))} <span class="muted">(${groups[t].length})</span><button class="btn btn-sm" data-add-type="${t}">+ Add ${esc(meta.types[t].label.toLowerCase())}</button></td></tr>
      ${groups[t].map(d => `
        <tr class="clickable ${d.status}" data-id="${d.id}">
          <td class="name">${esc(d.name)}${d.location_name ? ` <span class="muted small">· ${esc(d.location_name)}</span>` : ''}</td>
          <td>${esc([d.designation, [d.manufacturer, d.model].filter(Boolean).join(' ')].filter(Boolean).join(' · '))}${d.device_type === 'server' && d.services.length ? `<div class="muted small">${esc(d.services.slice(0, 4).join(', '))}${d.services.length > 4 ? '…' : ''}</div>` : ''}${d.os ? `<div class="muted small">${esc(d.os)}</div>` : ''}</td>
          <td>${esc(d.user_name || '')}</td>
          <td class="mono">${esc(d.ip_address || '')}</td>
          <td>${d.uplink_name ? `<span class="link-icon" title="${d.link_type === 'wireless' ? 'Wireless' : 'Wired'}">${d.link_type === 'wireless' ? '📶' : '🔌'}</span> ${esc(d.uplink_icon || '')} ${esc(d.uplink_name)}` : '<span class="muted">—</span>'}${d.downlink_count ? ` <span class="badge" title="Devices plugged into this">${d.downlink_count} ↓</span>` : ''}</td>
          <td><span class="badge ${d.status === 'active' ? 'badge-green' : d.status === 'spare' ? 'badge-yellow' : 'badge-grey'}">${esc(d.status_label)}</span>${d.ticket_count ? ` <span class="badge badge-red" title="Linked tickets">🎫 ${d.ticket_count}</span>` : ''}</td>
          <td class="actions"><button class="btn btn-sm" data-edit="${d.id}">Edit</button></td>
        </tr>`).join('')}`).join('')}
    </tbody></table></div>`;
  body.querySelectorAll('tr.clickable').forEach(tr => { tr.onclick = (e) => { if (e.target.closest('button')) return; openDeviceDetail({ deviceId: Number(tr.dataset.id), clinic, onChanged: load }); }; });
  body.querySelectorAll('[data-edit]').forEach(b => { b.onclick = () => { const d = list.find(x => x.id === Number(b.dataset.edit)); openDeviceForm({ clinic, device: d, onSaved: load }); }; });
  body.querySelectorAll('[data-add-type]').forEach(b => { b.onclick = () => openDeviceForm({ clinic, initial: { device_type: b.dataset.addType }, onSaved: load }); });
}

// ---- Topology ---------------------------------------------------------------------

const NODE_W = 172, NODE_H = 56, GAP_X = 18, GAP_Y = 46;

async function renderTopology(body) {
  const topo = await devices.topology(clinic.id);
  const byId = Object.fromEntries(topo.nodes.map(n => [n.id, n]));
  if (!topo.nodes.length) { body.innerHTML = '<div class="card empty">Nothing to draw yet. Add a firewall or router first, then plug other devices into it via “Uplink device”.</div>'; return; }

  // Roots that are network gear hang off a virtual WAN node; everything else is "standalone".
  const netRoots = topo.roots.filter(id => byId[id].is_network);
  const otherRoots = topo.roots.filter(id => !byId[id].is_network);

  // Layout: leaf-count based x positions, depth based y.
  const widths = {};
  const leafWidth = (id) => {
    const n = byId[id];
    if (!n.children.length) { widths[id] = NODE_W + GAP_X; return widths[id]; }
    widths[id] = Math.max(NODE_W + GAP_X, n.children.reduce((s, c) => s + leafWidth(c), 0));
    return widths[id];
  };
  const pos = {};
  const place = (id, x0, depth) => {
    const n = byId[id];
    const w = widths[id];
    pos[id] = { x: x0 + w / 2 - NODE_W / 2, y: depth * (NODE_H + GAP_Y) };
    let cx = x0;
    for (const c of n.children) { place(c, cx, depth + 1); cx += widths[c]; }
  };
  let x = 0;
  const wanDepth = netRoots.length ? 1 : 0;
  netRoots.forEach(id => { leafWidth(id); place(id, x, wanDepth); x += widths[id]; });
  const mainWidth = Math.max(x, NODE_W + GAP_X);
  const mainDepth = Math.max(0, ...Object.values(pos).map(p => p.y)) + NODE_H;
  // Standalone section below
  let y2 = mainDepth + (Object.keys(pos).length ? 70 : 20);
  let x2 = 0;
  const sectionY = y2;
  if (otherRoots.length) y2 += 26;
  const standaloneDepthStart = y2;
  otherRoots.forEach(id => { leafWidth(id); place(id, x2, 0); x2 += widths[id]; });
  // shift standalone roots' subtree down
  const shift = (id, dy) => { pos[id].y += dy; byId[id].children.forEach(c => shift(c, dy)); };
  otherRoots.forEach(id => shift(id, standaloneDepthStart));
  const W = Math.max(mainWidth, x2) + 40;
  const H = Math.max(...Object.values(pos).map(p => p.y)) + NODE_H + 30;
  const ox = 20, oy = 20;

  let svg = '';
  // WAN node
  if (netRoots.length) {
    const wx = mainWidth / 2 - 70;
    svg += `<g class="topo-wan" transform="translate(${ox + wx},${oy})"><rect width="140" height="30"/><text x="70" y="19" text-anchor="middle">🌐 Internet / WAN</text></g>`;
    for (const id of netRoots) svg += edge({ x: wx + 70, y: 30 }, { x: pos[id].x + NODE_W / 2, y: pos[id].y }, 'ethernet');
  }
  if (otherRoots.length) svg += `<text class="topo-section" x="${ox}" y="${oy + sectionY + 12}">Not connected to the network (no uplink set)</text>`;
  for (const e of topo.edges) {
    if (!pos[e.from] || !pos[e.to]) continue;
    svg += edge({ x: pos[e.from].x + NODE_W / 2, y: pos[e.from].y + NODE_H }, { x: pos[e.to].x + NODE_W / 2, y: pos[e.to].y }, e.link_type);
  }
  for (const n of topo.nodes) {
    const p = pos[n.id];
    if (!p) continue;
    const sub = deviceSubtitle(n);
    const trunc = (s, n) => (s && s.length > n ? s.slice(0, n - 1) + '…' : s || '');
    svg += `<g class="topo-node ${n.status === 'retired' ? 'retired' : ''}" data-id="${n.id}" transform="translate(${ox + p.x},${oy + p.y})">
      <title>${attr(n.name)}${sub ? ' · ' + attr(sub) : ''}${n.uplink_id ? ` · ${n.link_type === 'wireless' ? 'wireless' : 'wired'} to ${attr(byId[n.uplink_id] ? byId[n.uplink_id].name : '')}` : ''}</title>
      <rect class="box" width="${NODE_W}" height="${NODE_H}"/>
      <rect class="accent ${accentClass(n.device_type, meta)}" x="0" y="8" width="4" height="${NODE_H - 16}"/>
      <text class="icon" x="14" y="36">${esc(n.icon)}</text>
      <text x="44" y="22" font-weight="600">${esc(trunc(n.name, 17))}</text>
      <text class="sub" x="44" y="40">${esc(trunc(sub, 21))}</text>
      ${n.ticket_count ? `<text class="badge" x="${NODE_W - 8}" y="14" text-anchor="end">🎫${n.ticket_count}</text>` : ''}
      ${n.uplink_id && n.link_type === 'wireless' ? `<text class="badge" x="${NODE_W - 8}" y="${NODE_H - 8}" text-anchor="end">📶</text>` : ''}
    </g>`;
  }
  body.innerHTML = `
    <div class="topo-wrap" id="topo-wrap">
      <div class="topo-tools"><button class="btn btn-sm" id="zoom-out">−</button><button class="btn btn-sm" id="zoom-reset">${Math.round(state.zoom * 100)}%</button><button class="btn btn-sm" id="zoom-in">+</button></div>
      <svg class="topo-svg" viewBox="0 0 ${W + ox} ${H + oy}" width="${(W + ox) * state.zoom}" height="${(H + oy) * state.zoom}" xmlns="http://www.w3.org/2000/svg">${svg}</svg>
    </div>
    <div class="topo-legend">
      <span><span class="line"></span>Wired</span><span><span class="line wireless"></span>Wireless</span>
      <span>Left stripe: <span style="color:var(--c-interested)">■</span> network · <span style="color:#7c5cd6">■</span> server · <span style="color:var(--c-client)">■</span> workstation/laptop · <span style="color:#eda100">■</span> phone/mobile · <span style="color:#8a8f98">■</span> printer</span>
      <span>Click a device for details. Dashed box = retired.</span>
    </div>`;
  body.querySelectorAll('.topo-node').forEach(g => { g.onclick = () => openDeviceDetail({ deviceId: Number(g.dataset.id), clinic, onChanged: load }); });
  const setZoom = (z) => { state.zoom = Math.min(2, Math.max(0.4, z)); load(); };
  body.querySelector('#zoom-in').onclick = () => setZoom(state.zoom + 0.2);
  body.querySelector('#zoom-out').onclick = () => setZoom(state.zoom - 0.2);
  body.querySelector('#zoom-reset').onclick = () => setZoom(1);
}

function edge(a, b, type) {
  const my = (a.y + b.y) / 2;
  return `<path class="topo-edge ${type === 'wireless' ? 'wireless' : ''}" d="M${a.x + 20},${a.y + 20} V${my + 20} H${b.x + 20} V${b.y + 20}"/>`;
}
