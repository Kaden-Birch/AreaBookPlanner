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
    footer: `<button class="btn" data-act="endpoints">Manage endpoints</button><button class="btn btn-primary" data-act="add">+ Add VPN link</button><button class="btn" data-act="close">Close</button>`,
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
  await refresh();
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
      if (isEdit) await vpnApi.updateLink(link.id, payload);
      else await vpnApi.createLink(clinic.id, payload);
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
