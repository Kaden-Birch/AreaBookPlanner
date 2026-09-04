// VPN links + reusable endpoint directory (canonical two-sided links between clinic sites).
import { vpn as vpnApi, clinics as clinicsApi, devices as devicesApi } from './api.js';
import { openModal, esc, attr, options, toast, confirmDialog, formData, showFormError } from './ui.js';

const STATUS = { unknown: 'badge-grey', up: 'badge-green', down: 'badge-red', disabled: 'badge-yellow' };
const STATUS_LABELS = { unknown: 'Unknown', up: 'Up', down: 'Down', disabled: 'Disabled' };
const SECRETS_NOTICE = 'Do not store passwords, pre-shared keys, private keys, VPN configuration exports containing secrets, or recovery codes here. Store them in the approved password manager.';

function sideLabel(s) {
  if (!s) return '(unknown)';
  if (s.kind === 'endpoint') return `🌐 ${s.name}${s.private ? ' (private)' : ''}`;
  return `${s.clinic_name} · ${s.site_name}`;
}

function linkRow(l) {
  const st = STATUS[l.status] || STATUS.unknown;
  const dev = (side) => side && side.device ? ` <span class="muted">via ${esc(side.device.icon || '')} ${esc(side.device.name)}</span>` : '';
  return `<button type="button" class="vpn-row" data-id="${l.id}">
    <div class="vpn-ends">🔒 <strong>${esc(sideLabel(l.local))}</strong>${dev(l.local)} <span class="vpn-arrow">↔</span> <strong>${esc(sideLabel(l.remote))}</strong>${dev(l.remote)}</div>
    <div class="vpn-meta">${l.name ? esc(l.name) + ' · ' : ''}${l.vpn_type ? esc(l.vpn_type) + ' · ' : ''}<span class="badge ${st}">${esc(l.status_label)}</span></div>
  </button>`;
}

export async function openVpnPanel({ clinic, site = null, onChanged }) {
  const modal = openModal({
    title: `VPN links · ${clinic.shorthand || clinic.name}`,
    size: 'modal-lg',
    body: `<div id="vpn-body" class="mt">Loading…</div>`,
    footer: `<button class="btn" data-act="ranges">Network ranges</button><button class="btn" data-act="endpoints">Manage endpoints</button><button class="btn btn-primary" data-act="add">+ Add VPN link</button><button class="btn" data-act="close">Close</button>`,
  });
  const bodyEl = modal.body.querySelector('#vpn-body');
  let links = [];
  const changed = () => { refresh(); onChanged && onChanged(); };
  const refresh = async () => {
    const data = await vpnApi.links(clinic.id, site);
    links = data.links;
    bodyEl.innerHTML = links.length
      ? `<div class="vpn-list">${links.map(linkRow).join('')}</div>`
      : `<div class="card empty">No VPN links${site && site !== 'all' && site !== 'main' ? ' at this site' : ''} yet. Use “+ Add VPN link” to connect a router or firewall to another site or an external endpoint.</div>`;
    bodyEl.querySelectorAll('.vpn-row').forEach(el => {
      el.onclick = () => openLinkForm({ clinic, site, link: links.find(x => x.id === Number(el.dataset.id)), onSaved: changed });
    });
  };
  modal.root.querySelector('[data-act=close]').onclick = () => modal.close();
  modal.root.querySelector('[data-act=add]').onclick = () => openLinkForm({ clinic, site, onSaved: changed });
  modal.root.querySelector('[data-act=endpoints]').onclick = () => openEndpointList({ clinic, onChanged: refresh });
  modal.root.querySelector('[data-act=ranges]').onclick = () => openRangesManager({ clinic, site });
  await refresh();
  return modal;
}

// ---- Network ranges (advanced) --------------------------------------------------

