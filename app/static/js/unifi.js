import {api} from './api.js';
import {esc,attr,openModal,toast,navigate,confirmDialog} from './ui.js';

export async function unifiSettings(container){
  const config=await api.get('/api/unifi/settings');
  const card=document.createElement('section');card.className='card mb';
  card.innerHTML=`<h2>UniFi · shared read-only connection</h2><p>One Site Manager API key for all accessible consoles and sites. AreaBook never sends configuration changes to UniFi.</p>
    <p>Create a key at <a href="https://unifi.ui.com" target="_blank" rel="noopener noreferrer">unifi.ui.com</a>. Use an organization key for organization-wide access, or an owner key for consoles you own. Cloud connector requires compatible consoles on firmware 5.0.3+ and a supported Network application.</p>
    <label>Shared API key<input type="password" name="unifi-key" autocomplete="off" placeholder="${config.configured?'Saved — enter only to replace':'Enter Site Manager API key'}"></label>
    <div class="actions"><button class="btn" data-save>Save key</button><button class="btn" data-test>Test saved connection</button><button class="btn" data-import>Import from UniFi</button><button class="btn" data-remove>Remove key</button></div><p role="status"></p>`;
  (container.querySelector('section[aria-label="AI & integrations"]')||container).append(card);
  const status=card.querySelector('[role=status]');
  async function run(button,fn){button.disabled=true;try{await fn();}catch(e){status.textContent=e.message;}finally{button.disabled=false;}}
  card.querySelector('[data-save]').onclick=e=>run(e.target,async()=>{
    const input=card.querySelector('[name=unifi-key]');if(!input.value.trim()){status.textContent='Enter a key to save or replace it.';return;}
    await api.put('/api/unifi/settings',{api_key:input.value.trim()});input.value='';input.placeholder='Saved — enter only to replace';status.textContent='Shared key saved. Test the connection, then choose a console and map its site to a clinic.';
  });
  card.querySelector('[data-test]').onclick=e=>run(e.target,async()=>{status.textContent='Reading Site Manager…';const hosts=await api.get('/api/unifi/hosts');status.textContent=`Connected: ${hosts.length} consoles visible. Import checks Network access separately for the selected console.`;});
  card.querySelector('[data-remove]').onclick=e=>run(e.target,async()=>{if(!await confirmDialog('Remove the shared UniFi key for all users? Imported documentation remains.'))return;await api.put('/api/unifi/settings',{api_key:''});card.querySelector('[name=unifi-key]').value='';status.textContent='Key removed. Existing imports are preserved.';});
  card.querySelector('[data-import]').onclick=()=>importUnifi();
}

