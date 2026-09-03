// Equipment page for one clinic: list view and network topology view.
import { clinics, devices } from '../api.js';
import { esc, attr, options, debounce, setTitle, shorthandBadge, dot, toast, confirmDialog } from '../ui.js';
import { openDeviceForm, openDeviceDetail, openServiceDetail, accentClass, deviceSubtitle, plural } from '../equipment.js';

let state = { view: 'list', q: '', type: '', status: '', zoom: 1, edit: false, source: null, rack: null };
let rackDragEndAt = 0;  // suppress the click that browsers fire right after a drag
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
          <td>${esc([d.designation, [d.manufacturer, d.model].filter(Boolean).join(' ')].filter(Boolean).join(' · '))}${(d.device_type === 'server' || d.is_vm) && d.services.length ? `<div class="muted small">🧩 ${esc(d.services.slice(0, 4).map(s => s.name).join(', '))}${d.services.length > 4 ? '…' : ''}</div>` : ''}${d.os ? `<div class="muted small">${esc(d.os)}</div>` : ''}</td>
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

// Whether a node shows its running services inline (leaf server/VM nodes only, to avoid
// colliding with children drawn directly below a node).
function hasInlineServices(n) {
  return (n.device_type === 'server' || n.is_vm) && n.services && n.services.length && !n.children.length;
}
function svcLineCount(n) {
  if (!hasInlineServices(n)) return 0;
  return Math.min(2, n.services.length) + (n.services.length > 2 ? 1 : 0);
}
// Compact, clickable service names rendered just below a leaf server/VM node.
function svcLines(n, h, trunc) {
  if (!hasInlineServices(n)) return '';
  const shown = n.services.slice(0, 2);
  let out = shown.map((s, i) =>
    `<text class="topo-svc" data-svc="${s.id}" x="6" y="${h + 13 + i * 13}">🧩 ${esc(trunc(s.name, 22))}</text>`
  ).join('');
  if (n.services.length > 2) out += `<text class="topo-svc-more" x="6" y="${h + 13 + 2 * 13}">+${n.services.length - 2} more</text>`;
  return out;
}

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
  const nodeBottom = (n) => { const p = pos[n.id]; if (!p) return 0; const lines = svcLineCount(n); return p.y + NODE_H + (lines ? lines * 13 + 8 : 0); };
  const H = Math.max(0, ...[...topo.nodes, ...offsite].map(nodeBottom)) + 30;
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
      ${(n.services && n.services.length) ? `<text class="badge" x="${w - 8}" y="${h - 8}" text-anchor="end">🧩${n.services.length}</text>` : (n.uplink_id && n.link_type === 'wireless' ? `<text class="badge" x="${w - 8}" y="${h - 8}" text-anchor="end">📶</text>` : '')}
      ${svcLines(n, h, trunc)}
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
      <span>Left stripe: <span style="color:var(--c-interested)">■</span> network · <span style="color:#7c5cd6">■</span> server/VM · <span style="color:var(--c-client)">■</span> workstation/laptop · <span style="color:#eda100">■</span> phone · <span style="color:#8a8f98">■</span> printer · <span style="color:#d9342b">■</span> security</span>
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
  body.querySelectorAll('.topo-svc').forEach(t => {
    t.onclick = (e) => {
      e.stopPropagation();
      if (state.edit) return;
      openServiceDetail({ clinic, serviceId: Number(t.dataset.svc), onChanged: () => renderTopology(body) });
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
  if (!state.rack || !data.racks.find(r => r.name === state.rack)) state.rack = data.racks[0].name;
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
  main.querySelectorAll('.ru-device').forEach(g => { g.onclick = () => { if (Date.now() - rackDragEndAt < 350) return; openDeviceDetail({ deviceId: Number(g.dataset.id), clinic, onChanged: load }); }; });
  main.querySelectorAll('[data-id2]').forEach(b => { b.onclick = () => openDeviceDetail({ deviceId: Number(b.dataset.id2), clinic, onChanged: load }); });
  main.querySelectorAll('.ru-empty').forEach(g => { g.onclick = () => { if (Date.now() - rackDragEndAt < 350) return; openDeviceForm({ clinic, initial: { device_type: 'server', rack: selected.name, rack_room: selected.room || '', rack_position: Number(g.dataset.u) }, onSaved: () => renderRacks(body) }); }; });
  // shelf items open their own detail and shouldn't start a shelf drag
  main.querySelectorAll('.shelf-item[data-id]').forEach(g => {
    g.addEventListener('pointerdown', (e) => e.stopPropagation());
    g.addEventListener('click', (e) => { e.stopPropagation(); if (Date.now() - rackDragEndAt < 350) return; openDeviceDetail({ deviceId: Number(g.dataset.id), clinic, onChanged: load }); });
  });
  // hover a device (or its shelf) to highlight just its cables and chips
  const svg = main.querySelector('.rack-svg');
  const setHot = (id) => {
    if (!svg) return;
    svg.classList.toggle('has-hot', id != null);
    svg.querySelectorAll('[data-dev]').forEach(el => {
      const on = id != null && (el.dataset.dev === String(id) || el.dataset.dev2 === String(id));
      el.classList.toggle('hot', on);
    });
  };
  main.querySelectorAll('.ru-device[data-id]').forEach(g => {
    g.addEventListener('mouseenter', () => setHot(g.dataset.id));
    g.addEventListener('mouseleave', () => setHot(null));
  });
  wireRackDrag(main, selected, body);
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
  if (dt.security) return 'fill-security';
  if (t === 'printer') return 'fill-printer';
  return 'fill-other';
}

function rackElevation(r) {
  const U = r.units;
  const UH = 28;
  const leftRailW = 200, uNumW = 26, rackW = 260, rightRailW = 220;
  const rackX = leftRailW + uNumW, rackY = 22;
  const W = rackX + rackW + rightRailW + 20;
  const H = rackY + U * UH + 30;
  const uToY = (u) => rackY + (U - u) * UH;

  // rack frame + U numbers
  let frame = `<rect x="${rackX}" y="${rackY}" width="${rackW}" height="${U * UH}" rx="4" class="rack-frame"/>`;
  for (let u = 1; u <= U; u++) {
    const y = uToY(u);
    frame += `<line x1="${rackX}" x2="${rackX + rackW}" y1="${y}" y2="${y}" class="rack-uline"/>`;
    frame += `<text x="${rackX - 6}" y="${y + UH - 9}" text-anchor="end" class="rack-unum">${u}</text>`;
  }

  const occupied = new Set();
  for (const d of r.devices) { if (!d.position) continue; for (let u = d.position; u < d.position + (d.units || 1); u++) occupied.add(u); }
  let empties = '';
  for (let u = 1; u <= U; u++) {
    if (occupied.has(u)) continue;
    const y = uToY(u);
    empties += `<g class="ru-empty" data-u="${u}"><rect x="${rackX + 2}" y="${y + 1.5}" width="${rackW - 4}" height="${UH - 3}" rx="3"/><text x="${rackX + rackW / 2}" y="${y + UH / 2 + 4}" text-anchor="middle" class="ru-empty-label">+ add at U${u}</text></g>`;
  }

  // mounted devices
  const anchorOf = {};
  let devSvg = '';
  for (const d of r.devices) {
    const pos = d.position, h = d.units || 1;
    if (!pos) continue;
    const top = uToY(pos + h - 1), height = h * UH - 3, cy = top + height / 2;
    anchorOf[d.id] = { leftX: rackX, rightX: rackX + rackW, y: cy };
    const isShelf = d.device_type === 'shelf';
    const sub = [d.designation, d.ip_address].filter(Boolean).join(' · ');
    let inner = `
      <rect width="${rackW - 4}" height="${height}" rx="3" class="ru-box ${accentFill(d.device_type)} ${isShelf ? 'is-shelf' : ''}"/>
      <rect width="4" height="${height}" class="ru-accent ${accentFill(d.device_type)}"/>
      <text x="12" y="${Math.min(18, height / 2 + 5)}" class="ru-icon">${esc(d.icon)}</text>
      <text x="30" y="${h === 1 ? 16 : 16}" class="ru-name">${esc(trunc(d.name, 22))}</text>
      ${h > 1 && sub && !isShelf ? `<text x="30" y="32" class="ru-sub">${esc(trunc(sub, 30))}</text>` : ''}
      <text x="${rackW - 10}" y="15" text-anchor="end" class="ru-u">${h}U</text>
      ${d.ticket_count ? `<text x="${rackW - 10}" y="${height - 7}" text-anchor="end" class="ru-badge">🎫${d.ticket_count}</text>` : ''}`;
    // shelf items sitting on the tray: small chips laid across, wrapping
    if (isShelf) {
      const items = d.shelf_items || [];
      const padX = 8, chipH = 20, gap = 5, availW = rackW - 4 - padX * 2;
      let cxp = padX, cyp = 22;
      for (const it of items) {
        const label = `${it.icon} ${trunc(it.name, 12)}`;
        const cw = Math.min(availW, 30 + label.length * 6.2);
        if (cxp + cw > rackW - 4 - padX && cxp > padX) { cxp = padX; cyp += chipH + gap; }
        anchorOf['item-' + it.id] = { leftX: rackX, rightX: rackX + rackW, y: top + 1.5 + cyp + chipH / 2 };
        inner += `<g class="shelf-item" data-id="${it.id}" transform="translate(${cxp},${cyp})"><rect width="${cw}" height="${chipH}" rx="4" class="${accentFill(it.device_type)}"/><text x="6" y="14">${esc(label)}</text></g>`;
        cxp += cw + gap;
      }
      if (!items.length) inner += `<text x="30" y="${height - 8}" class="ru-sub">empty shelf — add devices onto it</text>`;
    }
    devSvg += `<g class="ru-device ${d.status === 'retired' ? 'retired' : ''} ${isShelf ? 'shelf' : ''}" data-id="${d.id}" data-pos="${pos}" data-h="${h}" transform="translate(${rackX + 2},${top + 1.5})">${inner}</g>`;
  }

  // map shelf-item ids to their shelf's anchor for link routing
  const memberAnchor = (id) => anchorOf[id] || null;

  // Build cables + chips. Upstream (direction 'up') -> LEFT rail; downstream ('down') -> RIGHT rail.
  const linkColor = (lt) => lt === 'wireless' ? 'wireless' : lt === 'virtual' ? 'virtual' : '';
  const leftChips = [], rightChips = [];
  const internal = [];
  for (const l of r.links) {
    if (l.in_rack) { internal.push(l); continue; }
    const anc = memberAnchor(l.member_id);
    if (!anc || !l.ext) continue;
    (l.direction === 'up' ? leftChips : rightChips).push({ y: anc.y, member: l.member_id, ext: l.ext, lt: l.link_type });
  }

  // place chips without overlap, near their anchor Y, and draw a smooth curve to the anchor edge
  const CHIP_H = 22, CHIP_GAP = 6, CHIP_W = 150;
  function layoutChips(list, side) {
    list.sort((a, b) => a.y - b.y);
    let lastY = -1e9;
    let cables = '', chips = '';
    for (const ch of list) {
      const cy = Math.max(ch.y, lastY + CHIP_H + CHIP_GAP);
      lastY = cy;
      const anc = memberAnchor(ch.member);
      const chipX = side === 'left' ? rackX - uNumW - CHIP_W - 10 : rackX + rackW + 30;
      const startX = side === 'left' ? anc.leftX : anc.rightX;
      const endX = side === 'left' ? chipX + CHIP_W : chipX;
      const c1 = side === 'left' ? startX - 40 : startX + 40;
      const c2 = side === 'left' ? endX + 40 : endX - 40;
      cables += `<path class="rack-cable ${linkColor(ch.lt)}" data-dev="${ch.member}" d="M${startX},${ch.y} C${c1},${ch.y} ${c2},${cy} ${endX},${cy}"/>`;
      chips += `<g class="rack-chip" data-dev="${ch.member}" transform="translate(${chipX},${cy - CHIP_H / 2})"><rect width="${CHIP_W}" height="${CHIP_H}" rx="6"/><text x="8" y="15">${esc(ch.ext.icon || '')} ${esc(trunc(ch.ext.name || '', 15))}${ch.ext.rack ? ` ·${esc(trunc(ch.ext.rack, 7))}` : ''}</text></g>`;
    }
    return cables + chips;
  }
  const leftSvg = layoutChips(leftChips, 'left');
  const rightSvg = layoutChips(rightChips, 'right');

  // in-rack peer links: a compact cable in a thin gutter just inside the right edge
  let internalSvg = '';
  let lane = 0;
  for (const l of internal) {
    const a = memberAnchor(l.member_id), b = memberAnchor(l.other_member_id);
    if (!a || !b) continue;
    const gx = rackX + rackW + 6 + (lane % 4) * 5; lane++;
    internalSvg += `<path class="rack-cable internal ${linkColor(l.link_type)}" data-dev="${l.member_id}" data-dev2="${l.other_member_id}" d="M${a.rightX},${a.y} C${gx},${a.y} ${gx},${b.y} ${b.rightX},${b.y}"/>`;
  }

  const legend = `<div class="rack-legend">
    <span><span class="sw fill-network"></span>Network</span><span><span class="sw fill-server"></span>Server</span><span><span class="sw fill-printer"></span>Printer</span><span><span class="sw fill-security"></span>Security</span>
    <span><span class="cable"></span>Wired</span><span><span class="cable wireless"></span>Wireless</span><span><span class="cable virtual"></span>Virtual</span>
    <span class="muted">◀ Upstream (uplinks) · Downstream ▶. Hover a device to highlight its links. Drag to move; click for details.</span></div>`;

  const noPos = r.devices.filter(d => !d.position);
  return `<div class="card">
    <div class="card-header"><h3>🗄 ${esc(r.name)}</h3><span class="muted small">${esc(r.room || '')} · ${r.device_count} device${r.device_count === 1 ? '' : 's'} · ${U}U</span>
      <div class="actions"><a class="btn btn-sm" href="#/clinics/${clinic.id}/equipment?view=topology">Topology</a></div></div>
    <div class="rack-scroll"><svg class="rack-svg" data-uh="${UH}" data-racky="${rackY}" data-rackx="${rackX}" data-rackw="${rackW}" data-u="${U}" data-h="${H}" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">
      ${leftSvg}${rightSvg}${internalSvg}${frame}${empties}${devSvg}
    </svg></div>
    ${noPos.length ? `<div class="mt small muted">In this rack without a U# set: ${noPos.map(d => `<button class="btn btn-link btn-sm" data-id2="${d.id}">${esc(d.icon)} ${esc(d.name)}</button>`).join(' ')} — edit each to set its position.</div>` : ''}
    ${legend}
  </div>`;
}


// Drag a rack device to another empty position. Clean, snap-to-U, overlap-aware.
function wireRackDrag(main, rack, body) {
  const svg = main.querySelector('.rack-svg');
  if (!svg) return;
  const UH = +svg.dataset.uh, rackY = +svg.dataset.racky, U = +svg.dataset.u, Hsvg = +svg.dataset.h;
  const rackX = +svg.dataset.rackx, rackW = +svg.dataset.rackw;
  // occupied ranges per device (for overlap tests)
  const items = rack.devices.filter(d => d.position).map(d => ({ id: d.id, pos: d.position, h: d.units || 1 }));
  const occupiedBy = (u, exceptId) => items.some(it => it.id !== exceptId && u >= it.pos && u < it.pos + it.h);
  const topEdgeY = (pos, h) => rackY + (U - (pos + h - 1)) * UH;

  svg.querySelectorAll('.ru-device[data-pos]').forEach(g => {
    if (g.dataset.pos === 'null' || g.dataset.pos === '') return;
    g.classList.add('draggable');
    let drag = null, ghost = null;
    g.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      const id = Number(g.dataset.id), h = Number(g.dataset.h), pos = Number(g.dataset.pos);
      const rect = svg.getBoundingClientRect();
      const scale = rect.height / Hsvg;
      const svgY = (e.clientY - rect.top) / scale;
      const uUnder = Math.min(U, Math.max(1, U - Math.floor((svgY - rackY) / UH)));
      drag = { id, h, pos, grabOffset: uUnder - pos, scale, rect, target: pos, moved: false };
      ghost = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      ghost.setAttribute('class', 'ru-ghost');
      ghost.setAttribute('x', rackX + 2); ghost.setAttribute('width', rackW - 4);
      ghost.setAttribute('height', h * UH - 3); ghost.setAttribute('rx', 3);
      ghost.setAttribute('y', topEdgeY(pos, h) + 1.5);
      svg.appendChild(ghost);
      g.classList.add('dragging');
      g.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    g.addEventListener('pointermove', (e) => {
      if (!drag) return;
      const svgY = (e.clientY - drag.rect.top) / drag.scale;
      const uUnder = Math.min(U, Math.max(1, U - Math.floor((svgY - rackY) / UH)));
      let target = uUnder - drag.grabOffset;
      target = Math.min(U - drag.h + 1, Math.max(1, target));
      drag.target = target;
      drag.moved = drag.moved || target !== drag.pos;
      const ok = !rangeOverlaps(target, drag.h, drag.id, occupiedBy);
      ghost.setAttribute('y', topEdgeY(target, drag.h) + 1.5);
      ghost.classList.toggle('invalid', !ok);
      g.setAttribute('transform', `translate(${rackX + 2},${topEdgeY(target, drag.h) + 1.5})`);
    });
    const finish = async (e) => {
      if (!drag) return;
      const { id, h, pos, target } = drag;
      if (ghost) ghost.remove();
      g.classList.remove('dragging');
      try { g.releasePointerCapture(e.pointerId); } catch { /* ignore */ }
      const moved = target !== pos;
      drag = null; ghost = null;
      if (!moved) return;  // a plain click: let the click handler open the device
      rackDragEndAt = Date.now();  // swallow the click the browser fires after this drag
      if (rangeOverlaps(target, h, id, occupiedBy)) { toast('That spot is occupied', 'error'); renderRacks(body); return; }
      try {
        const full = await devices.get(id);
        await devices.update(id, { ...deviceUpdatePayload(full), rack_position: target });
        toast(`Moved to U${target}`, 'success');
      } catch (err) { toast(err.message, 'error'); }
      renderRacks(body);
    };
    g.addEventListener('pointerup', finish);
    g.addEventListener('pointercancel', finish);
  });
}

function rangeOverlaps(pos, h, id, occupiedBy) {
  for (let u = pos; u < pos + h; u++) if (occupiedBy(u, id)) return true;
  return false;
}

// Build a full DeviceIn payload from a fetched device (so PUT keeps every field).
function deviceUpdatePayload(d) {
  return {
    device_type: d.device_type, name: d.name, location_id: d.location_id, designation: d.designation,
    manufacturer: d.manufacturer, model: d.model, serial: d.serial, ip_address: d.ip_address, mac_address: d.mac_address,
    os: d.os, user_name: d.user_name, uplink_id: d.uplink_id, link_type: d.device_type === 'vm' ? 'virtual' : d.link_type,
    status: d.status, off_site: d.off_site, rack: d.rack, rack_room: d.rack_room, rack_position: d.rack_position,
    rack_units: d.rack_units, services: d.services, purchase_date: d.purchase_date, warranty_until: d.warranty_until, notes: d.notes,
  };
}

function trunc(str, m) { return str && str.length > m ? str.slice(0, m - 1) + '…' : (str || ''); }


function edge(a, b, type, e) {
  const my = (a.y + b.y) / 2;
  const cls = ['topo-edge', type === 'wireless' ? 'wireless' : '', type === 'virtual' ? 'virtual' : '', e && e.primary === false ? 'extra' : ''].join(' ');
  const d = `M${a.x},${a.y} C${a.x},${my} ${b.x},${my} ${b.x},${b.y}`;
  const hit = (e && e.from != null && e.to != null) ? `<path class="topo-edge-hit" data-from="${e.from}" data-to="${e.to}" d="${d}"/>` : '';
  return `<path class="${cls}" d="${d}"/>${hit}`;
}