export async function openRangesManager({ clinic, site = null }) {
  const modal = openModal({
    title: 'Network ranges',
    size: 'modal-lg',
    body: `<p class="small muted">Network ranges are optional. Add them when you need to document exactly which IP networks are available through a VPN. They are never required to create a VPN link or route.</p><div id="nr-body">Loading…</div>`,
    footer: `<button class="btn btn-primary" data-act="add">+ Add range</button><button class="btn" data-act="close">Close</button>`,
  });
  const bodyEl = modal.body.querySelector('#nr-body');
  let types = {}, siteInfo = null;
  const refresh = async () => {
    const data = await vpnApi.ranges(clinic.id, site);
    types = data.network_types; siteInfo = data.site;
    modal.root.querySelector('.modal-header h2').textContent = `Network ranges · ${siteInfo.clinic_name} · ${siteInfo.site_name}`;
    bodyEl.innerHTML = data.ranges.length
      ? `<div class="vpn-list">${data.ranges.map(r => `<button type="button" class="vpn-row" data-id="${r.id}">
          <div class="vpn-ends"><span class="mono">${esc(r.cidr)}</span> · <strong>${esc(r.name)}</strong> <span class="badge">${esc(r.type_label)}</span></div>
          ${r.overlaps.length ? `<div class="vpn-meta warn">⚠ Overlaps ${r.overlaps.map(o => `${esc(o.cidr)} at ${esc(o.clinic_name)} · ${esc(o.site_name)}`).join(', ')} — NAT or special routing may apply.</div>` : ''}
          ${r.notes ? `<div class="vpn-meta">${esc(r.notes)}</div>` : ''}</button>`).join('')}</div>`
      : '<div class="card empty">No network ranges recorded for this site.</div>';
    bodyEl.querySelectorAll('.vpn-row').forEach(el => el.onclick = async () => {
      const r = (await vpnApi.ranges(clinic.id, site)).ranges.find(x => x.id === Number(el.dataset.id));
      openRangeForm({ clinic, site, range: r, types, onSaved: refresh });
    });
  };
  modal.root.querySelector('[data-act=close]').onclick = () => modal.close();
  modal.root.querySelector('[data-act=add]').onclick = () => openRangeForm({ clinic, site, types, onSaved: refresh });
  await refresh();
  return modal;
}

export function openRangeForm({ clinic, site = null, range = null, types = {}, onSaved }) {
  const isEdit = !!range;
  const r = range || {};
  const typeOpts = Object.entries(types).map(([k, v]) => `<option value="${k}" ${k === (r.network_type || 'lan') ? 'selected' : ''}>${esc(v)}</option>`).join('');
  const modal = openModal({
    title: isEdit ? `Edit ${r.name}` : 'Add network range',
    body: `<form id="nr-form" autocomplete="off">
      <div class="field"><label>Name *</label><input name="name" required value="${attr(r.name)}" placeholder="e.g. Main LAN"></div>
      <div class="field-row">
        <div class="field"><label>Network range (CIDR) *</label><input name="cidr" required value="${attr(r.cidr)}" placeholder="10.20.0.0/24" class="mono"></div>
        <div class="field"><label>Type</label><select name="network_type">${typeOpts}</select></div>
      </div>
      <div class="field"><label>Notes</label><textarea name="notes" rows="2">${esc(r.notes)}</textarea></div>
    </form>`,
    footer: `${isEdit ? '<button class="btn btn-danger left" data-act="delete">Delete</button>' : ''}<button class="btn" data-act="cancel">Cancel</button><button class="btn btn-primary" data-act="save">${isEdit ? 'Save' : 'Add'}</button>`,
  });
  const form = modal.body.querySelector('#nr-form');
  modal.root.querySelector('[data-act=cancel]').onclick = () => modal.close();
  const del = modal.root.querySelector('[data-act=delete]');
  if (del) del.onclick = async () => {
    if (!(await confirmDialog(`Delete network range “${r.name}”?`, { okLabel: 'Delete', danger: true }))) return;
    await vpnApi.removeRange(r.id); toast('Range deleted'); modal.close(); onSaved && onSaved();
  };
  modal.root.querySelector('[data-act=save]').onclick = async () => {
    const d = formData(form);
    if (!d.name || !d.name.trim()) { showFormError(form, 'Name is required.'); return; }
    if (!d.cidr || !d.cidr.trim()) { showFormError(form, 'A network range (CIDR) is required.'); return; }
    try {
      if (isEdit) await vpnApi.updateRange(r.id, d); else await vpnApi.createRange(clinic.id, d, site);
      toast(isEdit ? 'Range saved' : 'Range added', 'success'); modal.close(); onSaved && onSaved();
    } catch (e) { showFormError(form, e.message); }
  };
  return modal;
}

