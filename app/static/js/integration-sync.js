import {api} from './api.js';
import {esc,openModal,toast,navigate} from './ui.js';
const date=t=>t?new Date(t*1000).toLocaleString():'Not yet';
const state=(j,global)=>!global?'Globally paused':!j.enabled?'Paused':j.running?'Syncing':j.error?'Retry scheduled':j.next_at<Date.now()/1000?'Queued / delayed':'Scheduled';

export async function syncSettings(container){
  const card=document.createElement('section');card.className='card mb';
  (container.querySelector('section[aria-label="AI & integrations"]')||container).append(card);
  async function load(){
    const data=await api.post('/api/integration-sync/discover',{});
    if(!card.isConnected)return;
    card.innerHTML=`<h2>Automatic integration sync</h2><p>Read-only source refreshes, staggered between linked clinics. New machines and wiring changes need review. Manual overrides are preserved. The interval is a target; provider limits may delay a refresh.</p>
      <label><input type="checkbox" data-enabled ${data.enabled?'checked':''}> Enable background synchronization</label><button class="btn" data-save>Save global setting</button><button class="btn" data-reload>Refresh status</button><p role="status"></p>
      ${data.jobs.map(j=>`<details class="card"><summary>${esc(j.clinic_name)} · ${esc(j.provider)} · ${esc(j.site_name)} — ${esc(state(j,data.enabled))}</summary><p>Last success: ${date(j.last_success)}<br>Next attempt: ${date(j.next_at)}<br>${j.pending} changes to review · ${j.overrides} overridden fields</p><p>${esc(j.error||'')}${j.warnings.map(w=>'<br>'+esc(w)).join('')}</p>
        <label><input type="checkbox" data-active="${j.id}" ${j.enabled?'checked':''}> Sync this site</label><label>Interval (minutes)<input type="number" min="15" max="1440" value="${j.interval_minutes}" data-interval="${j.id}"></label><div class="actions"><button class="btn" data-job="${j.id}">Save site</button><button class="btn" data-now="${j.id}">Sync now (queue)</button><button class="btn" data-review="${j.clinic_id}">Review changes</button></div></details>`).join('')||'<p>Import/link a clinic from Syncro or UniFi first.</p>'}`;
    const status=card.querySelector('[role=status]');
    async function run(button,fn){button.disabled=true;try{await fn();await load();}catch(e){status.textContent=e.message;button.disabled=false;}}
    card.querySelector('[data-save]').onclick=e=>run(e.target,()=>api.put('/api/integration-sync/settings',{enabled:card.querySelector('[data-enabled]').checked}));
    card.querySelector('[data-reload]').onclick=()=>load().catch(e=>status.textContent=e.message);
    card.querySelectorAll('[data-job]').forEach(b=>b.onclick=()=>run(b,()=>api.put('/api/integration-sync/jobs/'+b.dataset.job,{enabled:card.querySelector(`[data-active="${b.dataset.job}"]`).checked,interval_minutes:Number(card.querySelector(`[data-interval="${b.dataset.job}"]`).value)})));
    card.querySelectorAll('[data-now]').forEach(b=>b.onclick=()=>run(b,()=>api.post(`/api/integration-sync/jobs/${b.dataset.now}/now`,{})));
    card.querySelectorAll('[data-review]').forEach(b=>b.onclick=()=>reviewChanges(Number(b.dataset.review)));
  }
  await load();
}

export async function syncClinic(container,cid){
  const user=await api.get('/api/auth/me');if(!user.roles.includes('admin')&&user.active_role!=='it')return;
  const data=await api.get('/api/integration-sync/clinics/'+cid);if(!data.jobs.length||!container.isConnected)return;
  const card=document.createElement('section');card.className='card mb';
  card.innerHTML=`<h2>Integration freshness</h2>${data.jobs.map(j=>`<p><strong>${esc(j.provider)} · ${esc(j.site_name)}</strong>: ${esc(state(j,data.enabled))}<br>Last successful sync: ${date(j.last_success)} · Next attempt: ${date(j.next_at)}<br>${j.pending} pending changes ${j.error?'· '+esc(j.error):''}</p>`).join('')}<button class="btn" data-review>Changes to review</button><p>“Not reported” does not mean offline or deleted. Source snapshots are dated observations.</p>`;
  container.append(card);card.querySelector('[data-review]').onclick=()=>reviewChanges(cid);
}

export async function reviewChanges(cid){
  const modal=openModal({title:'Integration changes to review',size:'modal-lg',body:'Loading…',footer:'<button class="btn" data-close>Close</button>'});
  modal.root.querySelector('[data-close]').onclick=()=>modal.close();
  async function load(){
    const [data,user]=await Promise.all([api.get('/api/integration-sync/clinics/'+cid),api.get('/api/auth/me')]);
    const admin=user.roles.includes('admin');
    modal.body.innerHTML=`<p>These observations have not changed your wiring or added/deleted machines. Use a reviewed import to add records, or edit the topology after checking the change. “Mark reviewed” acknowledges the observation only.</p>${admin?'<div class="actions"><button class="btn" data-syncro>Open Syncro import</button><button class="btn" data-unifi>Open UniFi import</button></div>':''}
      ${data.changes.map(c=>`<details class="card"><summary>${esc(c.title)} · ${date(c.updated_at)}</summary><pre style="white-space:pre-wrap">${esc(JSON.stringify(c.detail,null,2))}</pre>${admin?`<button class="btn" data-ack="${c.id}">Mark reviewed (no data changes)</button>`:''}</details>`).join('')||'<p>No pending changes.</p>'}`;
    modal.body.querySelectorAll('[data-ack]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{await api.post('/api/integration-sync/changes/'+b.dataset.ack+'/acknowledge',{});await load();}catch(e){toast(e.message,'error');b.disabled=false;}});
    if(admin){
      modal.body.querySelector('[data-syncro]').onclick=async()=>{modal.close();(await import('./syncro.js')).importSyncro();};
      modal.body.querySelector('[data-unifi]').onclick=async()=>{modal.close();(await import('./unifi.js')).importUnifi(cid);};
      const meraki=document.createElement('button');meraki.className='btn';meraki.textContent='Open Meraki import';
      meraki.onclick=async()=>{modal.close();(await import('./meraki.js')).importMeraki(cid);};
      modal.body.querySelector('.actions').append(meraki);
    }
  }
  try{await load();}catch(e){modal.body.textContent=e.message;}
}
