// Equipment page for one clinic: list view and network topology view.
import { clinics, devices } from '../api.js';
import { esc, attr, options, debounce, setTitle, shorthandBadge, dot, toast, confirmDialog } from '../ui.js';
import { openDeviceForm, openDeviceDetail, accentClass, deviceSubtitle, plural } from '../equipment.js';

let state = { view: 'list', q: '', type: '', status: '', zoom: 1, edit: false, source: null, rack: null };
let clinic = null, meta = null;

export async function render(container, params, routeParams) {
  const id = Number(routeParams.id);
  try { clinic = await clinics.get(id); } catch { container.innerHTML = '<div class="card empty">Clinic not found.</div>'; return; }
  meta = await devices.meta();
  setTitle(`Equipment · ${clinic.shorthand || clinic.name}`);
  container.classList.add('wide');
  if (params.get('view')) state.view = params.get('view');
  if (params.get('type')) state.type = params.get('type');
  if (params.get('rack')) { state.view = 'racks'; state.rack = params.get('rack'); }

  container.innerHTML = `
    <div class="mb"><a href="#/clinics/${clinic.id}">← ${esc(clinic.name)}</a></div>
    <div class="page-header">
      <h1>${shorthandBadge(clinic)} Equipment</h1>
      <span class="muted" id="equip-count"></span>
      <div class="actions">
        <div class="seg" style="display:inline-flex;border:1px solid var(--border);border-radius:7px;overflow:hidden">
          <button class="btn ${state.view === 'list' ? 'active' : ''}" data-view="list" style="border:none;border-radius:0">☰ List</button>
          <button class="btn ${state.view === 'topology' ? 'active' : ''}" data-view="topology" style="border:none;border-radius:0;border-left:1px solid var(--border)">🕸 Topology</button>
          <button class="btn ${state.view === 'racks' ? 'active' : ''}" data-view="racks" style="border:none;border-radius:0;border-left:1px solid var(--border)">🗄 Racks</button>
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
  else if (state.view === 'racks') await renderRacks(body);
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
          <td class="name">${d.is_vm ? '🧊 ' : ''}${esc(d.name)}${d.off_site ? ' <span class="badge badge-purple">off-site</span>' : ''}${d.location_name ? ` <span class="muted small">· ${esc(d.location_name)}</span>` : ''}</td>
          <td>${esc([d.designation, [d.manufacturer, d.model].filter(Boolean).join(' ')].filter(Boolean).join(' · '))}${d.device_type === 'server' && d.services.length ? `<div class="muted small">${esc(d.services.slice(0, 4).join(', '))}${d.services.length > 4 ? '…' : ''}</div>` : ''}${d.os ? `<div class="muted small">${esc(d.os)}</div>` : ''}</td>
          <td>${esc(d.user_name || '')}</td>
          <td class="mono">${esc(d.ip_address || '')}</td>
          <td>${d.uplink_name ? `<span class="link-icon" title="${d.link_label || ''}">${d.is_vm ? '🧊' : (d.link_type === 'wireless' ? '📶' : '🔌')}</span> ${esc(d.uplink_icon || '')} ${esc(d.uplink_name)}` : '<span class="muted">—</span>'}${d.downlink_count ? ` <span class="badge" title="Devices plugged into this">${d.downlink_count} ↓</span>` : ''}</td>
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

function nodeDim(n) { return n.is_vm ? { w: 132, h: 42 } : { w: NODE_W, h: NODE_H }; }

async function renderTopology(body) {
  const topo = await devices.topology(clinic.id);
  const byId = Object.fromEntries([...topo.nodes, ...(topo.offsite || [])].map(n => [n.id, n]));
  if (!topo.nodes.length && !(topo.offsite || []).length) { body.innerHTML = '<div class="card empty">Nothing to draw yet. Add a firewall or router first, then plug other devices into it via “Uplink device”.</div>'; return; }

  const netRoots = topo.roots.filter(id => byId[id].is_network);
  const otherRoots = topo.roots.filter(id => !byId[id].is_network);

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
  let y2 = mainDepth + (Object.keys(pos).length ? 70 : 20);
  let x2 = 0;
  const sectionY = y2;
  if (otherRoots.length) y2 += 26;
  const standaloneDepthStart = y2;
  otherRoots.forEach(id => { leafWidth(id); place(id, x2, 0); x2 += widths[id]; });
  const shift = (id, dy) => { pos[id].y += dy; byId[id].children.forEach(c => shift(c, dy)); };
  otherRoots.forEach(id => shift(id, standaloneDepthStart));

  // Off-site devices: a simple wrapped grid in its own band.
  const offsite = topo.offsite || [];
  const offY = Math.max(...Object.values(pos).map(p => p.y), 0) + NODE_H + (offsite.length ? 80 : 0);
  const perRow = Math.max(1, Math.floor((Math.max(mainWidth, x2) || (NODE_W + GAP_X)) / (NODE_W + GAP_X)));
  offsite.forEach((n, i) => { pos[n.id] = { x: (i % perRow) * (NODE_W + GAP_X), y: offY + 26 + Math.floor(i / perRow) * (NODE_H + GAP_Y) }; });

  const W = Math.max(mainWidth, x2, offsite.length ? perRow * (NODE_W + GAP_X) : 0) + 40;
  const H = Math.max(...Object.values(pos).map(p => p.y), 0) + NODE_H + 30;
  const ox = 20, oy = 20;
  const cx = (id) => ox + pos[id].x + NODE_W / 2;
  const boxTop = (id) => oy + pos[id].y + (NODE_H - nodeDim(byId[id]).h) / 2;
  const boxBot = (id) => boxTop(id) + nodeDim(byId[id]).h;

  let svg = '';
  if (netRoots.length) {
    const wx = mainWidth / 2 - 70;
    svg += `<g class="topo-wan" transform="translate(${ox + wx},${oy})"><rect width="140" height="30"/><text x="70" y="19" text-anchor="middle">🌐 Internet / WAN</text></g>`;
    for (const id of netRoots) svg += edge({ x: wx + 70 + ox, y: oy + 30 }, { x: cx(id), y: boxTop(id) }, 'ethernet', {});
  }
  if (otherRoots.length) svg += `<text class="topo-section" x="${ox}" y="${oy + sectionY + 12}">Not connected to the network (no uplink set)</text>`;
  if (offsite.length) svg += `<text class="topo-section" x="${ox}" y="${oy + offY + 14}">📍 Off-site devices</text>`;
  // edges (primary tree + extra overlay)
  for (const e of topo.edges) {
    if (!pos[e.from] || !pos[e.to]) continue;
    svg += edge({ x: cx(e.from), y: boxBot(e.from) }, { x: cx(e.to), y: boxTop(e.to) }, e.link_type, e);
  }
  for (const n of [...topo.nodes, ...offsite]) {
    const p = pos[n.id];
    if (!p) continue;
    const { w, h } = nodeDim(n);
    const bx = ox + p.x + (NODE_W - w) / 2, by = oy + p.y + (NODE_H - h) / 2;
    const sub = deviceSubtitle(n);
    const trunc = (str, m) => (str && str.length > m ? str.slice(0, m - 1) + '…' : str || '');
    const isVm = n.is_vm;
    const cls = [`topo-node`, n.status === 'retired' ? 'retired' : '', isVm ? 'is-vm' : '', state.source === n.id ? 'selected' : ''].join(' ');
    svg += `<g class="${cls}" data-id="${n.id}" transform="translate(${bx},${by})">
      <title>${attr(n.name)}${sub ? ' · ' + attr(sub) : ''}${n.uplink_id && byId[n.uplink_id] ? ` · ${isVm ? 'virtual, on' : (n.link_type === 'wireless' ? 'wireless to' : 'wired to')} ${attr(byId[n.uplink_id].name)}` : ''}</title>
      <rect class="box" width="${w}" height="${h}" rx="9"/>
      <rect class="accent ${accentClass(n.device_type, meta)}" x="0" y="8" width="4" height="${h - 16}"/>
      <text class="icon" x="${isVm ? 12 : 14}" y="${isVm ? 27 : 36}" style="font-size:${isVm ? 14 : 18}px">${esc(n.icon)}</text>
      <text x="${isVm ? 34 : 44}" y="${isVm ? 18 : 22}" font-weight="600" style="font-size:${isVm ? 11 : 12}px">${esc(trunc(n.name, isVm ? 14 : 17))}</text>
      <text class="sub" x="${isVm ? 34 : 44}" y="${isVm ? 33 : 40}" style="font-size:${isVm ? 10 : 11}px">${esc(trunc(sub, isVm ? 16 : 21))}</text>
      ${n.ticket_count ? `<text class="badge" x="${w - 8}" y="14" text-anchor="end">🎫${n.ticket_count}</text>` : ''}
      ${n.uplink_id && n.link_type === 'wireless' ? `<text class="badge" x="${w - 8}" y="${h - 8}" text-anchor="end">📶</text>` : ''}
    </g>`;
  }
  body.innerHTML = `
    <div class="topo-wrap ${state.edit ? 'editing' : ''}" id="topo-wrap">
      <div class="topo-tools">
        <button class="btn btn-sm" id="zoom-out">−</button><button class="btn btn-sm" id="zoom-reset">${Math.round(state.zoom * 100)}%</button><button class="btn btn-sm" id="zoom-in">+</button>
        <button class="btn btn-sm ${state.edit ? 'active' : ''}" id="edit-conn" title="Draw or remove connections between devices">${state.edit ? '✓ Done editing' : '✎ Edit connections'}</button>
      </div>
      ${state.edit ? `<div class="topo-hint" id="topo-hint">${state.source ? `Now click the device that <strong>${esc(byId[state.source] ? byId[state.source].name : '')}</strong> connects up to (its uplink). Or click a line to remove it.` : 'Click a device, then its uplink, to connect them. Click a line to remove it. The primary uplink is kept unless you remove it.'}</div>` : ''}
      <svg class="topo-svg" viewBox="0 0 ${W + ox} ${H + oy}" width="${(W + ox) * state.zoom}" height="${(H + oy) * state.zoom}" xmlns="http://www.w3.org/2000/svg">${svg}</svg>
    </div>
    <div class="topo-legend">
      <span><span class="line"></span>Wired</span><span><span class="line wireless"></span>Wireless</span><span><span class="line virtual"></span>VM → host</span><span><span class="line extra"></span>Extra link</span>
      <span>Left stripe: <span style="color:var(--c-interested)">■</span> network · <span style="color:#7c5cd6">■</span> server/VM · <span style="color:var(--c-client)">■</span> workstation/laptop · <span style="color:#eda100">■</span> phone · <span style="color:#8a8f98">■</span> printer</span>
      <span>🧊 = smaller box is a VM. Click a device for details.</span>
    </div>`;
  body.querySelectorAll('.topo-node').forEach(g => {
    g.onclick = async () => {
      const id = Number(g.dataset.id);
      if (!state.edit) { openDeviceDetail({ deviceId: id, clinic, onChanged: load }); return; }
      if (state.source === null) { state.source = id; renderTopology(body); return; }
      if (state.source === id) { state.source = null; renderTopology(body); return; }
      try { const r = await devices.connect(clinic.id, { child_id: state.source, parent_id: id }); toast(r.mode === 'primary' ? 'Primary uplink set' : 'Extra connection added', 'success'); }
      catch (e) { toast(e.message, 'error'); }
      state.source = null; renderTopology(body);
    };
  });
  body.querySelectorAll('.topo-edge-hit').forEach(h => {
    h.onclick = async () => {
      if (!state.edit) return;
      const from = Number(h.dataset.from), to = Number(h.dataset.to);
      if (!(await confirmDialog(`Remove the connection ${byId[to] ? byId[to].name : ''} → ${byId[from] ? byId[from].name : ''}?`, { okLabel: 'Remove', danger: true }))) return;
      try { await devices.disconnect(clinic.id, { child_id: to, parent_id: from }); toast('Connection removed'); }
      catch (e) { toast(e.message, 'error'); }
      renderTopology(body);
    };
  });
  const setZoom = (z) => { state.zoom = Math.min(2, Math.max(0.4, z)); renderTopology(body); };
  body.querySelector('#zoom-in').onclick = () => setZoom(state.zoom + 0.2);
  body.querySelector('#zoom-out').onclick = () => setZoom(state.zoom - 0.2);
  body.querySelector('#zoom-reset').onclick = () => setZoom(1);
  body.querySelector('#edit-conn').onclick = () => { state.edit = !state.edit; state.source = null; renderTopology(body); };
}

// ---- Rack elevation ---------------------------------------------------------------

async function renderRacks(body) {
  const data = await devices.racks(clinic.id);
  if (!data.racks.length) {
    body.innerHTML = `<div class="card empty">No racks yet. Edit a rack-mountable device (server, switch, firewall, router, AP) and fill in its <strong>Room</strong>, <strong>Rack</strong> and <strong>U#</strong> to place it in a rack.
      ${data.unracked_infra && data.unracked_infra.length ? `<div class="mt small">Not yet racked: ${data.unracked_infra.map(d => `<button class="btn btn-link btn-sm" data-open="${d.id}">${esc(d.icon)} ${esc(d.name)}</button>`).join(' ')}</div>` : ''}</div>`;
    body.querySelectorAll('[data-open]').forEach(b => b.onclick = () => openDeviceDetail({ deviceId: Number(b.dataset.open), clinic, onChanged: load }));
    return;
  }
  // group racks by room
  const rooms = {};
  data.racks.forEach(r => { (rooms[r.room || 'Unspecified room'] ||= []).push(r); });
  const selected = data.racks.find(r => r.name === state.rack) || null;

  body.innerHTML = `<div class="rack-layout">
    <aside class="rack-picker">
      ${Object.entries(rooms).map(([room, racks]) => `
        <div class="rack-room-group"><h4>🚪 ${esc(room)}</h4>
          ${racks.map(r => `<button class="rack-pick ${selected && selected.name === r.name ? 'active' : ''}" data-rack="${attr(r.name)}">
            <span class="rack-pick-name">🗄 ${esc(r.name)}</span><span class="muted small">${r.device_count} device${r.device_count === 1 ? '' : 's'} · ${r.units}U</span></button>`).join('')}
        </div>`).join('')}
      ${data.unracked_infra && data.unracked_infra.length ? `<div class="rack-room-group"><h4 class="muted">Not racked</h4>${data.unracked_infra.map(d => `<button class="rack-pick" data-open="${d.id}"><span>${esc(d.icon)} ${esc(d.name)}</span></button>`).join('')}</div>` : ''}
    </aside>
    <div class="rack-main" id="rack-main"></div>
  </div>`;

  body.querySelectorAll('.rack-pick[data-rack]').forEach(b => { b.onclick = () => { state.rack = b.dataset.rack; renderRacks(body); }; });
  body.querySelectorAll('.rack-pick[data-open]').forEach(b => { b.onclick = () => openDeviceDetail({ deviceId: Number(b.dataset.open), clinic, onChanged: load }); });

  const main = body.querySelector('#rack-main');
  if (!selected) {
    main.innerHTML = `<div class="card"><p class="muted">Pick a rack on the left to see its elevation, or here are all racks:</p>
      <div class="rack-thumbs">${data.racks.map(r => `<button class="rack-thumb" data-rack="${attr(r.name)}">${rackThumb(r)}<div class="rack-thumb-label">${esc(r.name)}<span class="muted small">${esc(r.room || '')}</span></div></button>`).join('')}</div></div>`;
    main.querySelectorAll('[data-rack]').forEach(b => { b.onclick = () => { state.rack = b.dataset.rack; renderRacks(body); }; });
    return;
  }
  main.innerHTML = rackElevation(selected);
  main.querySelectorAll('.ru-device').forEach(g => { g.onclick = () => openDeviceDetail({ deviceId: Number(g.dataset.id), clinic, onChanged: load }); });
  main.querySelectorAll('[data-id2]').forEach(b => { b.onclick = () => openDeviceDetail({ deviceId: Number(b.dataset.id2), clinic, onChanged: load }); });
}

function rackThumb(r) {
  const U = r.units, uh = 6, W = 90, H = U * uh + 8;
  let slots = '';
  for (const d of r.devices) {
    const pos = d.position || 0; if (!pos) continue;
    const y = 4 + (U - (pos + (d.units || 1) - 1)) * uh;
    slots += `<rect x="6" y="${y}" width="${W - 12}" height="${(d.units || 1) * uh - 1}" rx="1" class="thumb-slot ${accentFill(d.device_type)}"/>`;
  }
  return `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"><rect x="1" y="1" width="${W - 2}" height="${H - 2}" rx="3" class="thumb-frame"/>${slots}</svg>`;
}