// ---- VPN link form --------------------------------------------------------------

async function siteOptions(clinicId, selected) {
  const { sites } = await devicesApi.sites(clinicId);
  return sites.map(s => `<option value="${s.id === 'main' ? '' : s.id}" ${String(s.id === 'main' ? '' : s.id) === String(selected ?? '') ? 'selected' : ''}>${esc(s.name)}</option>`).join('');
}

async function terminatorOptions(clinicId, selected) {
  const { devices } = await devicesApi.list(clinicId);
  const t = devices.filter(d => d.device_type === 'router' || d.device_type === 'firewall');
  return `<option value="">— Not specified —</option>` + t.map(d =>
    `<option value="${d.id}" ${String(d.id) === String(selected ?? '') ? 'selected' : ''}>${esc(d.icon)} ${esc(d.name)}${d.location_name ? ` · ${esc(d.location_name)}` : ''}</option>`).join('');
}

// ---- Connectivity check tool ----------------------------------------------------
// "Can this site reach another site?" — resolved from the source site's connectivity.

function cidrRange(cidr) {
  const m = /^\s*(\d+)\.(\d+)\.(\d+)\.(\d+)\/(\d+)\s*$/.exec(cidr || '');
  if (!m) return null;
  const ip = ((+m[1] << 24) | (+m[2] << 16) | (+m[3] << 8) | (+m[4])) >>> 0;
  const bits = +m[5];
  const mask = bits === 0 ? 0 : (~((1 << (32 - bits)) - 1)) >>> 0;
  const net = (ip & mask) >>> 0;
  return [net, net + 2 ** (32 - bits) - 1];
}
function cidrsOverlap(a, b) { const ra = cidrRange(a), rb = cidrRange(b); return ra && rb && ra[0] <= rb[1] && rb[0] <= ra[1]; }

function rangesSection(srcRanges, destRanges) {
  if (!srcRanges || !destRanges || !srcRanges.length || !destRanges.length) return '';
  const conflicts = [];
  srcRanges.forEach(s => destRanges.forEach(d => { if (cidrsOverlap(s.cidr, d.cidr)) conflicts.push(`${s.cidr} ↔ ${d.cidr}`); }));
  return `<div class="cc-ranges">
    <div class="small"><strong>Source ranges:</strong> ${srcRanges.map(r => `<span class="mono">${esc(r.cidr)}</span>`).join(', ')}</div>
    <div class="small"><strong>Destination ranges:</strong> ${destRanges.map(r => `<span class="mono">${esc(r.cidr)}</span>`).join(', ')}</div>
    ${conflicts.length ? `<div class="small warn">⚠ Potential overlapping-subnet conflict: ${conflicts.map(esc).join(', ')} — NAT or special routing may be required.</div>` : ''}
  </div>`;
}

