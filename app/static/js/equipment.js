// Device form, device detail (with tickets, services, downlinks, uplink chain) and helpers.
import { devices } from './api.js';
import { esc, attr, openModal, confirmDialog, toast, formData, showFormError, options, fmtDate, fmtDateOnly, navigate, toDateInput } from './ui.js';

export function accentClass(type, meta) {
  const t = meta.types[type] || meta.types.other;
  if (t.network) return 'accent-network';
  if (type === 'server') return 'accent-server';
  if (type === 'voip' || type === 'wireless') return 'accent-phone';
  if (type === 'printer') return 'accent-printer';
  if (type === 'workstation' || type === 'laptop') return 'accent-endpoint';
  return 'accent-other';
}

export function plural(label, n) {
  if (n === 1) return label;
  return /(s|ch|x|sh)$/.test(label) ? `${label}es` : `${label}s`;
}

export function deviceSubtitle(d) {
  return [d.designation, d.user_name ? `👤 ${d.user_name}` : null, d.ip_address].filter(Boolean).join(' · ');
}

function uplinkOptions(list, selected, excludeId) {
  const opts = list.filter(d => d.id !== excludeId).map(d => `<option value="${d.id}" ${String(d.id) === String(selected) ? 'selected' : ''}>${esc(d.icon)} ${esc(d.name)}${d.ip_address ? ` (${esc(d.ip_address)})` : ''}</option>`);
  return `<option value="">— None (top of the network / standalone) —</option>${opts.join('')}`;
}

// ---- Device form --------------------------------------------------------------