function accentFill(t) {
  const dt = (meta.types[t] || {});
  if (dt.network) return 'fill-network';
  if (t === 'server') return 'fill-server';
  if (t === 'vm') return 'fill-vm';
  if (t === 'printer') return 'fill-printer';
  return 'fill-other';
}

function rackElevation(r) {
  const U = r.units;
  const UH = 26;                 // px per rack unit
  const rackX = 54, rackY = 20, rackW = 260;
  const railW = 200;             // cable-routing rail on the right
  const W = rackX + rackW + railW + 24;
  const H = rackY + U * UH + 30;
  const uToY = (u) => rackY + (U - u) * UH;   // top edge y of unit u
  const byId = Object.fromEntries(r.devices.map(d => [d.id, d]));

  // rack frame + U numbers + empty slots
  let svg = `<rect x="${rackX}" y="${rackY}" width="${rackW}" height="${U * UH}" rx="4" class="rack-frame"/>`;
  for (let u = 1; u <= U; u++) {
    const y = uToY(u);
    svg += `<line x1="${rackX}" x2="${rackX + rackW}" y1="${y}" y2="${y}" class="rack-uline"/>`;
    svg += `<text x="${rackX - 8}" y="${y + UH - 8}" text-anchor="end" class="rack-unum">${u}</text>`;
  }

  // devices
  const anchorOf = {};
  for (const d of r.devices) {
    const pos = d.position;
    const h = d.units || 1;
    if (!pos) continue;
    const top = uToY(pos + h - 1);
    const height = h * UH - 3;
    const cy = top + height / 2;
    anchorOf[d.id] = { x: rackX + rackW, y: cy, top, height };
    const label = `${d.name}`;
    const sub = [d.designation, d.ip_address].filter(Boolean).join(' · ');
    svg += `<g class="ru-device ${d.status === 'retired' ? 'retired' : ''}" data-id="${d.id}" transform="translate(${rackX + 2},${top + 1.5})">
      <rect width="${rackW - 4}" height="${height}" rx="3" class="ru-box ${accentFill(d.device_type)}"/>
      <rect width="4" height="${height}" class="ru-accent ${accentFill(d.device_type)}"/>
      <text x="12" y="${Math.min(17, height / 2 + 4)}" class="ru-icon">${esc(d.icon)}</text>
      <text x="30" y="${h === 1 ? 15 : 16}" class="ru-name">${esc(trunc(label, 22))}</text>
      ${h > 1 && sub ? `<text x="30" y="31" class="ru-sub">${esc(trunc(sub, 30))}</text>` : ''}
      <text x="${rackW - 10}" y="14" text-anchor="end" class="ru-u">${h}U</text>
      ${d.ticket_count ? `<text x="${rackW - 10}" y="${height - 6}" text-anchor="end" class="ru-badge">🎫${d.ticket_count}</text>` : ''}
    </g>`;
  }
  // occupied-but-unpositioned devices (no U#) listed below
  const noPos = r.devices.filter(d => !d.position);

  // links: internal = curved cables on the rail; external = stub + labeled chip
  const railX = rackX + rackW;
  let lane = 0;
  const laneGap = 13;
  let chips = [];
  const linkSvg = [];
  // de-dup already handled server-side; draw
  for (const l of r.links) {
    const a = anchorOf[l.a] || anchorOf[l.b];
    const aId = anchorOf[l.a] ? l.a : (anchorOf[l.b] ? l.b : null);
    if (!a || aId === null) continue;
    const cls = `rack-cable ${l.link_type === 'wireless' ? 'wireless' : l.link_type === 'virtual' ? 'virtual' : ''}`;
    if (l.b_in_rack && anchorOf[l.a] && anchorOf[l.b]) {
      // both endpoints in this rack: route a cable out to a lane and back
      const p = anchorOf[l.a], q = anchorOf[l.b];
      const lx = railX + 14 + (lane % 8) * laneGap; lane++;
      linkSvg.push(`<path class="${cls}" d="M${p.x},${p.y} H${lx} V${q.y} H${q.x}"/>`);
    } else {
      // external endpoint: stub to a chip in the rail
      const other = anchorOf[l.a] ? l.b : l.a;
      void other;
      const yc = a.y;
      const lx = railX + 14 + (lane % 8) * laneGap; lane++;
      chips.push({ y: yc, name: l.b_name, icon: l.b_icon, rack: l.b_rack, lx, link_type: l.link_type });
    }
  }
  // place external chips avoiding overlap (simple vertical stack near their anchor)
  chips.sort((a, b) => a.y - b.y);
  let lastY = -100;
  for (const ch of chips) {
    let cy = Math.max(ch.y, lastY + 24);
    lastY = cy;
    const chipX = railX + 120, chipW = railW - 130;
    const cls = `rack-cable ${ch.link_type === 'wireless' ? 'wireless' : ch.link_type === 'virtual' ? 'virtual' : ''}`;
    linkSvg.push(`<path class="${cls}" d="M${railX},${ch.y} H${ch.lx} V${cy} H${chipX}"/>`);
    linkSvg.push(`<g class="rack-chip" transform="translate(${chipX},${cy - 11})"><rect width="${chipW}" height="22" rx="5"/><text x="8" y="15">${esc(ch.icon || '')} ${esc(trunc(ch.name || '', 16))}${ch.rack ? ` ·${esc(trunc(ch.rack, 8))}` : ''}</text></g>`);
  }
  svg += linkSvg.join('');

  const legend = `<div class="rack-legend">
    <span><span class="sw fill-network"></span>Network</span><span><span class="sw fill-server"></span>Server</span><span><span class="sw fill-printer"></span>Printer</span>
    <span><span class="cable"></span>Cable</span><span><span class="cable wireless"></span>Wireless</span><span><span class="cable virtual"></span>Virtual</span>
    <span class="muted">Chips on the right are linked devices outside this rack. Click a device for details.</span></div>`;

  return `<div class="card">
    <div class="card-header"><h3>🗄 ${esc(r.name)}</h3><span class="muted small">${esc(r.room || '')} · ${r.device_count} device${r.device_count === 1 ? '' : 's'} · ${U}U</span>
      <div class="actions"><a class="btn btn-sm" href="#/clinics/${clinic.id}/equipment?view=topology">Topology</a></div></div>
    <div class="rack-scroll"><svg class="rack-svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">${svg}</svg></div>
    ${noPos.length ? `<div class="mt small muted">In this rack without a U# set: ${noPos.map(d => `<button class="btn btn-link btn-sm" data-id2="${d.id}">${esc(d.icon)} ${esc(d.name)}</button>`).join(' ')} — edit each to set its position.</div>` : ''}
    ${legend}
  </div>`;
}

function trunc(str, m) { return str && str.length > m ? str.slice(0, m - 1) + '…' : (str || ''); }


function edge(a, b, type, e) {
  const my = (a.y + b.y) / 2;
  const cls = ['topo-edge', type === 'wireless' ? 'wireless' : '', type === 'virtual' ? 'virtual' : '', e && e.primary === false ? 'extra' : ''].join(' ');
  const d = `M${a.x},${a.y} C${a.x},${my} ${b.x},${my} ${b.x},${b.y}`;
  const hit = (e && e.from != null && e.to != null) ? `<path class="topo-edge-hit" data-from="${e.from}" data-to="${e.to}" d="${d}"/>` : '';
  return `<path class="${cls}" d="${d}"/>${hit}`;
}