export async function openConnectivityCheck({ clinicId, site = null, label = '' }) {
  const modal = openModal({
    title: 'Connectivity check',
    size: 'modal-lg',
    body: `<div id="cc-body" class="mt">Loading…</div>`,
    footer: `<button class="btn" data-act="close">Close</button>`,
  });
  modal.root.querySelector('[data-act=close]').onclick = () => modal.close();
  const bodyEl = modal.body.querySelector('#cc-body');
  let conn, clinicsList;
  try {
    [conn, clinicsList] = await Promise.all([vpnApi.connectivity(clinicId, site), clinicsApi.list().catch(() => [])]);
  } catch (e) { bodyEl.innerHTML = `<div class="card empty">${esc(e.message)}</div>`; return modal; }
  clinicsList = Array.isArray(clinicsList) ? clinicsList : (clinicsList.clinics || []);
  const srcLabel = label || `${conn.source_site.clinic_name} · ${conn.source_site.site_name}`;
  // Reachable index by "clinicId:siteId".
  const reach = new Map();
  conn.direct.filter(d => d.kind === 'site').forEach(d => reach.set(`${d.clinic_id}:${d.site_id}`, { rel: 'direct', d }));
  conn.remote.forEach(r => reach.set(`${r.clinic_id}:${r.site_id}`, { rel: 'via', d: r }));
  // "To" options: every clinic's Main Site, plus any reachable destination (may be a secondary site).
  const opts = new Map();
  clinicsList.forEach(c => { if (c.id !== conn.source_site.clinic_id) opts.set(`${c.id}:main`, `${c.name} · Main Site`); });
  reach.forEach((v, k) => { const d = v.d; opts.set(k, `${d.clinic_name} · ${d.site_name}`); });

  bodyEl.innerHTML = `
    <div class="field-row">
      <div class="field"><label>From</label><input value="${attr(srcLabel)}" disabled></div>
      <div class="field"><label>To</label><select id="cc-to"><option value="">— Choose a site —</option>${[...opts.entries()].map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('')}</select></div>
    </div>
    <div id="cc-result" class="mt"></div>`;
  const resEl = bodyEl.querySelector('#cc-result');
  bodyEl.querySelector('#cc-to').onchange = (e) => {
    const key = e.target.value;
    if (!key) { resEl.innerHTML = ''; return; }
    const hit = reach.get(key);
    const toLabel = opts.get(key);
    if (!hit) {
      resEl.innerHTML = `<div class="card"><p><span class="badge badge-grey">Not documented as reachable</span></p>
        <p class="small muted">No direct VPN link or configured onward route documents reaching ${esc(toLabel)} from ${esc(srcLabel)}. Open a VPN link and set onward access to record a route.</p></div>`;
      return;
    }
    const d = hit.d;
    if (hit.rel === 'direct') {
      resEl.innerHTML = `<div class="card"><p><span class="badge badge-green">✓ Directly reachable</span></p>
        <div class="cc-path"><div>${esc(conn.source_site.clinic_name)} · ${esc(conn.source_site.site_name)}</div>
          <div class="cc-hop">→ ${esc(d.vpn_name || 'VPN link')} <span class="muted">(${esc(d.status_label)})</span></div>
          <div>${esc(d.clinic_name)} · ${esc(d.site_name)}</div></div>
        ${rangesSection(conn.source_site.ranges, d.ranges)}
        <p class="small muted mt">Documented connectivity — not a live reachability test.</p></div>`;
    } else {
      resEl.innerHTML = `<div class="card"><p><span class="badge badge-yellow">✓ Reachable via ${esc(d.via.clinic_name)}</span></p>
        <div class="cc-path"><div>${esc(conn.source_site.clinic_name)} · ${esc(conn.source_site.site_name)}</div>
          <div class="cc-hop">→ VPN link</div>
          <div>${esc(d.via.clinic_name)} · ${esc(d.via.site_name)}</div>
          <div class="cc-hop">→ VPN link</div>
          <div>${esc(d.clinic_name)} · ${esc(d.site_name)}</div></div>
        ${d.rationale ? `<p class="small">${esc(d.rationale)}</p>` : ''}
        ${rangesSection(conn.source_site.ranges, d.ranges)}
        <p class="small muted mt">Documented connectivity — not a live reachability test.</p></div>`;
    }
  };
  return modal;
}