export async function importUnifi(initialClinic=null){
  const modal=openModal({title:'Import from UniFi',size:'modal-lg',body:'Reading consoles…',footer:'<button class="btn" data-close>Close</button>'});
  modal.root.querySelector('[data-close]').onclick=()=>modal.close();
  try{
    const [hosts,clinics]=await Promise.all([api.get('/api/unifi/hosts'),api.get('/api/clinics')]);
    if(!hosts.length){modal.body.textContent='No consoles visible to this key. Check the key owner or organization access in Site Manager.';return;}
    modal.body.innerHTML=`<p>1. Choose a console and UniFi site. 2. Map it to an existing AreaBook clinic/site. 3. Review before importing. Nothing changes in UniFi.</p>
      <label>UniFi console<select name="host">${hosts.map(h=>`<option value="${attr(h.id)}">${esc(h.name)}${h.blocked?' (cloud access blocked)':''}</option>`).join('')}</select></label>
      <label>UniFi site<select name="remote"></select></label>
      <label>AreaBook clinic<select name="clinic"><option value="">Select a clinic</option>${clinics.map(c=>`<option value="${c.id}" ${c.id===initialClinic?'selected':''}>${esc(c.name)} · ${esc(c.city||'')}</option>`).join('')}</select></label>
      <label>AreaBook site<select name="location"><option value="">Main Site</option></select></label>
      <button class="btn btn-primary" data-preview>Build preview</button><p role="status"></p><div data-review></div>`;
    const q=s=>modal.body.querySelector(s),status=q('[role=status]');let remoteSites=[],request=0;
    function lock(value){['host','remote','clinic','location'].forEach(name=>q(`[name=${name}]`).disabled=value);q('[data-preview]').disabled=value;}
    async function change(fn){invalidate();lock(true);try{await fn();}catch(e){status.textContent=e.message;}finally{lock(false);}}
    async function locations(){const cid=q('[name=clinic]').value;const rows=cid?await api.get(`/api/clinics/${cid}/locations`):[];q('[name=location]').innerHTML='<option value="">Main Site</option>'+rows.map(s=>`<option value="${s.id}">${esc(s.name)}</option>`).join('');}
    async function applyLink(){const site=remoteSites.find(s=>s.id===q('[name=remote]').value);if(site?.link){q('[name=clinic]').value=site.link.clinic_id;await locations();q('[name=location]').value=site.link.location_id||'';status.textContent='Existing mapping loaded. Reimport preserves local documentation.';}}
    function invalidate(){q('[data-review]').innerHTML='';request++;}
    async function loadSites(){await change(async()=>{status.textContent='Reading Network sites…';q('[name=remote]').innerHTML='';remoteSites=await api.get('/api/unifi/sites',{host_id:q('[name=host]').value});q('[name=remote]').innerHTML=remoteSites.map(s=>`<option value="${attr(s.id)}">${esc(s.name)}${s.link?' · linked':''}</option>`).join('');status.textContent=remoteSites.length?'Choose the matching clinic/site.':'No Network sites found.';await applyLink();});}
    q('[name=host]').onchange=loadSites;
    q('[name=remote]').onchange=()=>change(applyLink);
    q('[name=clinic]').onchange=()=>change(locations);
    q('[name=location]').onchange=invalidate;
    q('[data-preview]').onclick=async e=>{
      if(!q('[name=clinic]').value||!q('[name=remote]').value){status.textContent='Choose a UniFi site and an AreaBook clinic first.';return;}
      lock(true);const version=++request;status.textContent='Reading inventory and details. This can take up to 90 seconds…';q('[data-review]').innerHTML='';
      try{const draft=await api.post('/api/unifi/preview',{host_id:q('[name=host]').value,site_id:q('[name=remote]').value,clinic_id:Number(q('[name=clinic]').value),location_id:Number(q('[name=location]').value)||null});if(version!==request)return;review(draft,q('[data-review]'),status,modal);}catch(error){status.textContent=error.message;}finally{lock(false);}
    };
    await locations();await loadSites();
  }catch(e){modal.body.textContent=e.message;}
}

