import {api} from './api.js';
import {esc,openModal,toast,confirmDialog} from './ui.js';
import {saveNetwork} from './network.js';

// Add tagged/routed memberships without removing existing trunk documentation.
export function assignMembership(interfaces,indices,vlanId,mode) {
  const result=structuredClone(interfaces);
  for(const index of indices) {
    const i=result[index];
    if(i.memberships.some(m=>m.vlan_id===vlanId))continue;
    if(mode==='access'||mode==='native') {
      const replaced=i.memberships.filter(m=>['access','native'].includes(m.mode)).map(m=>m.vlan_id);
      i.memberships=i.memberships.filter(m=>!replaced.includes(m.vlan_id));
      for(const a of i.addresses)if(replaced.includes(a.vlan_id))a.vlan_id=vlanId;
    }
    i.memberships.push({vlan_id:vlanId,mode});
  }
  return result;
}

export async function assignDeviceVlan(deviceId,vlan,catalog) {
  const original=await api.get(`/api/devices/${deviceId}/network`);
  if(original.location_id!==vlan.location_id){toast('Choose a VLAN belonging to this device’s site.','error');return null;}
  let rows=structuredClone(original.interfaces);
  if(!rows.length)rows=[{name:'Port 1',mac_address:original.legacy_mac||null,addresses:original.legacy_ip?[{address:original.legacy_ip,is_primary:true}]:[],memberships:[]}];
  const apply=async(indices,mode)=>{
    if(indices.every(index=>rows[index].memberships.some(m=>m.vlan_id===vlan.id))){toast('Already assigned');return null;}
    const replacing=indices.some(index=>rows[index].memberships.some(m=>m.vlan_id!==vlan.id&&['access','native'].includes(m.mode)))&&['access','native'].includes(mode);
    if(replacing&&!await confirmDialog('Replace the selected interfaces’ access/native VLAN? Explicit addresses on that membership will follow the new VLAN and be checked. Tagged and routed memberships are retained.',{okLabel:'Replace VLAN',danger:false}))return null;
    return saveNetwork(deviceId,{interfaces:assignMembership(rows,indices,vlan.id,mode),expected_interfaces:original.interfaces});
  };
  if(rows.length===1&&!rows[0].memberships.length)return apply([0],'access');
  return new Promise(resolve=>{
    const modal=openModal({title:`Assign VLAN ${vlan.tag} · ${vlan.name}`,body:`<p>Select interfaces. Existing memberships and addresses are shown below.</p><form>${rows.map((i,index)=>`<label class="card"><input type="checkbox" name="interface" value="${index}"> <strong>${esc(i.name)}</strong><br>${esc(i.addresses.map(a=>a.address).join(', ')||'No IP addresses')}<br>${esc(i.memberships.map(m=>{const v=catalog.find(v=>v.id===m.vlan_id);return `${v?.tag??m.vlan_id} · ${v?.name||'VLAN'} (${m.mode})`;}).join(', ')||'No VLAN assigned')}</label>`).join('')}<label>Membership action<select name="mode"><option value="tagged">Add tagged membership — retain existing VLANs</option><option value="access">Assign / replace access VLAN</option><option value="native">Assign / replace native VLAN</option><option value="routed">Add routed membership</option></select></label></form><p class="help">Documentation only — does not configure the physical device.</p>`,footer:'<button class="btn" data-cancel>Cancel</button><button class="btn btn-primary" data-apply>Apply VLAN</button>',onClose:()=>resolve(null)});
    modal.root.querySelector('[data-cancel]').onclick=()=>modal.close();
    modal.root.querySelector('[data-apply]').onclick=async()=>{
      const indices=[...modal.body.querySelectorAll('input:checked')].map(el=>Number(el.value));
      if(!indices.length){toast('Select at least one interface.');return;}
      const button=modal.root.querySelector('[data-apply]');button.disabled=true;
      try{const result=await apply(indices,modal.body.querySelector('select').value);if(result){resolve(result);modal.close();}}catch(e){toast(e.message,'error');}finally{button.disabled=false;}
    };
  });
}