function routingHtml(dir, t) {
  const anySel = t.options.some(o => o.selected);
  return `<div class="form-section routing-section" data-dir="${dir}">
    <h3>Reachability from ${esc(t.source.clinic_name)} · ${esc(t.source.site_name)} through ${esc(t.via.clinic_name)} · ${esc(t.via.site_name)}</h3>
    <p class="small muted">Can ${esc(t.source.clinic_name)} reach sites beyond ${esc(t.via.site_name)} through this VPN?</p>
    <div class="flex mb" style="gap:16px">
      <label class="checkbox"><input type="radio" name="route-${dir}" value="no" ${anySel ? '' : 'checked'}> No — ${esc(t.via.site_name)} only</label>
      <label class="checkbox"><input type="radio" name="route-${dir}" value="yes" ${anySel ? 'checked' : ''}> Yes — allow onward access to selected sites</label>
    </div>
    <div class="route-dests ${anySel ? '' : 'hidden'}" data-dests="${dir}">
      ${t.options.length ? t.options.map(o => `<div class="route-dest">
        <label class="checkbox block"><input type="checkbox" data-exit="${o.exit_vpn_link_id}" data-clinic="${o.clinic_id}" data-loc="${o.location_id ?? ''}" ${o.selected ? 'checked' : ''}> ${esc(o.clinic_name)} · ${esc(o.site_name)}${o.exit_status === 'disabled' ? ' <span class="muted">(tunnel disabled)</span>' : ''}</label>
        <input class="route-rationale" data-exit="${o.exit_vpn_link_id}" value="${attr(o.rationale || '')}" placeholder="why this route? (optional)">
      </div>`).join('')
        : '<p class="small muted">No other sites are directly connected to this intermediate site yet.</p>'}
    </div>
    <div class="help">These are documented routing intentions, not a live reachability test.</div>
  </div>`;
}

function collectTransit(form, dir) {
  const yes = form.querySelector(`[name=route-${dir}]:checked`)?.value === 'yes';
  if (!yes) return [];
  return [...form.querySelectorAll(`[data-dests="${dir}"] input[type=checkbox]:checked`)].map(cb => {
    const rat = form.querySelector(`[data-dests="${dir}"] .route-rationale[data-exit="${cb.dataset.exit}"]`);
    return {
      clinic_id: Number(cb.dataset.clinic),
      location_id: cb.dataset.loc === '' ? null : Number(cb.dataset.loc),
      exit_vpn_link_id: Number(cb.dataset.exit),
      rationale: rat && rat.value.trim() ? rat.value.trim() : null,
    };
  });
}

