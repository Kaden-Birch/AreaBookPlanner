import { api, devices } from './api.js';
import { esc, attr, openModal, toast, showFormError, confirmDialog } from './ui.js';

const option=(value,label,selected)=>`<option value="${attr(value)}" ${String(value)===String(selected)?'selected':''}>${esc(label)}</option>`;

export async function openNetwork({clinic,deviceId,onChanged}) {
  let data, catalog;
  try { [data,catalog]=await Promise.all([api.get(`/api/devices/${deviceId}/network`),api.get(`/api/clinics/${clinic.id}/vlans`)]); }
  catch(e){toast(e.message,'error');return;}
  let rows=data.interfaces;
  if(!rows.length&&data.legacy_ip)rows=[{name:'Primary',mac_address:data.legacy_mac,addresses:[{address:data.legacy_ip,is_primary:true}],memberships:[]}];
  const vlans=catalog.vlans.filter(v=>v.location_id===data.location_id);
  const modal=openModal({title:'Network interfaces & addresses',size:'modal-lg',body:`<p>Record each interface, its IPv4/IPv6 addresses, and VLAN memberships. Choose one primary address for the device.</p>${data.legacy_ip?`<p class="muted small">Previously recorded address: ${esc(data.legacy_ip)}</p>`:''}<form id="network-form"><div id="network-interfaces"></div><button type="button" class="btn" id="network-add">+ Add interface</button><p class="help">Changes, including removals, apply when you save.</p></form>`,footer:'<button class="btn" data-close>Cancel</button><button class="btn btn-primary" data-save>Save network</button>'});
  const form=modal.body.querySelector('form'),host=form.querySelector('#network-interfaces');
  const vlanOptions=(selected,empty='No VLAN')=>option('',empty,selected??'')+vlans.map(v=>option(v.id,`${v.tag} · ${v.name}`,selected)).join('');
  const capture=()=>[...host.querySelectorAll('[data-interface]')].map(el=>{
    const val=name=>el.querySelector(`[name="${name}"]`).value;
    return {id:el.dataset.id?Number(el.dataset.id):null,name:val('name'),mac_address:val('mac_address'),notes:val('interface_notes'),
      memberships:[...el.querySelectorAll('[data-membership]')].map(m=>({vlan_id:Number(m.querySelector('[name=vlan]').value),mode:m.querySelector('[name=mode]').value})),
      addresses:[...el.querySelectorAll('[data-address]')].map(a=>{const v=n=>a.querySelector(`[name="${n}"]`).value;return {address:v('address'),prefix_length:v('prefix')===''?null:Number(v('prefix')),vlan_id:v('address_vlan')===''?null:Number(v('address_vlan')),kind:v('kind'),is_primary:a.querySelector('[name=primary]').checked,hostname:v('hostname'),notes:v('address_notes')};})};
  });
  const draw=()=>{
    host.innerHTML=rows.map((i,index)=>`<fieldset class="network-interface" data-interface="${index}" data-id="${i.id||''}"><legend>Interface ${index+1}</legend>
      <div class="field-row"><label>Interface name<input name="name" required maxlength="100" value="${attr(i.name)}" placeholder="eth0, LAN, iDRAC…"></label><label>MAC address<input name="mac_address" value="${attr(i.mac_address)}" placeholder="AA:BB:CC:DD:EE:FF"></label></div>
      <label>Interface notes<textarea name="interface_notes" rows="2">${esc(i.notes)}</textarea></label>
      <h4>VLAN memberships</h4>${!vlans.length?'<p class="help">Create VLANs for this site using Manage VLANs in the topology.</p>':''}
      ${(i.memberships||[]).map((m,j)=>`<div class="field-row" data-membership><label>VLAN<select name="vlan" required>${vlanOptions(m.vlan_id,'Choose VLAN')}</select></label><label>Membership<select name="mode">${['access','tagged','native','routed'].map(k=>option(k,k,m.mode||'access')).join('')}</select></label><button type="button" class="btn btn-sm" data-remove-membership="${j}">Remove membership</button></div>`).join('')}
      <button type="button" class="btn btn-sm" data-add-membership ${vlans.length?'':'disabled'}>+ Assign VLAN</button>
      <h4>Addresses</h4>${(i.addresses||[]).map((a,j)=>`<fieldset data-address><legend>Address ${j+1}</legend><div class="field-row"><label>IPv4 or IPv6<input name="address" required value="${attr(a.address)}" placeholder="10.0.0.10 or 2001:db8::10"></label><label>Prefix length<input type="number" name="prefix" min="0" max="128" value="${attr(a.prefix_length??'')}" placeholder="24 or 64"></label></div>
        <div class="field-row"><label>Purpose<select name="kind">${['static','dhcp','management','virtual','loopback','service','nat','floating'].map(k=>option(k,k,a.kind||'static')).join('')}</select></label><label>Address VLAN<select name="address_vlan">${vlanOptions(a.vlan_id)}</select></label></div>
        <label class="network-primary"><input type="radio" name="primary" ${a.is_primary?'checked':''}> Primary device address</label>
        <label>Hostname<input name="hostname" maxlength="255" value="${attr(a.hostname)}"></label><label>Address notes<textarea name="address_notes" rows="1">${esc(a.notes)}</textarea></label>
        <button type="button" class="btn btn-sm" data-remove-address="${j}">Remove address</button></fieldset>`).join('')}
      <div class="actions"><button type="button" class="btn btn-sm" data-add-address>+ Add address</button><button type="button" class="btn btn-sm" data-remove-interface>Remove interface</button></div></fieldset>`).join('')||'<p class="muted">No interfaces recorded.</p>';
    host.querySelectorAll('[data-interface]').forEach(el=>{
      const index=Number(el.dataset.interface);
      const change=fn=>{rows=capture();fn(rows[index]);draw();};
      el.querySelector('[data-add-address]').onclick=()=>change(i=>i.addresses.push({address:'',kind:'static',is_primary:false}));
      el.querySelector('[data-add-membership]').onclick=()=>change(i=>i.memberships.push({vlan_id:vlans[0]?.id,mode:'tagged'}));
      el.querySelector('[data-remove-interface]').onclick=()=>change(()=>rows.splice(index,1));
      el.querySelectorAll('[data-remove-address]').forEach(b=>b.onclick=()=>change(i=>i.addresses.splice(Number(b.dataset.removeAddress),1)));
      el.querySelectorAll('[data-remove-membership]').forEach(b=>b.onclick=()=>change(i=>i.memberships.splice(Number(b.dataset.removeMembership),1)));
    });
  };
  form.querySelector('#network-add').onclick=()=>{rows=capture();rows.push({name:'',addresses:[],memberships:[]});draw();};
  modal.root.querySelector('[data-close]').onclick=()=>modal.close();
  const save=async()=>{
    if(!form.reportValidity())return;
    const button=modal.root.querySelector('[data-save]');button.disabled=true;
    try{await api.put(`/api/devices/${deviceId}/network`,{interfaces:capture()});toast('Network saved','success');modal.close();onChanged?.();}
    catch(e){showFormError(form,e.message);}finally{button.disabled=false;}
  };
  modal.root.querySelector('[data-save]').onclick=save;form.onsubmit=e=>{e.preventDefault();save();};draw();
}

