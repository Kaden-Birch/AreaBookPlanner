// Equipment page for one clinic: list view and network topology view.
import { clinics, devices } from '../api.js';
import { esc, attr, options, debounce, setTitle, shorthandBadge, dot, toast, confirmDialog } from '../ui.js';
import { openDeviceForm, openDeviceDetail, accentClass, deviceSubtitle, plural } from '../equipment.js';

let state = { view: 'list', q: '', type: '', status: '', zoom: 1, edit: false, source: null };
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

function edge(a, b, type, e) {
  const my = (a.y + b.y) / 2;
  const cls = ['topo-edge', type === 'wireless' ? 'wireless' : '', type === 'virtual' ? 'virtual' : '', e && e.primary === false ? 'extra' : ''].join(' ');
  const d = `M${a.x},${a.y} C${a.x},${my} ${b.x},${my} ${b.x},${b.y}`;
  const hit = (e && e.from != null && e.to != null) ? `<path class="topo-edge-hit" data-from="${e.from}" data-to="${e.to}" d="${d}"/>` : '';
  return `<path class="${cls}" d="${d}"/>${hit}`;
}