export async function openLinkForm({ clinic, site = null, link = null, onSaved }) {
  const isEdit = !!link;
  const raw = link ? link.raw : {};
  const aClinicId = raw.a_clinic_id || clinic.id;
  const [allClinics, endpointsResp] = await Promise.all([clinicsApi.list().catch(() => []), vpnApi.endpoints(clinic.id)]);
  const clinicsList = Array.isArray(allClinics) ? allClinics : (allClinics.clinics || []);
  const endpoints = endpointsResp.endpoints;
  const aClinic = clinicsList.find(c => c.id === aClinicId) || clinic;
  // Default the local site to the currently-selected equipment site when creating.
  const defaultALoc = isEdit ? raw.a_location_id : (site && site !== 'all' && site !== 'main' ? Number(site) : null);
  const [aSiteOpts, aTermOpts] = await Promise.all([siteOptions(aClinicId, defaultALoc), terminatorOptions(aClinicId, raw.a_device_id)]);
  const remoteKind = raw.b_kind || 'site';
  const clinicOpts = `<option value="">— Choose clinic —</option>` + clinicsList.map(c =>
    `<option value="${c.id}" ${String(c.id) === String(raw.b_clinic_id ?? '') ? 'selected' : ''}>${esc(c.name)}${c.shorthand ? ` (${esc(c.shorthand)})` : ''}</option>`).join('');
  const endpointOpts = `<option value="">— Choose endpoint —</option>` + endpoints.map(e =>
    `<option value="${e.id}" ${String(e.id) === String(raw.b_endpoint_id ?? '') ? 'selected' : ''}>${esc(e.name)}${e.private ? ' (private)' : ''}</option>`).join('');

  // Onward-access (transit) routing — only for an existing site-to-site link.
  let transit = null;
  if (isEdit && raw.b_kind === 'site') {
    try { transit = { a: await vpnApi.transitOptions(link.id, 'a'), b: await vpnApi.transitOptions(link.id, 'b') }; } catch { transit = null; }
  }
  const routingBlocks = transit ? routingHtml('a', transit.a) + routingHtml('b', transit.b) : '';

  const modal = openModal({
    title: isEdit ? 'Edit VPN link' : `Add VPN link · ${clinic.shorthand || clinic.name}`,
    size: 'modal-lg',
    body: `<form id="vpn-form" autocomplete="off">
      <div class="form-warn mb">🔒 ${esc(SECRETS_NOTICE)}</div>
      <div class="form-section"><h3>This end (${esc(aClinic.name)})</h3>
        <div class="field-row">
          <div class="field"><label>Site</label><select name="a_location_id">${aSiteOpts}</select></div>
          <div class="field"><label>Terminating router / firewall</label><select name="a_device_id">${aTermOpts}</select></div>
        </div>
      </div>
      <div class="form-section"><h3>Other end</h3>
        <div class="flex mb" style="gap:16px">
          <label class="checkbox"><input type="radio" name="remote_kind" value="site" ${remoteKind === 'site' ? 'checked' : ''}> Another clinic site</label>
          <label class="checkbox"><input type="radio" name="remote_kind" value="endpoint" ${remoteKind === 'endpoint' ? 'checked' : ''}> Custom / external endpoint</label>
        </div>
        <div id="remote-site" class="${remoteKind === 'site' ? '' : 'hidden'}">
          <div class="field-row">
            <div class="field"><label>Remote clinic</label><select name="b_clinic_id" id="b-clinic">${clinicOpts}</select></div>
            <div class="field"><label>Remote site</label><select name="b_location_id" id="b-site"><option value="">Main Site</option></select></div>
            <div class="field"><label>Remote router / firewall</label><select name="b_device_id" id="b-device"><option value="">— Not specified —</option></select></div>
          </div>
        </div>
        <div id="remote-endpoint" class="${remoteKind === 'endpoint' ? '' : 'hidden'}">
          <div class="field-row">
            <div class="field grow"><label>Endpoint</label><select name="b_endpoint_id">${endpointOpts}</select></div>
            <div class="field" style="align-self:end"><button type="button" class="btn" id="new-endpoint">+ New endpoint</button></div>
          </div>
          <div class="help">Shared endpoints are reusable across clinics; a private one stays with this clinic.</div>
        </div>
      </div>
      <div class="field-row">
        <div class="field"><label>Link name</label><input name="name" value="${attr(link ? link.name : '')}" placeholder="e.g. HQ ↔ North tunnel"></div>
        <div class="field"><label>VPN type / vendor</label><input name="vpn_type" value="${attr(link ? link.vpn_type : '')}" placeholder="e.g. IPsec, WireGuard, Meraki AutoVPN"></div>
        <div class="field"><label>Status</label><select name="status">${options(STATUS_LABELS, link ? link.status : 'unknown')}</select></div>
      </div>
      <div class="field"><label>Notes</label><textarea name="notes" rows="2" placeholder="What it's for, subnets at a glance, who manages it…">${esc(link ? link.notes : '')}</textarea></div>
      ${routingBlocks}
    </form>`,
    footer: `${isEdit ? '<button class="btn btn-danger left" data-act="delete">Delete</button>' : ''}<button class="btn" data-act="cancel">Cancel</button><button class="btn btn-primary" data-act="save">${isEdit ? 'Save changes' : 'Add link'}</button>`,
  });
  const form = modal.body.querySelector('#vpn-form');
  const siteBlock = form.querySelector('#remote-site');
  const epBlock = form.querySelector('#remote-endpoint');
  form.querySelectorAll('[name=remote_kind]').forEach(r => r.onchange = () => {
    const kind = form.elements.remote_kind.value;
    siteBlock.classList.toggle('hidden', kind !== 'site');
    epBlock.classList.toggle('hidden', kind !== 'endpoint');
  });

  const bSite = form.querySelector('#b-site'), bDevice = form.querySelector('#b-device');
  const loadRemote = async (clinicId, selSite, selDev) => {
    bSite.innerHTML = '<option value="">Main Site</option>';
    bDevice.innerHTML = '<option value="">— Not specified —</option>';
    if (!clinicId) return;
    const [sOpts, dOpts] = await Promise.all([siteOptions(clinicId, selSite), terminatorOptions(clinicId, selDev)]);
    bSite.innerHTML = sOpts;
    bDevice.innerHTML = dOpts;
  };
  form.querySelector('#b-clinic').onchange = (e) => loadRemote(e.target.value, null, null);
  if (raw.b_clinic_id) await loadRemote(raw.b_clinic_id, raw.b_location_id, raw.b_device_id);

  form.querySelectorAll('.routing-section').forEach(sec => {
    const dir = sec.dataset.dir, dests = sec.querySelector(`[data-dests="${dir}"]`);
    sec.querySelectorAll(`[name=route-${dir}]`).forEach(r => r.onchange = () => {
      dests.classList.toggle('hidden', form.querySelector(`[name=route-${dir}]:checked`).value !== 'yes');
    });
  });

  form.querySelector('#new-endpoint').onclick = () => openEndpointForm({
    clinic, onSaved: (ep) => {
      const sel = form.elements.b_endpoint_id;
      sel.insertAdjacentHTML('beforeend', `<option value="${ep.id}">${esc(ep.name)}${ep.private ? ' (private)' : ''}</option>`);
      sel.value = ep.id;
    },
  });

  modal.root.querySelector('[data-act=cancel]').onclick = () => modal.close();
  const del = modal.root.querySelector('[data-act=delete]');
  if (del) del.onclick = async () => {
    if (!(await confirmDialog('Delete this VPN link? It is removed from both sides.', { okLabel: 'Delete', danger: true }))) return;
    await vpnApi.removeLink(link.id); toast('VPN link deleted'); modal.close(); onSaved && onSaved();
  };
  modal.root.querySelector('[data-act=save]').onclick = async () => {
    const d = formData(form);
    const kind = form.elements.remote_kind.value;  // formData can't read a radio group
    const payload = {
      name: d.name, vpn_type: d.vpn_type, status: d.status, notes: d.notes,
      a_location_id: d.a_location_id || null, a_device_id: d.a_device_id || null,
      remote_kind: kind,
      b_clinic_id: kind === 'site' ? (d.b_clinic_id || null) : null,
      b_location_id: kind === 'site' ? (d.b_location_id || null) : null,
      b_device_id: kind === 'site' ? (d.b_device_id || null) : null,
      b_endpoint_id: kind === 'endpoint' ? (d.b_endpoint_id || null) : null,
    };
    if (kind === 'site' && !payload.b_clinic_id) { showFormError(form, 'Choose a remote clinic.'); return; }
    if (kind === 'endpoint' && !payload.b_endpoint_id) { showFormError(form, 'Choose or create an endpoint.'); return; }
    try {
      if (isEdit) {
        await vpnApi.updateLink(link.id, payload);
        if (transit && payload.remote_kind === 'site') {
          await vpnApi.setTransit(link.id, { origin: 'a', destinations: collectTransit(form, 'a') });
          await vpnApi.setTransit(link.id, { origin: 'b', destinations: collectTransit(form, 'b') });
        }
      } else {
        await vpnApi.createLink(clinic.id, payload);
      }
      toast(isEdit ? 'VPN link updated' : 'VPN link added', 'success'); modal.close(); onSaved && onSaved();
    } catch (e) { showFormError(form, e.message); }
  };
  return modal;
}

