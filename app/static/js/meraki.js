import {api} from './api.js';
import {esc,attr,openModal,toast,navigate,confirmDialog} from './ui.js';

export async function merakiSettings(container){
  const clinics=await api.get('/api/clinics');
  const card=document.createElement('section');card.className='card mb';
  card.innerHTML=`<h2>Meraki · clinic-specific connections</h2><p>Each clinic has its own read-only API key. Choose a clinic to manage its key and map Meraki networks to its sites. No shared Meraki key is used.</p><label>Clinic<select data-clinic><option value="">Choose a clinic</option>${clinics.map(c=>`<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select></label><button class="btn" data-open>Set up / import Meraki</button>`;
  (container.querySelector('section[aria-label="AI & integrations"]')||container).append(card);
  card.querySelector('[data-open]').onclick=()=>{const cid=Number(card.querySelector('[data-clinic]').value);if(cid)importMeraki(cid);else toast('Choose a clinic first.','error');};
}

export async function importMeraki(cid){
  const modal=openModal({title:'Meraki · clinic connection',size:'modal-lg',body:'Loading…',footer:'<button class="btn" data-close>Close</button>'});
  modal.root.querySelector('[data-close]').onclick=()=>modal.close();
  try{
    const [config,clinic,locations]=await Promise.all([api.get(`/api/meraki/clinics/${cid}/settings`),api.get(`/api/clinics/${cid}`),api.get(`/api/clinics/${cid}/locations`)]);
    modal.body.innerHTML=`<h3>${esc(clinic.name)}</h3><p>This key is used only for this clinic and its mapped sites. Use a dedicated Meraki Dashboard account with read-only access to the intended networks and enable Dashboard API access. AreaBook only sends GET requests.</p>
      <details ${config.configured?'':'open'}><summary>Clinic API key · ${config.configured?'saved':'not configured'}</summary><label>API key<input type="password" data-key autocomplete="off" placeholder="${config.configured?'Saved — leave blank to keep':'Enter clinic API key'}"></label><div class="actions"><button class="btn" data-save>Save clinic key</button><button class="btn" data-remove>Remove clinic key</button></div><p>The key is stored server-side. Protect the database and backups.</p></details>
      <button class="btn" data-test>Test key & load organizations</button><p role="status"></p><div data-select></div><div data-review></div>`;
    const q=s=>modal.body.querySelector(s),status=q('[role=status]');
    async function run(button,fn){button.disabled=true;try{await fn();}catch(e){status.textContent=e.message;}finally{button.disabled=false;}}
    function clear(){q('[data-select]').innerHTML='';q('[data-review]').innerHTML='';}
    q('[data-save]').onclick=e=>run(e.target,async()=>{const key=q('[data-key]').value.trim();if(!key){status.textContent='Enter a key to replace it; leave blank to keep the saved key.';return;}await api.put(`/api/meraki/clinics/${cid}/settings`,{api_key:key});q('[data-key]').value='';clear();status.textContent='Clinic key saved. Test it to choose an organization and network.';});
    q('[data-remove]').onclick=e=>run(e.target,async()=>{if(!await confirmDialog('Remove only this clinic’s Meraki key? Imported documentation stays intact; refreshes cannot run without a key.'))return;await api.put(`/api/meraki/clinics/${cid}/settings`,{api_key:''});q('[data-key]').value='';clear();status.textContent='Clinic key removed.';});
    q('[data-test]').onclick=e=>run(e.target,async()=>{
      clear();status.textContent='Reading organizations using this clinic’s saved key…';
      const orgs=await api.get(`/api/meraki/clinics/${cid}/organizations`);
      if(!orgs.length){status.textContent='No organizations visible to this key.';return;}
      status.textContent='Key accepted. Select the organization, network and matching local site.';
      q('[data-select]').innerHTML=`<label>Meraki organization<select data-org>${orgs.map(o=>`<option value="${attr(o.id)}">${esc(o.name)}</option>`).join('')}</select></label><label>Meraki network<select data-network></select></label><label>AreaBook site<select data-location><option value="">Main Site</option>${locations.map(l=>`<option value="${l.id}">${esc(l.name)}</option>`).join('')}</select></label><button class="btn btn-primary" data-preview>Build import preview</button>`;
      let networks=[];
      function mapping(){q('[data-review]').innerHTML='';const link=networks.find(n=>n.id===q('[data-network]').value)?.link;q('[data-location]').value=link?.location_id||'';q('[data-location]').disabled=Boolean(link);}
      async function load(){networks=[];q('[data-review]').innerHTML='';q('[data-preview]').disabled=true;q('[data-org]').disabled=true;q('[data-network]').innerHTML='';try{networks=await api.get(`/api/meraki/clinics/${cid}/networks`,{organization_id:q('[data-org]').value});q('[data-network]').innerHTML=networks.map(n=>`<option value="${attr(n.id)}">${esc(n.name)}${n.link?' · linked':''}</option>`).join('');mapping();status.textContent=networks.length?'Choose the correct site, then build a preview.':'No networks accessible in this organization.';}catch(e){status.textContent=e.message;}finally{q('[data-org]').disabled=false;q('[data-preview]').disabled=!networks.length;}}
      q('[data-org]').onchange=load;q('[data-network]').onchange=mapping;q('[data-location]').onchange=()=>q('[data-review]').innerHTML='';
      q('[data-preview]').onclick=e=>run(e.target,async()=>{
        const payload={clinic_id:cid,organization_id:q('[data-org]').value,network_id:q('[data-network]').value,location_id:Number(q('[data-location]').value)||null};
        q('[data-review]').innerHTML='';status.textContent='Reading inventory, ports and network observations. This can take up to four minutes…';
        const controls=[q('[data-org]'),q('[data-network]'),q('[data-location]'),q('[data-test]'),q('[data-save]'),q('[data-remove]')];controls.forEach(c=>c.disabled=true);
        try{const draft=await api.post('/api/meraki/preview',payload);review(draft,q('[data-review]'),status,modal);}finally{controls.forEach(c=>c.disabled=false);q('[data-location]').disabled=Boolean(networks.find(n=>n.id===payload.network_id)?.link);}
      });
      await load();
    });
  }catch(e){modal.body.textContent=e.message;}
}

function review(draft,container,status,modal){
  const machines=draft.records.filter(r=>r.proposal);
  status.textContent='Preview ready — nothing imported yet.';
  container.innerHTML=`<h3>Review ${esc(draft.site_name)}</h3><p>${machines.length} machines. Unique MAC matches reuse existing records; IP/name-only similarities need review. Existing device names, VM types, interfaces and wiring are preserved.</p><p>Clients were observed in the last 24 hours, not necessarily online now. Reported adapters are not assumed to be physical ports. Public IPv4 and APIPA are excluded; eligible IPv6 addresses are retained.</p>
    ${draft.warnings.map(w=>`<p class="text-muted">${esc(w)}</p>`).join('')}
    ${machines.map((r,i)=>`<details class="card mb"><summary>${esc(r.name)} · ${esc(r.proposal.action)} · ${esc(r.mac||'MAC unknown')}</summary><p>${esc(r.proposal.reason)}</p><p>IP: ${esc(r.addresses.map(a=>a.address).join(', ')||'No eligible address')} · ${esc(r.state||'State unknown')} · ${r.ports.length} ports</p><p>Reported attachment: ${esc(r.uplink||'Unknown')} · port ${esc(r.uplink_port||'unknown')} · VLAN ${esc(r.vlan||'unknown')}</p><label>Decision<select data-choice="${i}"><option value="skip" ${r.proposal.action==='skip'?'selected':''}>Skip local changes</option><option value="create" ${r.proposal.action==='create'?'selected':''}>Create device</option>${draft.choices.map(d=>`<option value="${d.id}" ${r.proposal.action==='match'&&r.proposal.device_id===d.id?'selected':''}>Match ${esc(d.name)} (#${d.id})</option>`).join('')}</select></label><details><summary>All collected details</summary><pre style="white-space:pre-wrap">${esc(JSON.stringify(r,null,2))}</pre></details></details>`).join('')}
    <details><summary>VLAN, VPN and LLDP/CDP observations</summary><pre style="white-space:pre-wrap">${esc(JSON.stringify(draft.records.filter(r=>!r.proposal),null,2))}</pre></details>
    <label><input type="checkbox" data-vlans checked> Add missing VLANs/subnets. Existing VLAN definitions and memberships stay unchanged.</label><label><input type="checkbox" data-uplinks> Fill missing uplinks from online clients with explicit attachment reports. VM hosts and existing wiring stay unchanged; exact port assignments remain observations.</label>
    <p>Switch ports are added on new switches only. Port configuration, VPN and undirected LLDP/CDP links remain source observations for review, not automatic local configuration.</p><button class="btn btn-primary" data-confirm>Confirm import into AreaBook</button>`;
  container.querySelector('[data-confirm]').onclick=async e=>{
    e.target.disabled=true;
    const decisions=machines.map((r,i)=>{const v=container.querySelector(`[data-choice="${i}"]`).value;return {kind:r.kind,id:r.id,action:['skip','create'].includes(v)?v:'match',device_id:Number(v)||null};});
    try{const result=await api.post('/api/meraki/import',{token:draft.token,decisions,import_networks:container.querySelector('[data-vlans]').checked,import_uplinks:container.querySelector('[data-uplinks]').checked});modal.close();toast(`Meraki: ${result.created} created, ${result.matched} matched, ${result.vlans_added} VLANs added.`,'success');navigate('#/clinics/'+result.clinic_id);}catch(error){status.textContent=error.message;e.target.disabled=false;}
  };
}

export async function merakiClinic(container,cid){
  const user=await api.get('/api/auth/me');const admin=user.roles.includes('admin');if(!admin&&user.active_role!=='it')return;
  const data=await api.get(`/api/meraki/clinics/${cid}`);if(!container.isConnected||(!admin&&!data.sites.length))return;
  const card=document.createElement('section');card.className='card mb';
  card.innerHTML=`<h2>Meraki network observations</h2><p>Clinic-specific read-only connection. Snapshots do not prove current reachability; missing devices are never deleted automatically.</p>${admin?'<button class="btn" data-setup>Set up / import Meraki</button>':''}${data.sites.map(s=>`<details><summary>${esc(s.name)} · ${esc(s.updated_at)} UTC</summary>${JSON.parse(s.warnings).map(w=>`<p>${esc(w)}</p>`).join('')}${data.records.filter(r=>r.network_id===s.network_id).map(r=>`<details><summary>${esc(r.data.name)} · ${esc(r.data.kind)}${r.local_id?' · linked #'+r.local_id:''}</summary><p>Last observation: ${esc(r.updated_at)} UTC</p><pre style="white-space:pre-wrap">${esc(JSON.stringify(r.data,null,2))}</pre></details>`).join('')}</details>`).join('')}`;
  container.append(card);if(admin)card.querySelector('[data-setup]').onclick=()=>importMeraki(cid);
}