function review(draft,container,status,modal){
  const machines=draft.records.filter(r=>r.proposal),networks=draft.records.filter(r=>r.kind==='networks'),vpns=draft.records.filter(r=>r.kind==='vpn');
  status.textContent='Preview ready. Nothing imported yet.';
  container.innerHTML=`<h3>Review ${esc(draft.site_name)}</h3><p>${machines.length} devices/clients · ${networks.length} networks · ${vpns.length} VPN descriptions</p>
    <p>Unique MAC matches reuse existing machines, including Syncro imports. IP/name-only similarities need your choice. Existing fields, addresses, VLAN assignments and wiring are preserved; conflicting source values remain visible in the UniFi snapshot.</p>
    ${draft.warnings.length?`<details><summary>Warnings (${draft.warnings.length})</summary>${draft.warnings.map(w=>`<p>${esc(w)}</p>`).join('')}</details>`:''}
    ${machines.map((r,index)=>`<details class="card mb"><summary>${esc(r.name)} · ${esc(r.proposal.action)} · ${esc(r.mac||'MAC unavailable')}</summary><p>${esc(r.proposal.reason)}</p>
      <p>IP: ${esc(r.addresses.map(a=>a.address).join(', ')||'No eligible LAN address')} · Type: ${esc(r.device_type)} · ${esc(r.connection_type)} · ${r.ports.length} reported ports</p><p>Reported uplink source ID: ${esc(r.uplink||'Unknown')} (port unknown)</p>
      <label>Import decision<select data-choice="${index}"><option value="skip" ${r.proposal.action==='skip'?'selected':''}>Skip local changes</option><option value="create" ${r.proposal.action==='create'?'selected':''}>Create a new device</option>${draft.choices.map(d=>`<option value="${d.id}" ${r.proposal.action==='match'&&r.proposal.device_id===d.id?'selected':''}>Match: ${esc(d.name)} (#${d.id})</option>`).join('')}</select></label></details>`).join('')}
    <details><summary>Networks and VPN observations</summary>${networks.map(n=>`<p>VLAN ${esc(n.tag??'unknown')} · ${esc(n.name)} · ${esc(n.subnets.join(', '))}</p>`).join('')}${vpns.map(v=>`<p>VPN: ${esc(v.name)} · ${esc(v.type)} — remote endpoint not reported; snapshot only</p>`).join('')}</details>
    <label><input type="checkbox" data-networks checked> Add missing VLANs/subnets. Existing VLAN definitions are preserved; no interface memberships are guessed.</label>
    <label><input type="checkbox" data-uplinks> Fill missing reported uplinks between imported/matched devices. Existing wiring and VM hosts are preserved; ports remain unknown.</label>
    <p>Only currently connected clients are reported by this API. Generic clients are created as “Other”; review their device type afterwards. This is a dated snapshot, not live monitoring.</p><button class="btn btn-primary" data-confirm>Confirm import into AreaBook</button>`;
  container.querySelector('[data-confirm]').onclick=async e=>{
    const decisions=machines.map((r,index)=>{const value=container.querySelector(`[data-choice="${index}"]`).value;return {kind:r.kind,id:r.id,action:['skip','create'].includes(value)?value:'match',device_id:Number(value)||null};});
    e.target.disabled=true;status.textContent='Importing reviewed records…';
    try{const result=await api.post('/api/unifi/import',{token:draft.token,decisions,import_networks:container.querySelector('[data-networks]').checked,import_uplinks:container.querySelector('[data-uplinks]').checked});modal.close();toast(`UniFi: ${result.created} created, ${result.matched} matched, ${result.skipped} skipped, ${result.vlans_added} VLANs and ${result.uplinks_added} uplinks added.${result.warnings.length?' Review warnings in the source observations.':''}`,'success');navigate('#/clinics/'+result.clinic_id);}catch(error){status.textContent=error.message;e.target.disabled=false;}
  };
}

export async function unifiClinic(container,cid){
  const user=await api.get('/api/auth/me');if(!user.roles.includes('admin')&&user.active_role!=='it')return;
  const data=await api.get(`/api/unifi/clinics/${cid}`);if(!data.sites.length||!container.isConnected)return;
  const card=document.createElement('section');card.className='card mb';
  card.innerHTML=`<h2>UniFi network observations</h2><p>Read-only snapshots. Local documentation is preserved. Unknown ports, VLAN membership and VPN remote endpoints are not inferred.</p>${user.roles.includes('admin')?'<button class="btn" data-refresh>Review a fresh UniFi import</button>':''}
    ${data.sites.map(s=>`<details><summary>${esc(s.name)} · ${esc(s.updated_at)} UTC</summary>${JSON.parse(s.warnings||'[]').map(w=>`<p>${esc(w)}</p>`).join('')}${data.records.filter(r=>r.host_id===s.host_id&&r.site_id===s.site_id).map(({data:r,local_id,updated_at})=>`<details><summary>${esc(r.name)} · ${esc(r.kind)}${local_id?' · linked #'+local_id:''}</summary><p>Last observed in import: ${esc(updated_at)} UTC. Missing from a later import does not delete this record.</p><pre style="white-space:pre-wrap">${esc(JSON.stringify(Object.fromEntries(Object.entries(r).filter(([k])=>k!=='proposal')),null,2))}</pre></details>`).join('')}</details>`).join('')}`;
  container.append(card);const button=card.querySelector('[data-refresh]');if(button)button.onclick=()=>importUnifi(cid);
}