// ---- Endpoint directory ---------------------------------------------------------

export async function openEndpointList({ clinic, onChanged }) {
  const modal = openModal({
    title: 'VPN endpoints',
    size: 'modal-lg',
    body: `<p class="small muted">Reusable external endpoints (e.g. AHS). Shared endpoints appear for every clinic; private ones stay with this clinic.</p><div id="ep-body">Loading…</div>`,
    footer: `<button class="btn btn-primary" data-act="add">+ New endpoint</button><button class="btn" data-act="close">Close</button>`,
  });
  const bodyEl = modal.body.querySelector('#ep-body');
  const refresh = async () => {
    const { endpoints } = await vpnApi.endpoints(clinic.id);
    bodyEl.innerHTML = endpoints.length
      ? `<div class="vpn-list">${endpoints.map(e => `<button type="button" class="vpn-row" data-id="${e.id}">
          <div class="vpn-ends">🌐 <strong>${esc(e.name)}</strong> ${e.private ? '<span class="badge badge-purple">Private</span>' : '<span class="badge">Shared</span>'}</div>
          <div class="vpn-meta">${[e.vendor, e.display_address || e.address].filter(Boolean).map(esc).join(' · ')}</div></button>`).join('')}</div>`
      : '<div class="card empty">No endpoints yet.</div>';
    bodyEl.querySelectorAll('.vpn-row').forEach(el => el.onclick = async () => {
      const ep = (await vpnApi.endpoints(clinic.id)).endpoints.find(x => x.id === Number(el.dataset.id));
      openEndpointForm({ clinic, endpoint: ep, onSaved: () => { refresh(); onChanged && onChanged(); }, onDeleted: () => { refresh(); onChanged && onChanged(); } });
    });
  };
  modal.root.querySelector('[data-act=close]').onclick = () => modal.close();
  modal.root.querySelector('[data-act=add]').onclick = () => openEndpointForm({ clinic, onSaved: () => { refresh(); onChanged && onChanged(); } });
  await refresh();
  return modal;
}