export async function openDeviceForm({ clinic, device = null, initial = null, onSaved }) {
  const meta = await devices.meta();
  const { devices: all, locations, shorthand } = await devices.list(clinic.id);
  const d = { device_type: 'workstation', status: 'active', ...(device || {}), ...(initial || {}) };
  const isEdit = !!device;
  const typeOpts = Object.entries(meta.types).map(([k, v]) => `<option value="${k}" ${k === d.device_type ? 'selected' : ''}>${esc(v.icon)} ${esc(v.label)}</option>`).join('');
  const modal = openModal({
    title: isEdit ? `Edit ${d.name}` : `Add equipment · ${clinic.shorthand || clinic.name}`,
    size: 'modal-lg',
    body: `<form id="device-form" autocomplete="off">
      <div class="field-row">
        <div class="field"><label>Type</label><select name="device_type" id="dev-type">${typeOpts}</select></div>
        <div class="field" style="grid-column: span 2"><label>Name</label>
          <div class="flex"><input name="name" id="dev-name" value="${attr(d.name)}" placeholder="auto: ${attr(shorthand)}-W001" class="grow"><button type="button" class="btn" id="dev-autoname" title="Use the next name from the template">Auto</button></div>
          <div class="help" id="dev-name-help">Template {shorthand}-{prefix}{number}: leave blank to auto-name, or type your own.</div></div>
        ${!isEdit ? `<div class="field"><label>How many</label><input name="quantity" type="number" min="1" max="50" value="1"><div class="help">More than 1 auto-names them all.</div></div>` : ''}
      </div>
      <div class="field-row">
        <div class="field"><label id="desig-label">Designation</label><input name="designation" list="desig-list" value="${attr(d.designation)}" placeholder="e.g. Exam room"><datalist id="desig-list"></datalist></div>
        <div class="field user-field"><label>User / assigned to</label><input name="user_name" value="${attr(d.user_name)}" placeholder="e.g. Dr. Lee, Front desk"></div>
        <div class="field"><label>Status</label><select name="status">${options(meta.statuses, d.status)}</select></div>
        ${locations.length ? `<div class="field"><label>Location / site</label><select name="location_id"><option value="">Main</option>${locations.map(l => `<option value="${l.id}" ${String(l.id) === String(d.location_id) ? 'selected' : ''}>${esc(l.name)}</option>`).join('')}</select></div>` : ''}
      </div>
      <div class="form-section"><h3>Network</h3>
        <div class="field-row">
          <div class="field" style="grid-column: span 2"><label>Uplink device (what it plugs into)</label><select name="uplink_id" id="dev-uplink">${uplinkOptions(all, d.uplink_id, device ? device.id : null)}</select>
            <div class="help">e.g. a workstation → its VoIP phone → the switch → the firewall.</div></div>
          <div class="field"><label>Link</label>
            <div class="flex mt" style="gap:14px"><label class="checkbox"><input type="radio" name="link_type" value="ethernet" ${d.link_type !== 'wireless' ? 'checked' : ''}> 🔌 Wired</label><label class="checkbox"><input type="radio" name="link_type" value="wireless" ${d.link_type === 'wireless' ? 'checked' : ''}> 📶 Wireless</label></div></div>
          <div class="field"><label>IP address</label><input name="ip_address" value="${attr(d.ip_address)}" placeholder="192.168.1.20" class="mono"></div>
          <div class="field"><label>MAC address</label><input name="mac_address" value="${attr(d.mac_address)}" placeholder="AA:BB:CC:DD:EE:FF"></div>
        </div>
      </div>
      <div class="form-section"><h3>Hardware</h3>
        <div class="field-row">
          <div class="field"><label>Manufacturer</label><input name="manufacturer" value="${attr(d.manufacturer)}" placeholder="Dell, HP, Ubiquiti…"></div>
          <div class="field"><label>Model</label><input name="model" value="${attr(d.model)}"></div>
          <div class="field"><label>Serial / service tag</label><input name="serial" value="${attr(d.serial)}"></div>
          <div class="field os-field"><label>Operating system</label><input name="os" value="${attr(d.os)}" placeholder="Windows 11 Pro, Ubuntu 24.04…"></div>
          <div class="field"><label>Purchased</label><input name="purchase_date" type="date" value="${attr(d.purchase_date)}"></div>
          <div class="field"><label>Warranty until</label><input name="warranty_until" type="date" value="${attr(d.warranty_until)}"></div>
        </div>
      </div>
      <div class="form-section services-field"><h3>Services running on this server</h3>
        <textarea name="services" rows="3" placeholder="One per line, e.g.&#10;Active Directory&#10;File shares (\\\\COC-S001\\shared)&#10;Backup agent">${esc((d.services || []).join('\\n'))}</textarea></div>
      <div class="field mt"><label>Notes</label><textarea name="notes" rows="3" placeholder="Where it sits, quirks, passwords go in the password manager not here…">${esc(d.notes)}</textarea></div>
    </form>`,
    footer: `${isEdit ? '<button class="btn btn-danger left" data-act="delete">Delete</button>' : ''}<button class="btn" data-act="cancel">Cancel</button><button class="btn btn-primary" data-act="save">${isEdit ? 'Save changes' : 'Add'}</button>`,
  });
  const form = modal.body.querySelector('#device-form');
  const typeSel = form.querySelector('#dev-type');
  const nameEl = form.querySelector('#dev-name');
  const syncType = async () => {
    const t = typeSel.value;
    form.querySelector('#desig-list').innerHTML = (meta.designations[t] || []).map(x => `<option value="${attr(x)}">`).join('');
    form.querySelector('#desig-label').textContent = t === 'server' ? 'Server role / designation' : 'Designation';
    form.querySelector('.user-field').classList.toggle('hidden', !meta.user_types.includes(t));
    form.querySelector('.services-field').classList.toggle('hidden', t !== 'server');
    form.querySelector('.os-field').classList.toggle('hidden', !['workstation', 'laptop', 'server', 'wireless', 'other'].includes(t));
    if (t === 'wireless' && !isEdit) form.querySelector('[name=link_type][value=wireless]').checked = true;
    try {
      const nn = await devices.nextName(clinic.id, t);
      nameEl.placeholder = `auto: ${nn.name}`;
      form.querySelector('#dev-name-help').textContent = `Template ${nn.template} → next is ${nn.name}. Leave blank to use it, or type your own.`;
    } catch { /* ignore */ }
  };
  typeSel.addEventListener('change', syncType);
  syncType();
  form.querySelector('#dev-autoname').onclick = async () => { const nn = await devices.nextName(clinic.id, typeSel.value); nameEl.value = nn.name; };

  modal.root.querySelector('[data-act=cancel]').onclick = () => modal.close();
  const del = modal.root.querySelector('[data-act=delete]');
  if (del) del.onclick = async () => {
    if (!(await confirmDialog(`Delete ${d.name}? Devices plugged into it will be left without an uplink.`))) return;
    await devices.remove(device.id); toast('Device deleted'); modal.close(); onSaved && onSaved(null);
  };
  const save = async () => {
    const data = formData(form);
    data.uplink_id = data.uplink_id ? Number(data.uplink_id) : null;
    data.location_id = data.location_id ? Number(data.location_id) : null;
    data.link_type = form.querySelector('[name=link_type]:checked').value;
    if (!isEdit) data.quantity = Math.max(1, Number(data.quantity) || 1);
    try {
      const saved = isEdit ? await devices.update(device.id, data) : await devices.create(clinic.id, data);
      const n = Array.isArray(saved) ? saved.length : 1;
      toast(isEdit ? 'Device updated' : `${n} device${n === 1 ? '' : 's'} added`, 'success');
      modal.close(); onSaved && onSaved(saved);
    } catch (e) { showFormError(form, e.message); }
  };
  modal.root.querySelector('[data-act=save]').onclick = save;
  form.addEventListener('submit', (e) => { e.preventDefault(); save(); });
  return modal;
}

