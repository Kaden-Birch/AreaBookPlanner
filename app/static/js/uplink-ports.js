import {api} from './api.js';
import {esc} from './ui.js';

export function attachUplinkPorts(form,clinic,device) {
  const uplink=form.querySelector('#dev-uplink'),host=document.createElement('div');host.className='field-row';uplink.closest('.field').after(host);
  let revision=0,ready=false;
  const load=async(initial=false)=>{
    const current=++revision;ready=false;host.innerHTML='';
    if(!uplink.value){ready=true;return;}
    host.textContent='Loading port choices…';
    try{
      const parent=Number(uplink.value);
      const [source,target,connection]=await Promise.all([api.get(`/api/devices/${parent}/network`),device?.id?api.get(`/api/devices/${device.id}/network`):Promise.resolve({interfaces:[],connections:[]}),initial&&device?.id&&parent===device.uplink_id?api.get(`/api/clinics/${clinic.id}/connections/${parent}/${device.id}`):Promise.resolve(null)]);
      if(current!==revision)return;
      const choices=(data,selected)=>'<option value="">Unknown port</option>'+data.interfaces.map(i=>{const used=data.connections.some(c=>(c.source_interface_id===i.id||c.target_interface_id===i.id)&&!(c.uplink_id===parent&&c.device_id===device?.id)&&!['wireless','virtual'].includes(c.media));return `<option value="${i.id}" ${i.id===selected?'selected':''} ${used?'disabled':''}>${esc(i.name)} · ${i.supported_speeds?.length?Math.max(...i.supported_speeds)+' Mbps max':'speed unknown'} · ${used?'In use':i.memberships.length+' VLAN memberships'}</option>`;}).join('');
      host.innerHTML=`<label>Uplink port<select name="uplink_port_id">${choices(source,connection?.details?.source_interface_id)}</select></label><label>This device’s interface<select name="device_port_id">${choices(target,connection?.details?.target_interface_id)}</select></label><p class="help">Unknown port preserves the device-level relationship. Used physical ports must be disconnected before reassignment. Configure ports from device details.</p>`;ready=true;
    }catch(e){if(current===revision){host.textContent=`Could not load ports: ${e.message}. Change the uplink selection to retry.`;}}
  };
  uplink.addEventListener('change',()=>load());load(true);
  return ()=>ready;
}