export function openEndpointForm({ clinic, endpoint = null, onSaved, onDeleted }) {
  const isEdit = !!endpoint;
  const e = endpoint || {};
  const modal = openModal({
    title: isEdit ? `Edit endpoint · ${e.name}` : 'New VPN endpoint',
    size: 'modal-lg',
    body: `<form id="ep-form" autocomplete="off">
      <div class="form-warn mb">🔒 ${esc(SECRETS_NOTICE)}</div>
      <div class="field"><label>Name *</label><input name="name" required value="${attr(e.name)}" placeholder="e.g. AHS Netcare gateway"></div>
      <div class="field-row">
        <div class="field"><label>Vendor</label><input name="vendor" value="${attr(e.vendor)}" placeholder="e.g. Cisco, AHS"></div>
        <div class="field"><label class="checkbox mt"><input type="checkbox" name="private" ${e.private ? 'checked' : ''}> Private to ${esc(clinic.shorthand || clinic.name)}</label></div>
      </div>
      <div class="field"><label>Description</label><textarea name="description" rows="2">${esc(e.description)}</textarea></div>
      <div class="field-row">
        <div class="field"><label>Address</label><input name="address" value="${attr(e.address)}"></div>
        <div class="field"><label>Displayed address</label><input name="display_address" value="${attr(e.display_address)}"></div>
      </div>
      <div class="field-row">
        <div class="field"><label>Latitude</label><input name="lat" type="number" step="any" value="${attr(e.lat ?? '')}"><div class="help">Optional — only mapped if set.</div></div>
        <div class="field"><label>Longitude</label><input name="lng" type="number" step="any" value="${attr(e.lng ?? '')}"></div>
      </div>
      <div class="field"><label>Support / vendor info</label><textarea name="support_info" rows="2" placeholder="Support portal, phone, account #…">${esc(e.support_info)}</textarea></div>
    </form>`,
    footer: `${isEdit ? '<button class="btn btn-danger left" data-act="delete">Delete</button>' : ''}<button class="btn" data-act="cancel">Cancel</button><button class="btn btn-primary" data-act="save">${isEdit ? 'Save' : 'Create'}</button>`,
  });
  const form = modal.body.querySelector('#ep-form');
  modal.root.querySelector('[data-act=cancel]').onclick = () => modal.close();
  const del = modal.root.querySelector('[data-act=delete]');
  if (del) del.onclick = async () => {
    if (!(await confirmDialog(`Delete endpoint “${e.name}”? Any VPN links using it are removed too.`, { okLabel: 'Delete', danger: true }))) return;
    await vpnApi.removeEndpoint(e.id); toast('Endpoint deleted'); modal.close(); (onDeleted || onSaved) && (onDeleted || onSaved)();
  };
  modal.root.querySelector('[data-act=save]').onclick = async () => {
    const d = formData(form);
    if (!d.name || !d.name.trim()) { showFormError(form, 'Name is required.'); return; }
    try {
      const saved = isEdit ? await vpnApi.updateEndpoint(e.id, d) : await vpnApi.createEndpoint(clinic.id, d);
      toast(isEdit ? 'Endpoint saved' : 'Endpoint created', 'success'); modal.close(); onSaved && onSaved(saved);
    } catch (err) { showFormError(form, err.message); }
  };
  return modal;
}
