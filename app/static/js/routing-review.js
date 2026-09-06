import { api, devices } from './api.js';
import { esc, attr, openModal, toast, showFormError } from './ui.js';
import { openRangesManager, openVpnPanel } from './vpn.js';

export async function openRoutingReview({clinic,site}) {
  let sites;
  try { sites=(await devices.sites(clinic.id)).sites; } catch(e) { toast(e.message,'error');return; }
  const selected=!site||site==='all'?'main':String(site);
  const modal=openModal({title:'VPN IP path review',size:'modal-lg',body:`<p>Choose the source site and two host IP addresses. Review documented paths without changing any configuration.</p><form>
    <label>Source site<select name="site">${sites.map(s=>`<option value="${attr(s.id)}" ${String(s.id)===selected?'selected':''}>${esc(s.name)}</option>`).join('')}</select></label>
    <div class="field-row"><label>Source IP<input name="source_ip" required maxlength="45" placeholder="10.20.0.10 or 2001:db8::10"></label><label>Destination IP<input name="destination_ip" required maxlength="45" placeholder="10.30.0.10 or 2001:db8:1::10"></label></div>
    <button class="btn btn-primary" type="submit">Review path</button></form><div id="ip-review-result" aria-live="polite"></div>`,
    footer:'<button class="btn" data-ranges>Source network ranges</button><button class="btn" data-vpn>VPN links & onward access</button><button class="btn" data-close>Close</button>'});
  const form=modal.body.querySelector('form'),result=modal.body.querySelector('#ip-review-result');
  let revision=0;
  form.oninput=()=>{revision++;result.innerHTML='';};
  form.onsubmit=async e=>{
    e.preventDefault();const button=form.querySelector('button');if(button.disabled||!form.reportValidity())return;
    button.disabled=true;result.innerHTML='';const requestRevision=revision;
    try {
      const query=new URLSearchParams(new FormData(form));
      const data=await api.get(`/api/clinics/${clinic.id}/connectivity/ip-review?${query}`);
      if(requestRevision!==revision)return;
      result.innerHTML=`<h3>${esc(data.source_site.clinic_name)} · ${esc(data.source_site.site_name)}</h3><p><strong>Reachability unverified</strong> · ${esc(data.source_ip)} → ${esc(data.destination_ip)}</p>
        <p>Source networks: ${data.source_matches.map(r=>esc(r.cidr)).join(', ')||'Not documented'}</p>
        ${data.warnings.map(w=>`<p class="warn">⚠ ${esc(w)}</p>`).join('')}
        ${data.candidates.map(c=>`<section class="card"><h4>${esc(c.destination.clinic_name)} · ${esc(c.destination.site_name)}</h4><p>${c.kind==='local'?'Same-site address match — no VPN path required':c.kind==='direct'?'Direct VPN path documented':'Onward VPN path explicitly documented'}</p><p>Destination networks: ${c.matched_ranges.map(r=>esc(r.cidr)).join(', ')}</p>
        <ol>${c.hops.map(h=>`<li>${esc(h.from)} → ${esc(h.to)}<br>${esc(h.name||'VPN tunnel')} · recorded status: ${esc(h.status)}</li>`).join('')}</ol>
        ${c.kind==='local'?'':`<p>Return site path: ${c.return_path_documented?'documented (subnet permission still unverified)':'not documented'}</p>`}</section>`).join('')}
        <p class="muted">${esc(data.limitations)}</p>`;
    } catch(error){showFormError(form,error.message);} finally{button.disabled=false;}
  };
  const current=()=>form.elements.site.value;
  modal.root.querySelector('[data-ranges]').onclick=()=>openRangesManager({clinic,site:current()});
  modal.root.querySelector('[data-vpn]').onclick=()=>openVpnPanel({clinic,site:current()});
  modal.root.querySelector('[data-close]').onclick=()=>modal.close();
}
