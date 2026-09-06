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
    <div class="field-row">${select('source_interface_id',data.source.name+' interface',[['','Not recorded'],...data.source_interfaces.map(i=>[i.id,i.name])])}${select('target_interface_id',data.target.name+' interface',[['','Not recorded'],...data.target_interfaces.map(i=>[i.id,i.name])])}</div>
    <div class="field-row"><label>Speed (Mbps)<input name="speed_mbps" type="number" min="1" max="10000000" value="${attr(d.speed_mbps??'')}"></label>${select('duplex','Duplex',choices(['unknown','full','half']))}${select('media','Media',choices(['unknown','copper','fiber','wireless','virtual','other']))}</div>
    <div class="field-row">${select('vlan_mode','VLAN mode',choices(['unknown','access','trunk','routed']))}${select('native_vlan_id','Access / native VLAN',[['','Not recorded'],...data.vlans.map(v=>[v.id,`${v.tag} · ${v.name}`])])}</div>
    <fieldset><legend>Tagged VLANs (trunk mode only)</legend>${data.vlans.map(v=>`<label><input type="checkbox" name="tagged_vlans" value="${v.id}" ${d.tagged_vlans?.includes(v.id)?'checked':''}> ${v.tag} · ${esc(v.name)}</label>`).join('')||'<p>No VLANs recorded for these sites.</p>'}</fieldset>
    ${select('admin_status','Recorded administrative status',choices(['unknown','enabled','disabled']))}<label>Notes / purpose<textarea name="notes" rows="4" maxlength="10000">${esc(d.notes||'')}</textarea></label></form>`,footer:'<button class="btn" data-cancel>Cancel</button><button class="btn btn-primary" data-save>Save connection</button>'});
  const form=modal.body.querySelector('form'),button=modal.root.querySelector('[data-save]');
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
