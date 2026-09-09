import {api,devices} from './api.js';
import {esc,attr,openModal,showFormError} from './ui.js';

export async function editTopologyGroup(clinicId,group,onChanged) {
  const {sites}=await devices.sites(clinicId);
  const data=await devices.topology(clinicId,'all');
  const nodes=[...data.nodes,...data.offsite];
  const modal=openModal({title:group?'Edit logical group':'New logical group',body:`<p>Groups organize documentation; they do not change connections. Devices must belong to one site.</p><form>
    <label>Name<input name="name" required maxlength="100" value="${attr(group?.name||'')}"></label>
    <label>Description<textarea name="description" maxlength="10000">${esc(group?.description||'')}</textarea></label>
    <label>Colour<input name="color" type="color" value="${attr(group?.color||'#547ee8')}"></label>
    <label>Site<select name="site">${sites.map(s=>`<option value="${attr(s.id)}" ${String(s.id)===String(group?.location_id??'main')?'selected':''}>${esc(s.name)}</option>`).join('')}</select></label>
    <fieldset><legend>Devices</legend><div data-members style="max-height:260px;overflow:auto"></div></fieldset>
    <button class="btn btn-primary" type="submit">Save group</button></form>`,footer:'<button class="btn" data-close>Cancel</button>'});
  const form=modal.body.querySelector('form'),members=form.querySelector('[data-members]');
  const render=()=>{const loc=form.elements.site.value;members.innerHTML=nodes.filter(n=>String(n.location_id??'main')===loc).map(n=>`<label><input type="checkbox" value="${n.id}" ${group?.device_ids.includes(n.id)?'checked':''}> ${esc(n.name)}</label>`).join('')||'<p>No logical devices at this site.</p>';};
  form.elements.site.onchange=render;render();
  form.onsubmit=async e=>{e.preventDefault();const button=form.querySelector('[type=submit]');button.disabled=true;
    try{await api.put(`/api/clinics/${clinicId}/topology/groups/${group?.id||0}`,{name:form.elements.name.value,description:form.elements.description.value,color:form.elements.color.value,location_id:form.elements.site.value==='main'?null:Number(form.elements.site.value),device_ids:[...members.querySelectorAll('input:checked')].map(c=>Number(c.value))});modal.close();onChanged();}
    catch(error){showFormError(form,error.message);}finally{button.disabled=false;}
  };
  modal.root.querySelector('[data-close]').onclick=()=>modal.close();
}
