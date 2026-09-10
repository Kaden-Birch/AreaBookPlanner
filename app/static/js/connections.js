import { api } from './api.js';
import { esc, attr, openModal, toast, showFormError } from './ui.js';

export async function openConnection({clinic,parent,child,onChanged}) {
  const url=`/api/clinics/${clinic.id}/connections/${parent}/${child}`;
  let data;
  try { data=await api.get(url); } catch(e) { toast(e.message,'error');return; }
  const d=data.details||{};
  const select=(name,label,options)=>`<label>${esc(label)}<select name="${name}">${options.map(([value,text])=>`<option value="${attr(value)}" ${String(d[name]??'')===String(value)?'selected':''}>${esc(text)}</option>`).join('')}</select></label>`;
  const choices=values=>values.map(v=>[v,v]);
  const modal=openModal({title:'Connection details',size:'modal-lg',body:`<p>${esc(data.source.name)} → ${esc(data.target.name)} · ${data.primary?'Primary':'Extra'} connection</p><p class="help">Documentation only, not live monitoring. Create interfaces in each device’s Network screen first. No credentials or secrets.</p><form>
    <div class="field-row">${select('source_interface_id',data.source.name+' interface',[['','Unknown port'],...data.source_interfaces.map(i=>[i.id,i.name])])}${select('target_interface_id',data.target.name+' interface',[['','Unknown port'],...data.target_interfaces.map(i=>[i.id,i.name])])}</div>
    <div class="field-row"><label>Link speed override (Mbps)<input name="speed_mbps" type="number" min="1" max="10000000" value="${attr(d.speed_override_mbps??'')}" placeholder="Automatic when endpoints are known"></label>${select('duplex','Duplex',choices(['unknown','full','half']))}${select('media','Media',choices(['unknown','copper','fiber','wireless','virtual','other']))}</div><p class="help" id="connection-speed-preview" role="status"></p>
    <div class="field-row">${select('vlan_mode','VLAN mode',choices(['unknown','access','trunk','routed']))}${select('native_vlan_id','Access / native VLAN',[['','Not recorded'],...data.vlans.map(v=>[v.id,`${v.tag} · ${v.name}`])])}</div>
    <fieldset><legend>Tagged VLANs (trunk mode only)</legend>${data.vlans.map(v=>`<label><input type="checkbox" name="tagged_vlans" value="${v.id}" ${d.tagged_vlans?.includes(v.id)?'checked':''}> ${v.tag} · ${esc(v.name)}</label>`).join('')||'<p>No VLANs recorded for these sites.</p>'}</fieldset>
    ${select('admin_status','Recorded administrative status',choices(['unknown','enabled','disabled']))}<label>Notes / purpose<textarea name="notes" rows="4" maxlength="10000">${esc(d.notes||'')}</textarea></label></form>`,footer:'<button class="btn" data-cancel>Cancel</button><button class="btn btn-primary" data-save>Save connection</button>'});
  const form=modal.body.querySelector('form'),button=modal.root.querySelector('[data-save]');
  const preview=()=>{
    const endpoints=[data.source_interfaces.find(i=>i.id===Number(form.elements.source_interface_id.value)),data.target_interfaces.find(i=>i.id===Number(form.elements.target_interface_id.value))];
    const speeds=i=>!i?[]:['sfp','sfp+','qsfp'].includes(i.connector)?(i.supported_speeds||[]).filter(s=>i.module_speeds?.includes(s)):i.supported_speeds||[];
    const shared=speeds(endpoints[0]).filter(s=>speeds(endpoints[1]).includes(s));
    const inferred=['virtual','wireless'].includes(form.elements.media.value)?null:Math.max(0,...shared);
    const override=Number(form.elements.speed_mbps.value)||null;
    const text=override?`${override} Mbps · override${endpoints.every(i=>speeds(i).length)&&!shared.includes(override)?' — conflicts with documented capabilities':''}`:inferred?`${inferred} Mbps · inferred highest shared capability`:'Unknown speed — document both endpoints and any required modules, or enter an override';
    const source=endpoints[0],target=endpoints[1];
    const name=id=>{const v=data.vlans.find(v=>v.id===id);return v?`${v.tag} · ${v.name}`:`VLAN ${id}`;};
    const upstream=source?.memberships||[],native=upstream.find(m=>['access','native'].includes(m.mode));
    const warnings=[];
    if(source&&target){const targetNative=target.memberships.find(m=>['access','native'].includes(m.mode));if(native&&targetNative&&native.vlan_id!==targetNative.vlan_id)warnings.push('Untagged/native VLANs disagree.');for(const m of target.memberships.filter(m=>m.mode==='tagged'))if(!upstream.some(s=>s.vlan_id===m.vlan_id&&s.mode==='tagged'))warnings.push(`${name(m.vlan_id)} is not documented as tagged upstream.`);}
    form.querySelector('#connection-speed-preview').textContent=text+'. Not a measured speed. '+(source?`Available upstream: ${upstream.map(m=>name(m.vlan_id)+' ('+m.mode+')').join(', ')||'not documented'}. `:'Upstream VLAN availability unknown. ')+warnings.join(' ');
  };
  form.addEventListener('change',preview);form.elements.speed_mbps.addEventListener('input',preview);preview();
  const save=async()=>{
    if(button.disabled||!form.reportValidity())return;
    const values=new FormData(form),payload=Object.fromEntries(values);
    for(const k of ['source_interface_id','target_interface_id','speed_mbps','native_vlan_id'])payload[k]=payload[k]?Number(payload[k]):null;
    payload.tagged_vlans=values.getAll('tagged_vlans').map(Number);button.disabled=true;
    try { await api.put(url,payload);modal.close();toast('Connection saved','success');onChanged?.(); }
    catch(e) { showFormError(form,e.message); } finally { button.disabled=false; }
  };
  button.onclick=save;form.onsubmit=e=>{e.preventDefault();save();};
  modal.root.querySelector('[data-cancel]').onclick=()=>modal.close();
}
