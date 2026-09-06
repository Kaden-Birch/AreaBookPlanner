import { api } from '../api.js';
import { user, role } from '../auth.js';
import { esc, attr, fmtDateOnly, fmtDateTime, setTitle, toast } from '../ui.js';

export async function render(container) {
  setTitle('IT overview');
  const area=user.areas.find(a=>a.role===role() && a.id===user.area_id);
  let data, includeProspects=false, directoryFilter='', query='', showClinics=false, showAttention=false, attentionFilter='', showUpcoming=false;
  let generation=0;
  container.innerHTML=`<section class="it-dashboard">
    <header class="it-heading"><div><div class="it-eyebrow">IT OPERATIONS · ${esc(area?.name||'Selected Area')}</div><h1>Your IT overview</h1><p class="muted">What needs attention, what’s coming up, and a shortcut to every clinic.</p></div>
      <div class="it-heading-actions"><a class="btn" href="#/map">Open Area map ↗</a><button class="btn btn-primary" id="it-new-task">+ Technical task</button></div></header>
    <div class="it-scope"><label><input type="checkbox" id="it-prospects"> Include prospects & other relationships</label><span id="it-updated" class="muted" role="status">Loading overview…</span><button class="btn btn-sm" id="it-refresh">Refresh</button></div>
    <p id="it-error" role="alert" hidden></p>
    <div id="it-content"><div class="loading">Loading your Area…</div></div>
    <footer class="it-footnote">Documentation overview, not live monitoring. Equipment totals include all recorded statuses. VPN status is manually recorded.</footer>
  </section>`;
  const content=container.querySelector('#it-content');
  const view=container.querySelector('.it-dashboard');
  async function load() {
    if(container.querySelector('.it-dashboard')!==view) return;
    const run=++generation;
    const error=container.querySelector('#it-error');
    error.hidden=true;
    container.querySelector('#it-updated').textContent='Refreshing…';
    // Do not leave old-scope figures visible while a new scope loads.
    content.innerHTML='<div class="loading">Loading your Area…</div>';
    try {
      const result=await api.get('/api/it/dashboard',{include_prospects:includeProspects});
      if(run!==generation || container.querySelector('.it-dashboard')!==view) return;
      data=result; draw();
      container.querySelector('#it-updated').textContent=`Updated ${new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})} · ${includeProspects?'All relationships':'Current clients'} + unlinked Area tasks`;
    } catch(e) {
      if(run!==generation || container.querySelector('.it-dashboard')!==view) return;
      error.textContent=`Could not load overview: ${e.message}. Use Refresh to retry.`;error.hidden=false;
      content.innerHTML='';container.querySelector('#it-updated').textContent='Overview unavailable';
    }
  }
  function draw() {
    const s=data.summary;
    content.innerHTML=`<div class="it-metrics">${[
      ['client','Current clients',s.current_clients,'Open client directory','◉'],
      ['devices','Documented devices',s.devices,'Find clinics with equipment','▤'],
      ['servers','Servers & VMs',s.servers,'Find clinics with servers','▥'],
      ['overdue','Overdue tasks',s.overdue_tasks,'Review overdue Area tasks','◷'],
    ].map(([filter,label,value,hint,icon])=>`<button class="it-metric ${filter==='overdue'&&value?'it-metric-warn':''}" data-metric="${filter}" aria-label="${attr(`${value} ${label}. ${hint}`)}"><span class="it-metric-label">${label}<span aria-hidden="true">${icon}</span></span><strong>${value}</strong><span class="it-metric-hint">${hint} ↗</span></button>`).join('')}</div>
      <div class="it-work-grid"><section class="card it-panel" id="it-attention-panel"><div class="it-panel-heading"><h2>Needs attention <span class="it-count">${data.attention.length}</span></h2><select id="it-attention-filter" aria-label="Attention category"><option value="">All items</option><option value="task">Overdue tasks</option><option value="documentation">Equipment gaps</option><option value="service">Service support gaps</option><option value="vpn">VPN marked down</option></select></div><p class="muted small">Actionable work and documentation gaps—not automatic fault alerts.</p><div id="it-attention"></div></section>
      <section class="card it-panel"><div class="it-panel-heading"><h2>Today & upcoming</h2><a href="#/tasks">All Area tasks ↗</a></div><p class="muted small">Through ${esc(fmtDateOnly(data.through))} · ${s.open_tasks} open tasks in this overview</p><div id="it-upcoming"></div></section></div>
      <section class="card it-panel" id="it-directory"><div class="it-panel-heading"><div><h2>Clinic shortcuts</h2><p class="muted small">${s.services} services documented across ${data.clinics.length} clinics.</p></div><a href="#/clinics">Full clinic directory ↗</a></div>
      <div class="it-directory-tools"><input type="search" id="it-clinic-search" placeholder="Find a clinic by name or shorthand…" aria-label="Search clinic shortcuts"><select id="it-directory-filter" aria-label="Clinic shortcut filter"><option value="">All clinics in this overview</option><option value="client">Current clients</option><option value="devices">With documented equipment</option><option value="servers">With servers or VMs</option></select></div><div id="it-clinics"></div></section>`;
    content.querySelector('#it-clinic-search').value=query;
    content.querySelector('#it-directory-filter').value=directoryFilter;
    content.querySelector('#it-attention-filter').value=attentionFilter;
    content.querySelector('#it-clinic-search').oninput=e=>{query=e.target.value;showClinics=false;drawClinics();};
    content.querySelector('#it-directory-filter').onchange=e=>{directoryFilter=e.target.value;showClinics=false;drawClinics();};
    content.querySelector('#it-attention-filter').onchange=e=>{attentionFilter=e.target.value;showAttention=false;drawAttention();};
    content.querySelectorAll('[data-metric]').forEach(b=>b.onclick=()=>{
      if(b.dataset.metric==='overdue') {attentionFilter='task';showAttention=true;content.querySelector('#it-attention-filter').value='task';drawAttention();content.querySelector('#it-attention-filter').focus();content.querySelector('#it-attention-panel').scrollIntoView({behavior:'smooth',block:'start'});}
      else {directoryFilter=b.dataset.metric;query='';showClinics=false;content.querySelector('#it-clinic-search').value='';content.querySelector('#it-directory-filter').value=directoryFilter;drawClinics();content.querySelector('#it-clinic-search').focus();content.querySelector('#it-directory').scrollIntoView({behavior:'smooth',block:'start'});}
    });
    drawAttention();drawUpcoming();drawClinics();
  }
  function drawAttention() {
    const rows=data.attention.filter(a=>!attentionFilter||a.kind===attentionFilter), host=content.querySelector('#it-attention');
    host.innerHTML=rows.length ? (showAttention?rows:rows.slice(0,5)).map(a=>`<div class="it-work-item"><span class="it-item-symbol ${a.kind==='task'||a.kind==='vpn'?'it-amber':''}" aria-hidden="true">${a.kind==='task'?'◷':a.kind==='vpn'?'↔':'▤'}</span><div class="it-item-body"><strong>${esc(a.title)}</strong><div>${esc(a.clinic_name||'Unlinked Area task')}</div><small class="muted">${esc(a.detail)}</small></div>${a.task_id?`<button class="btn btn-sm" data-task="${a.task_id}">Open task</button>`:`<a class="btn btn-sm" href="#/clinics/${a.clinic_id}/equipment?view=${(a.kind==='vpn'||a.topology)?'topology':'list'}&site=all">${(a.kind==='vpn'||a.topology)?'Topology':'Equipment'}</a>`}</div>`).join('') : '<div class="it-empty"><strong>No items to review here</strong><p>No matching overdue work or documentation gaps. This is not a live health check.</p></div>';
    if(rows.length>5) host.insertAdjacentHTML('beforeend',`<button class="it-show-more" id="it-attention-more">${showAttention?'Show fewer':`View all ${rows.length} items`}</button>`);
    host.querySelectorAll('.it-work-item').forEach((item,i)=>{
      const entry=rows[i];
      if(!entry.service_id) return;
      const link=item.querySelector('a.btn');
      const button=document.createElement('button');button.className='btn btn-sm';button.textContent='Open service';
      button.onclick=async()=>{
        try {const {openServiceDetail}=await import('../equipment.js');await openServiceDetail({clinic:{id:entry.clinic_id,name:entry.clinic_name},serviceId:entry.service_id,onChanged:load});}
        catch(e){toast(e.message,'error');}
      };
      link.replaceWith(button);
    });
    const more=host.querySelector('#it-attention-more');if(more) more.onclick=()=>{showAttention=!showAttention;drawAttention();};
    wireTasks(host);
  }
  function drawUpcoming() {
    const host=content.querySelector('#it-upcoming'),rows=data.upcoming;
    host.innerHTML=rows.length?(showUpcoming?rows:rows.slice(0,5)).map(a=>`<div class="it-work-item"><div class="it-date-pill"><strong>${a.date===data.today?'Today':esc(fmtDateOnly(a.date))}</strong><small>${a.kind==='task'?'Task':'Appointment'}</small></div><div class="it-item-body"><strong>${esc(a.title)}</strong><div>${esc(a.clinic_name||'Unlinked Area task')}</div>${a.start_time?`<small class="muted">${esc(fmtDateTime(a.start_time))}</small>`:''}</div>${a.kind==='task'?`<button class="btn btn-sm" data-task="${a.id}">Open task</button>`:`<a class="btn btn-sm" href="#/clinics/${a.clinic_id}">Open clinic</a>`}</div>`).join(''):'<div class="it-empty"><strong>A clear schedule</strong><p>No tasks due or scheduled appointments in this window.</p><a href="#/calendar">Open calendar ↗</a></div>';
    if(rows.length>5) host.insertAdjacentHTML('beforeend',`<button class="it-show-more" id="it-upcoming-more">${showUpcoming?'Show fewer':`View all ${rows.length} upcoming items`}</button>`);
    const more=host.querySelector('#it-upcoming-more');if(more) more.onclick=()=>{showUpcoming=!showUpcoming;drawUpcoming();};
    wireTasks(host);
  }
  function drawClinics() {
    const rows=data.clinics.filter(c=>(!query||`${c.name} ${c.shorthand||''}`.toLowerCase().includes(query.trim().toLowerCase()))&&(!directoryFilter||(directoryFilter==='client'?c.relationship==='current_client':directoryFilter==='devices'?c.device_count>0:c.server_count>0)));
    const host=content.querySelector('#it-clinics');
    host.innerHTML=`<p class="muted small" role="status">${rows.length} matching clinics${rows.length>6&&!showClinics?' · showing first 6':''}</p><div class="it-clinic-grid">${(showClinics?rows:rows.slice(0,6)).map(c=>`<article class="it-clinic"><div class="it-clinic-name"><span class="it-monogram" aria-hidden="true">${esc(c.shorthand||c.name.slice(0,2).toUpperCase())}</span><div><a href="#/clinics/${c.id}">${esc(c.name)}</a><div class="muted small">${c.relationship==='current_client'?'Current client':'Other relationship'}</div></div></div><div class="it-clinic-counts"><span><strong>${c.site_count}</strong> sites</span><span><strong>${c.device_count}</strong> devices</span><span><strong>${c.server_count}</strong> servers / VMs</span><span><strong>${c.service_count}</strong> services</span></div><div class="it-clinic-links"><a href="#/clinics/${c.id}/equipment?view=list&site=all">Equipment & services</a><a href="#/clinics/${c.id}/equipment?view=topology&site=all">Topology</a><a href="#/clinics/${c.id}/equipment?view=racks&site=all">Racks</a></div></article>`).join('')||'<div class="it-empty"><strong>No matching clinics</strong><p>Try another search or filter, include other relationships, or check your Area assignment.</p></div>'}</div>`;
    if(rows.length>6) host.insertAdjacentHTML('beforeend',`<button class="it-show-more" id="it-clinics-more">${showClinics?'Show fewer':`Show all ${rows.length} clinics`}</button>`);
    const more=host.querySelector('#it-clinics-more');if(more) more.onclick=()=>{showClinics=!showClinics;drawClinics();};
  }
  function wireTasks(host) {
    host.querySelectorAll('[data-task]').forEach(b=>b.onclick=async()=>{
      try {const task=await api.get(`/api/tasks/${b.dataset.task}`);const {openTaskForm}=await import('../forms.js');await openTaskForm({task,onSaved:load});}
      catch(e){toast(e.message,'error');}
    });
  }
  container.querySelector('#it-prospects').onchange=e=>{includeProspects=e.target.checked;showClinics=false;load();};
  container.querySelector('#it-refresh').onclick=load;
  container.querySelector('#it-new-task').onclick=async()=>{try {const {openTaskForm}=await import('../forms.js');await openTaskForm({onSaved:load});}catch(e){toast(e.message,'error');}};
  await load();
}
