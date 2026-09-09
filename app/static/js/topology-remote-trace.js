import {api,clinics,devices} from './api.js';
import {esc,attr,openModal,showFormError} from './ui.js';

export async function openRemoteTrace(clinicId,nodes) {
  const list=await clinics.list();
  const modal=openModal({title:'Cross-site documented path',size:'modal-lg',body:`<p>Trace local devices and explicitly documented VPN transit. This is not live monitoring or proof of IP reachability.</p><form>
    <label>Source device<select name="source">${nodes.map(n=>`<option value="${n.id}">${esc(n.name)} · ${esc(n.location_name||'Main site')}</option>`).join('')}</select></label>
    <label>Destination clinic<select name="clinic">${list.map(c=>`<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select></label>
    <label>Destination site<select name="site"></select></label><label>Destination device / service<select name="device"></select></label>
    <button type="submit" class="btn btn-primary">Trace documented path</button></form><div data-result aria-live="polite"></div>`,footer:'<button class="btn" data-close>Close</button>'});
  const form=modal.body.querySelector('form'),result=modal.body.querySelector('[data-result]');
  let revision=0,loading=false,selectionRevision=0;
  const loadSites=async()=>{
    revision++;const rev=++selectionRevision;loading=true;result.innerHTML='';form.elements.site.innerHTML='';form.elements.device.innerHTML='';
    try{const data=await devices.sites(Number(form.elements.clinic.value));if(rev!==selectionRevision)return;
      form.elements.site.innerHTML=data.sites.map(s=>`<option value="${attr(s.id)}">${esc(s.name)}</option>`).join('');await loadDevices();
    }catch(e){if(rev===selectionRevision)showFormError(form,e.message);}
  };
  const loadDevices=async()=>{
    revision++;const rev=++selectionRevision;
    const cid=form.elements.clinic.value,site=form.elements.site.value;loading=true;form.elements.device.innerHTML='';result.innerHTML='';
    try{const data=await devices.topology(Number(cid),site);if(rev!==selectionRevision)return;
      const all=[...data.nodes,...data.offsite];form.elements.device.innerHTML='<option value="">Site VPN termination only</option>'+all.map(n=>`<option value="${n.id}">${esc(n.name)}</option>`).join('')+all.flatMap(n=>(n.services||[]).map(s=>`<option value="${n.id}">${esc(s.name)} (host: ${esc(n.name)})</option>`)).join('');
      loading=false;
    }catch(e){if(rev===selectionRevision)showFormError(form,e.message);}
  };
  form.elements.clinic.onchange=loadSites;form.elements.site.onchange=loadDevices;
  form.onsubmit=async e=>{e.preventDefault();if(loading)return;const button=form.querySelector('button');button.disabled=true;
    const rev=++revision;
    try{const query={source_device_id:form.elements.source.value,destination_clinic_id:form.elements.clinic.value,destination_site:form.elements.site.value};if(form.elements.device.value)query.destination_device_id=form.elements.device.value;
      const data=await api.get(`/api/clinics/${clinicId}/topology/trace`,query);if(rev!==revision)return;
      result.innerHTML=`<p>${esc(data.notice)}</p>`+(data.routes.length?data.routes.map((route,index)=>`<section class="card"><h3>Path ${index+1} · ${route.relationship==='via'?'Explicit onward transit':route.relationship==='direct'?'Direct VPN':'Local site'}</h3><p>${route.documentation_complete?'Local connection chains documented':'Incomplete local documentation'} — reachability unverified</p>${route.rationale?`<p>${esc(route.rationale)}</p>`:''}
        <ol class="remote-trace">${route.segments.map(segment=>segment.kind==='vpn'?`<li class="remote-trace-vpn ${route.relationship==='via'?'transit':'direct'} recorded-${attr(segment.status)}"><strong>VPN: ${esc(segment.name||'Unnamed tunnel')}</strong><p>${esc(segment.from.clinic_name)} · ${esc(segment.from.site_name)} → ${esc(segment.to.clinic_name)} · ${esc(segment.to.site_name)}</p><p>Recorded ${esc(segment.status)} · not a live check</p><p>${esc(segment.notes||'No tunnel notes recorded')}</p><p>Local subnets: ${esc(segment.local_subnets.join(', ')||'Undocumented')}<br>Remote subnets: ${esc(segment.remote_subnets.join(', ')||'Undocumented')}</p><p class="help">Subnet presence does not establish forwarding permission.</p></li>`:
          `<li>${segment.warning?`<p class="help">${esc(segment.warning)}</p>`:''}<div class="remote-trace-chain">${segment.nodes.map(n=>`<a class="btn btn-sm" href="#/clinics/${segment.clinic_id}/equipment?view=topology&site=${attr(segment.site)}&device=${n.id}" data-device-link>${esc(n.name)}</a>`).join('<span aria-hidden="true"> → </span>')}</div>${segment.links.length?`<details><summary>Interfaces, VLANs and connection evidence</summary>${segment.links.map(link=>`<p>${esc(segment.nodes.find(n=>n.id===link.from)?.name)} → ${esc(segment.nodes.find(n=>n.id===link.to)?.name)}: ${esc(link.assessment)}<br>${esc(link.details.source_interface_name||'Unknown interface')} ↔ ${esc(link.details.target_interface_name||'Unknown interface')} · ${esc(link.details.speed_mbps||'Unknown')} Mbps · ${esc(link.details.admin_status||'unknown')}<br><strong>${esc(link.vlan_boundary)}</strong><br>Documented interface VLANs: ${esc(link.source_vlans.join(', ')||'unknown')} ↔ ${esc(link.destination_vlans.join(', ')||'unknown')}</p>`).join('')}</details>`:''}</li>`).join('')}</ol></section>`).join(''):'<p>No direct or explicitly permitted onward VPN path is documented for this source. Disabled tunnels are excluded. This does not prove unreachability.</p>')+(data.truncated?'<p>Showing the first 50 documented paths.</p>':'');
      result.querySelectorAll('[data-device-link]').forEach(a=>a.onclick=()=>modal.close());
    }catch(error){showFormError(form,error.message);}finally{button.disabled=false;}
  };
  form.elements.source.onchange=()=>{revision++;result.innerHTML='';};
  form.elements.device.onchange=()=>{revision++;result.innerHTML='';};
  modal.root.querySelector('[data-close]').onclick=()=>modal.close();
  await loadSites();
}