export async function openVlans({clinic,site,onChanged}) {
  const modal=openModal({title:'VLANs & subnets',size:'modal-lg',body:'<div id="vlan-list">Loading…</div>',footer:'<button class="btn" data-close>Close</button><button class="btn btn-primary" data-add>+ Add VLAN</button>',onClose:()=>onChanged?.()});
  let catalog,sites;
  const load=async()=>{
    try{
      [catalog,sites]=await Promise.all([api.get(`/api/clinics/${clinic.id}/vlans`,{site}),devices.sites(clinic.id)]);
      modal.body.querySelector('#vlan-list').innerHTML=catalog.vlans.map(v=>`<div class="vlan-record"><strong><span class="vlan-dot" style="background:${attr(v.color)}"></span> ${v.tag} · ${esc(v.name)}</strong><p class="muted small">${esc(v.location_name||'Main site')} · ${esc(v.subnets.join(', ')||'No subnets recorded')} · ${esc(v.dhcp_mode)}</p>${v.description?`<p>${esc(v.description)}</p>`:''}<div class="actions"><button class="btn btn-sm" data-edit-vlan="${v.id}">Edit</button><button class="btn btn-sm" data-delete-vlan="${v.id}">Delete</button></div></div>`).join('')||'<p class="muted">No VLANs recorded for this site.</p>';
      modal.body.querySelectorAll('[data-edit-vlan]').forEach(b=>b.onclick=()=>edit(catalog.vlans.find(v=>v.id===Number(b.dataset.editVlan))));
      modal.body.querySelectorAll('[data-delete-vlan]').forEach(b=>b.onclick=async()=>{if(!await confirmDialog('Delete this VLAN? VLANs assigned to interfaces must be unassigned first.'))return;try{await api.del(`/api/clinics/${clinic.id}/vlans/${b.dataset.deleteVlan}`);await load();}catch(e){toast(e.message,'error');}});
    }catch(e){modal.body.querySelector('#vlan-list').textContent=e.message;}
  };
  const edit=(v={})=>{
    if(!catalog||!sites)return;
    const loc=v.location_id??(site&&site!=='all'&&site!=='main'?Number(site):'');
    const formModal=openModal({title:v.id?'Edit VLAN': 'Add VLAN',size:'modal-lg',body:`<form id="vlan-form">
      <div class="field-row"><label>VLAN ID<input name="tag" type="number" min="1" max="4094" required value="${attr(v.tag??'')}"></label><label>Name<input name="name" required maxlength="100" value="${attr(v.name)}"></label></div>
      <div class="field-row"><label>Site<select name="location_id">${option('','Main site',loc)}${sites.sites.filter(s=>s.id!=='main').map(s=>option(s.id,s.name,loc)).join('')}</select></label><label>Colour<input type="color" name="color" value="${attr(v.color||'#547ee8')}"></label></div>
      <label>Description<textarea name="description" rows="2">${esc(v.description)}</textarea></label>
      <label>IPv4 subnets / IPv6 prefixes<textarea name="subnets" rows="3" placeholder="10.20.0.0/24&#10;2001:db8:20::/64">${esc((v.subnets||[]).join('\n'))}</textarea></label><p class="help">One subnet per line. Network addresses are normalized when saved.</p>
      <div class="field-row"><label>Address allocation<select name="dhcp_mode">${['unknown','dhcp','static','mixed'].map(k=>option(k,k,v.dhcp_mode||'unknown')).join('')}</select></label><label>Gateway interface<select name="gateway_interface_id"></select></label></div>
      <label>Notes<textarea name="notes" rows="2">${esc(v.notes)}</textarea></label></form>`,footer:'<button class="btn" data-cancel>Cancel</button><button class="btn btn-primary" data-save>Save VLAN</button>'});
    const f=formModal.body.querySelector('form');
    const gateways=()=>{const loc=f.elements.location_id.value;f.elements.gateway_interface_id.innerHTML=option('','Not recorded',v.gateway_interface_id??'')+catalog.interfaces.filter(i=>String(i.location_id??'')===loc).map(i=>option(i.id,`${i.device_name} · ${i.name}`,v.gateway_interface_id)).join('');};
    f.elements.location_id.onchange=gateways;gateways();
    const save=async()=>{if(!f.reportValidity())return;const data=Object.fromEntries(new FormData(f));data.tag=Number(data.tag);data.location_id=data.location_id?Number(data.location_id):null;data.gateway_interface_id=data.gateway_interface_id?Number(data.gateway_interface_id):null;data.subnets=data.subnets.split(/[\n,]+/).map(s=>s.trim()).filter(Boolean);const button=formModal.root.querySelector('[data-save]');button.disabled=true;
      try{await(v.id?api.put(`/api/clinics/${clinic.id}/vlans/${v.id}`,data):api.post(`/api/clinics/${clinic.id}/vlans`,data));toast('VLAN saved','success');formModal.close();await load();}catch(e){showFormError(f,e.message);}finally{button.disabled=false;}};
    formModal.root.querySelector('[data-save]').onclick=save;formModal.root.querySelector('[data-cancel]').onclick=()=>formModal.close();f.onsubmit=e=>{e.preventDefault();save();};
  };
  modal.root.querySelector('[data-close]').onclick=()=>modal.close();modal.root.querySelector('[data-add]').onclick=()=>edit();await load();
}