// ---- Device detail ----------------------------------------------------------------

export async function openDeviceDetail({ deviceId, clinic, onChanged }) {
  const meta = await devices.meta();
  let d;
  try { d = await devices.get(deviceId); } catch (e) { toast(e.message, 'error'); return; }
  const warrantyOver = d.warranty_until && d.warranty_until < toDateInput(new Date());
  const modal = openModal({
    title: `${d.icon} ${d.name}`,
    size: 'modal-lg',
    body: `
      <div class="device-head">
        <span class="badge">${esc(d.type_label)}</span>
        ${d.designation ? `<span class="badge badge-purple">${esc(d.designation)}</span>` : ''}
        <span class="badge ${d.status === 'active' ? 'badge-green' : d.status === 'spare' ? 'badge-yellow' : 'badge-grey'}">${esc(d.status_label)}</span>
        ${d.location_name ? `<span class="badge">📍 ${esc(d.location_name)}</span>` : ''}
        ${d.ticket_count ? `<span class="badge badge-red">🎫 ${d.ticket_count} ticket${d.ticket_count === 1 ? '' : 's'}</span>` : ''}
        ${warrantyOver ? '<span class="badge badge-overdue">Warranty expired</span>' : ''}
      </div>
      <div class="chain mb">
        ${[...d.uplink_chain].reverse().map(u => `<span class="node" data-open="${u.id}" title="Open ${attr(u.name)}">${esc(u.icon)} ${esc(u.name)}</span><span>→</span>`).join('')}
        <span class="node me">${esc(d.icon)} ${esc(d.name)}</span>
        ${d.uplink_id ? `<span class="muted">· ${d.link_type === 'wireless' ? '📶 wireless' : '🔌 wired'} to ${esc(d.uplink_name)}</span>` : '<span class="muted">· no uplink</span>'}
      </div>
      <div class="grid-2">
        <div>
          <dl class="kv">
            ${d.user_name ? `<dt>User</dt><dd>${esc(d.user_name)}</dd>` : ''}
            <dt>IP address</dt><dd class="mono">${esc(d.ip_address || '—')}</dd>
            ${d.mac_address ? `<dt>MAC</dt><dd class="mono">${esc(d.mac_address)}</dd>` : ''}
            ${d.os ? `<dt>OS</dt><dd>${esc(d.os)}</dd>` : ''}
            <dt>Hardware</dt><dd>${esc([d.manufacturer, d.model].filter(Boolean).join(' ') || '—')}</dd>
            ${d.serial ? `<dt>Serial</dt><dd class="mono">${esc(d.serial)}</dd>` : ''}
            ${d.purchase_date ? `<dt>Purchased</dt><dd>${esc(fmtDateOnly(d.purchase_date))}</dd>` : ''}
            ${d.warranty_until ? `<dt>Warranty</dt><dd>${esc(fmtDateOnly(d.warranty_until))}${warrantyOver ? ' <span class="badge badge-overdue">expired</span>' : ''}</dd>` : ''}
            <dt>Added</dt><dd>${esc(fmtDate(d.created_at))}</dd>
          </dl>
          ${d.device_type === 'server' ? `<h3 class="mt">Services</h3>${d.services.length ? `<div class="svc-list">${d.services.map(s => `<span>${esc(s)}</span>`).join('')}</div>` : '<p class="muted small">None recorded. Edit the device to add services.</p>'}` : ''}
          <h3 class="mt">Notes</h3>
          ${d.notes ? `<pre class="wrap">${esc(d.notes)}</pre>` : '<p class="muted small">No notes.</p>'}
        </div>
        <div>
          <h3>Devices plugged into this (${d.downlinks.length})</h3>
          ${d.downlinks.length ? d.downlinks.map(x => `<div class="downlink-row" data-open="${x.id}"><span>${esc(x.icon)}</span><strong>${esc(x.name)}</strong><span class="muted small">${esc(deviceSubtitle(x))}</span><span class="link-icon">${x.link_type === 'wireless' ? '📶' : '🔌'}</span></div>`).join('') : '<p class="muted small">Nothing uses this device as an uplink.</p>'}
          <h3 class="mt">Tickets (${d.tickets.length})</h3>
          <div id="ticket-list">${d.tickets.length ? d.tickets.map(t => ticketRow(t)).join('') : '<p class="muted small">No tickets linked yet.</p>'}</div>
          <form id="ticket-form" class="mt">
            <div class="field-row">
              <div class="field" style="grid-column: span 2"><input name="title" placeholder="Ticket title, e.g. Printer jams on tray 2" required></div>
              <div class="field"><input name="ticket_date" type="date" value="${toDateInput(new Date())}"></div>
            </div>
            <div class="field-row">
              <div class="field" style="grid-column: span 2"><input name="url" placeholder="Link to the ticket (optional)"></div>
              <div class="field"><button class="btn btn-sm btn-primary" type="submit">+ Add ticket</button></div>
            </div>
          </form>
        </div>
      </div>`,
    footer: `<button class="btn btn-danger left" data-act="delete">Delete</button>
             <button class="btn" data-act="clone" title="Add another device like this one (same type, model, uplink)">Clone</button>
             <button class="btn" data-act="close">Close</button>
             <button class="btn btn-primary" data-act="edit">Edit</button>`,
    onClose: () => onChanged && onChanged(),
  });
  const reopen = (id) => { modal.close(); openDeviceDetail({ deviceId: id, clinic, onChanged }); };
  modal.body.querySelectorAll('[data-open]').forEach(el => { el.onclick = () => reopen(Number(el.dataset.open)); });
  modal.root.querySelector('[data-act=close]').onclick = () => modal.close();
  modal.root.querySelector('[data-act=edit]').onclick = () => { modal.close(); openDeviceForm({ clinic, device: d, onSaved: (saved) => { if (saved) openDeviceDetail({ deviceId: d.id, clinic, onChanged }); else onChanged && onChanged(); } }); };
  modal.root.querySelector('[data-act=clone]').onclick = () => {
    modal.close();
    const initial = { device_type: d.device_type, designation: d.designation, manufacturer: d.manufacturer, model: d.model, os: d.os, uplink_id: d.uplink_id, link_type: d.link_type, location_id: d.location_id, status: d.status, name: '' };
    openDeviceForm({ clinic, initial, onSaved: () => onChanged && onChanged() });
  };
  modal.root.querySelector('[data-act=delete]').onclick = async () => {
    if (!(await confirmDialog(`Delete ${d.name}? Devices plugged into it will be left without an uplink.`))) return;
    await devices.remove(d.id); toast('Device deleted'); modal.close();
  };
  const tf = modal.body.querySelector('#ticket-form');
  tf.onsubmit = async (e) => {
    e.preventDefault();
    const data = formData(tf);
    if (!data.title.trim()) return;
    try { await devices.addTicket(d.id, data); toast('Ticket added', 'success'); reopen(d.id); }
    catch (err) { showFormError(tf, err.message); }
  };
  modal.body.querySelectorAll('[data-del-ticket]').forEach(b => {
    b.onclick = async () => { if (!(await confirmDialog('Remove this ticket link?'))) return; await devices.removeTicket(d.id, Number(b.dataset.delTicket)); reopen(d.id); };
  });
  return modal;
}

function ticketRow(t) {
  return `<div class="ticket-row">
    <span>🎫</span>
    <div class="body">${t.url ? `<a href="${attr(t.url)}" target="_blank" rel="noopener">${esc(t.title)}</a>` : `<strong>${esc(t.title)}</strong>`}
      <div class="muted small">${t.ticket_date ? esc(fmtDateOnly(t.ticket_date)) : esc(fmtDate(t.created_at))}${t.notes ? ` · ${esc(t.notes)}` : ''}</div></div>
    <button class="btn btn-link btn-sm" data-del-ticket="${t.id}">Remove</button>
  </div>`;
}
