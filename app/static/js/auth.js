import { api } from './api.js';
import { esc, attr, setTheme, confirmDialog, toast, openModal } from './ui.js';
import { workspaceDestination, hasUnsavedInputs } from './workspace-navigation.js';

export let user = null;
export const roleNames = { sales: 'Sales', client_success: 'Client Success', it: 'IT', manager: 'Manager', admin: 'Administration' };
const roleSummary={sales:'Prospects, quotes, contacts and commercial work in assigned Areas; no technical configuration.',client_success:'Current clients in assigned Areas; no prospecting or technical configuration.',it:'Equipment, services, topology, VPNs and technical tasks in assigned Areas.',manager:'Sales and client-management work, quote generation and assigned-Area transfers; no technical configuration or global pricing changes.',admin:'All workspaces, all Areas, users and shared application settings.'};
export const role = () => user?.active_role;
export const technical = () => role() === 'it';
export const business = () => ['sales','manager','client_success'].includes(role());
export const selling = () => ['sales','manager'].includes(role());
let switching=false;
export async function changeWorkspace(nextRole, areaId=null) {
  if(switching)return;
  const restoreSelection=()=>{document.querySelector('#workspace-select').value=role();const area=document.querySelector('#area-select');if(area)area.value=String(user.area_id);};
  if(hasUnsavedInputs() && !await confirmDialog('You have unsaved changes. Discard them and switch workspace or Area?')){restoreSelection();return;}
  switching=true;
  let switched=false;
  try {
    const previous={role:role(),area_id:user.area_id};
    const allowed=user.areas.filter(a=>a.role===nextRole);
    const area_id=areaId??(allowed.some(a=>a.id===user.area_id)?user.area_id:null);
    let destination=workspaceDestination(location.hash,nextRole,user.roles.includes('admin'));
    await api.post('/api/auth/workspace',{role:nextRole,area_id});
    switched=true;
    const clinic=destination.match(/^#\/clinics\/(\d+)/);
    if(clinic) {
      try { await api.get(`/api/clinics/${clinic[1]}`); }
      catch(e){if(![403,404].includes(e.status))throw e;destination='#/clinics';sessionStorage.setItem('workspace-notice','This clinic is not available in the selected workspace/Area. Choose another assigned Area from the account menu.');}
    }
    sessionStorage.setItem(`previous-workspace:${user.id}`,JSON.stringify(previous));
    location.hash=destination;location.reload();
  } catch(e){toast(e.message,'error');if(switched)location.reload();else restoreSelection();}finally{switching=false;}
}

export function openWorkspaceSwitcher() {
  const modal=openModal({title:'Switch workspace',body:`<p>Keep your current page when the selected workspace can access it.</p><div class="actions">${user.roles.map(r=>`<button class="btn" data-workspace="${r}">${roleNames[r]}${r===role()?' · current':''}</button>`).join('')}</div><button class="btn mt" data-previous>Return to previous workspace</button>`,footer:'<button class="btn" data-close>Close</button>'});
  modal.body.querySelectorAll('[data-workspace]').forEach(b=>b.onclick=()=>{modal.close();changeWorkspace(b.dataset.workspace);});
  modal.body.querySelector('[data-previous]').onclick=()=>{const prior=JSON.parse(sessionStorage.getItem(`previous-workspace:${user.id}`)||'null');if(prior&&user.roles.includes(prior.role)){modal.close();changeWorkspace(prior.role,prior.area_id);}else toast('No previous workspace is available.');};
  modal.root.querySelector('[data-close]').onclick=()=>modal.close();
}

export async function boot() {
  try { user = await api.get('/api/auth/me'); }
  catch (e) {
    if (e.status !== 401) throw e;
    const status = await api.get('/api/auth/status');
    await loginForm(status.setup_required);
    return false;
  }
  if (user.must_change_password) { passwordForm(); return false; }
  const preferences=await api.get('/api/auth/preferences');
  document.addEventListener('preferenceschange',e=>Object.assign(preferences,e.detail));
  if(preferences.theme) setTheme(preferences.theme);
  if(sessionStorage.getItem('apply-startup')) {
    sessionStorage.removeItem('apply-startup');
    if(!location.hash||location.hash==='#/') {
      let target=preferences.startup_page==='map'?'#/map':preferences.startup_page==='last'?(localStorage.getItem(`last-page:${user.id}`)||'#/'):'#/';
      if(!/^#\//.test(target))target='#/';
      target=workspaceDestination(target,role(),user.roles.includes('admin'));
      const clinic=target.match(/^#\/clinics\/(\d+)(?:[/?]|$)/);
      if(clinic) {
        try { await api.get(`/api/clinics/${clinic[1]}`); }
        catch(e) { target='#/clinics';sessionStorage.setItem('workspace-notice','Your saved clinic page is unavailable in this workspace or Area. Choose a clinic from your current list.'); }
      }
      location.hash=target;
    }
  }
  const notice=sessionStorage.getItem('workspace-notice');if(notice){sessionStorage.removeItem('workspace-notice');toast(notice,'info',8000);}
  document.addEventListener('keydown',e=>{if(preferences.workspace_shortcut&&e.ctrlKey&&e.altKey&&!e.metaKey&&e.key.toLowerCase()===preferences.workspace_shortcut){if(!e.target.closest('input,textarea,select,[contenteditable=true]')){e.preventDefault();openWorkspaceSwitcher();}}});
  accountMenu();
  return true;
}

function loginForm(setup) {
  document.querySelector('.topbar').hidden = true;
  const app = document.getElementById('app');
  app.innerHTML = `<form class="card" id="login-form" style="max-width:440px;margin:8vh auto">
    <h1>${setup ? 'Create the first administrator' : 'Sign in'}</h1><p>Area Book Planner</p>
    <label class="field">Username<input name="username" autocomplete="username" required maxlength="80"></label>
    <label class="field">Password<input name="password" type="password" autocomplete="${setup ? 'new-password':'current-password'}" required ${setup ? 'minlength="12"':''} maxlength="256"></label>
    ${setup ? '<label class="field">Confirm password<input name="confirm" type="password" autocomplete="new-password" required></label><p>Use at least 12 characters.</p>' : ''}
    <p id="auth-error" role="alert"></p><button class="btn btn-primary">${setup ? 'Create administrator':'Sign in'}</button></form>`;
  app.querySelector('form').onsubmit = async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    const error = app.querySelector('#auth-error');
    if (setup && f.get('password') !== f.get('confirm')) { error.textContent='Passwords do not match'; return; }
    const btn=e.target.querySelector('button'); btn.disabled=true;
    try { await api.post(`/api/auth/${setup?'setup':'login'}`, {username:f.get('username'),password:f.get('password')}); sessionStorage.setItem('apply-startup','1');location.reload(); }
    catch(e) { error.textContent=e.message; btn.disabled=false; }
  };
}

function passwordForm() {
  document.querySelector('.topbar').hidden = true;
  const app=document.getElementById('app');
  app.innerHTML=`<form class="card" style="max-width:440px;margin:8vh auto"><h1>Change password</h1>
    <label class="field">Current password<input type="password" name="current_password" autocomplete="current-password" required></label>
    <label class="field">New password<input type="password" name="password" autocomplete="new-password" minlength="12" maxlength="256" required></label>
    <label class="field">Confirm new password<input type="password" name="confirm" autocomplete="new-password" required></label>
    <p role="alert"></p><button class="btn btn-primary">Save password</button></form>`;
  app.querySelector('form').onsubmit=async e=>{e.preventDefault(); const d=Object.fromEntries(new FormData(e.target));
    try {if(d.password!==d.confirm) throw new Error('Passwords do not match'); await api.post('/api/auth/password',d); location.reload();}
    catch(err){e.target.querySelector('[role=alert]').textContent=err.message;}};
}

function accountMenu() {
  document.querySelector('.topbar').hidden=false;
  const host=document.createElement('div'); host.id='account-menu';
  const workspaces=user.roles.filter(r=>r!=='admin');
  const areas=user.areas.filter(a=>a.role===role());
  host.innerHTML=`<label>${esc(user.display_name)} <select id="workspace-select" aria-label="Workspace">
    ${workspaces.map(r=>`<option value="${r}" ${r===role()?'selected':''}>${roleNames[r]}</option>`).join('')}
    ${role()==='admin'?'<option value="" selected disabled>Choose workspace</option>':''}</select></label>
    ${areas.length>1?`<select id="area-select" aria-label="Area">${areas.map(a=>`<option value="${a.id}" ${a.id===user.area_id?'selected':''}>${esc(a.name)}</option>`).join('')}</select>`:areas.length?`<span>${esc(areas[0].name)}</span>`:''}
    ${user.roles.includes('admin')?'<button class="btn btn-sm" id="administration">Administration</button>':''}
    ${user.roles.includes('admin')?'<a class="btn btn-sm" href="#/application-settings">Global settings</a>':''}<a class="btn btn-sm" href="#/settings">My settings</a><button class="btn btn-sm" id="password-change">Password</button><button class="btn btn-sm" id="signout">Sign out</button>`;
  document.querySelector('.topbar-right').append(host);
  const change=changeWorkspace;
  host.querySelector('#workspace-select').onchange=e=>change(e.target.value,null);
  host.querySelector('#workspace-select').hidden=!workspaces.length;
  if(host.querySelector('#administration')) host.querySelector('#administration').onclick=()=>change('admin',null);
  if(host.querySelector('#area-select')) host.querySelector('#area-select').onchange=e=>change(role(),Number(e.target.value));
  host.querySelector('#signout').onclick=async()=>{await api.post('/api/auth/logout',{});location.reload();};
  host.querySelector('#password-change').onclick=passwordForm;
  document.querySelectorAll('#topnav a').forEach(a=>a.hidden=a.dataset.route==='settings'||!allowedPage(a.dataset.route));
  if(role()==='client_success') document.querySelector('#topnav [data-route=clinics]').hidden=true;
  document.getElementById('global-add-clinic').hidden=!selling();
  document.getElementById('global-add-appointment').hidden=!business();
  document.getElementById('global-search').hidden=false;
  if(role()==='client_success') document.querySelector('[data-route=map]').textContent='Client Map';
}

export function allowedPage(nav) {
  if(nav==='application-settings') return !!user?.roles.includes('admin');
  if(nav==='settings') return true;
  if(role()==='admin') return false;
  if(['settings'].includes(nav)) return false;
  if(['pipeline','analytics'].includes(nav)) return selling();
  if(['billing','clients'].includes(nav)) return business();
  return true;
}

export function pruneWorkspaceUI(root) {
  if(user?.roles.includes('admin') && location.hash==='#/application-settings') return;
  if(role()==='admin') return;
  const hide=selector=>root.querySelectorAll(selector).forEach(el=>{el.hidden=true;});
  if(!technical()) {
    hide('#btn-device, #btn-ticket, #vpn-btn, #conn-check, #connectivity-check, [data-connectivity], [data-vpn], [data-act="connectivity"], [data-act="conn-loc"], #btn-location, [data-act="edit-loc"]');
    root.querySelectorAll('a[href*="/equipment"]').forEach(el=>el.hidden=true);
    const ticket=root.querySelector('#btn-ticket'); if(ticket) ticket.closest('.card').hidden=true;
  }
  if(role()==='client_success') {
    root.querySelectorAll('#legend-filter [data-color]').forEach(el=>{if(el.dataset.color!=='client') el.closest('label').hidden=true;});
    hide('#relationship, #color');
    root.querySelectorAll('#clinic-form input, #clinic-form select, #clinic-form textarea').forEach(el=>{
      if(el.name && !['phone','fax','email','website','hours','notes','next_follow_up','display_address','name'].includes(el.name)) el.closest('.field')?.setAttribute('hidden','');
    });
    root.querySelectorAll('#task-form [name=clinic_id], #contact-form [name=clinic_id]').forEach(el=>el.required=true);
  }
  hide('#view-select, #import-backup, #new-group-btn');
  if(!selling()) hide('#btn-delete, #btn-stage, #btn-archive, #global-add-clinic, [data-add-clinic], #stage-move, #btn-edit-deal, #btn-promote, #place-btn, #stage-filter, #stage, #q-status, #apply-deal, #dup, .quote-doc ~ #del, #btn-link, [data-act="del-link"]');
  if(!selling() && root.querySelector('.quote-doc')) hide('#del');
  if(!business()) hide('#btn-edit, #btn-edit-notes, #btn-contact, #btn-appointment, #btn-contact-2, #btn-appt-2, #btn-scan-card, [data-act="edit-contact"], [data-act="appt"], [data-act="move"], #btn-locate');
  if(!business()) {
    hide('#add-contact, #scan-card, #new-appt');
    root.querySelectorAll('#table button[data-id]').forEach(el=>{if(location.hash==='#/contacts') el.hidden=true;});
  }
  if(!business()) {
    hide('#btn-invoice, #global-add-appointment');
    const invoice=root.querySelector('#btn-invoice'); if(invoice) invoice.closest('.card').hidden=true;
    const deal=root.querySelector('#btn-edit-deal'); if(deal) deal.closest('.card').hidden=true;
  }
  root.querySelectorAll('a[href]').forEach(a=>{
    const href=a.getAttribute('href');
    if(!selling() && (/\/quote$|\/quotes\/\d+\/edit/.test(href))) a.hidden=true;
    if(!business() && /#\/(billing|clients|invoices)/.test(href)) a.hidden=true;
    if(!selling() && /#\/(pipeline|analytics)/.test(href)) a.hidden=true;
    if(href.includes('/api/export/backup')) a.hidden=true;
  });
}

export async function renderItHome(container) {
  const dashboard = await import('./pages/it-dashboard.js');
  await dashboard.render(container);
}

export async function renderAdmin(container) {
  const [users,areas,clinics]=await Promise.all([api.get('/api/admin/users'),api.get('/api/admin/areas'),api.get('/api/admin/clinic-areas')]);
  const adminIntro='<p>Administrators have access to every workspace and all Areas. Choose a workspace in the top-right menu to open its interface.</p><p><a class="btn btn-primary" href="#/application-settings">Global application settings</a> <a class="btn" href="#/settings">My settings</a></p>';
  container.innerHTML=`<h1>Administration</h1><div class="card"><h2>Users</h2><button class="btn" id="add-user">+ Add user</button>
    ${users.map(u=>`<p><strong>${esc(u.display_name)}</strong> · ${esc(u.username)} · ${u.assignments.map(a=>roleNames[a.role]).join(', ')} · ${u.is_active?'Active':'Inactive'} <button class="btn btn-sm" data-user="${u.id}">Edit / reset password</button></p>`).join('')}</div>
    <div class="card"><h2>Areas</h2><button class="btn" id="add-area">+ Add Area</button>${areas.map(a=>`<p>${esc(a.name)} · ${a.is_active?'Active':'Inactive'} <button class="btn btn-sm" data-area="${a.id}">Edit</button></p>`).join('')}</div>
    <div class="card"><h2>Clinic Area assignments</h2><p>Assign existing clinics explicitly. Unassigned clinics are hidden from staff. Only provisioning metadata is shown here.</p>
    ${clinics.map(c=>`<p>${esc(c.name)} · ${esc(c.city||'')} <select aria-label="Service Area for ${attr(c.name)}" data-clinic="${c.id}"><option value="" disabled ${!c.area_id?'selected':''}>Unassigned</option>${areas.map(a=>`<option value="${a.id}" ${c.area_id===a.id?'selected':''} ${!a.is_active?'disabled':''}>${esc(a.name)}${!a.is_active?' (inactive)':''}</option>`).join('')}</select></p>`).join('')}</div><div id="admin-editor"></div>`;
  container.querySelector('h1').insertAdjacentHTML('afterend',adminIntro);
  const summaries=document.createElement('details');summaries.innerHTML='<summary>What each role can access</summary>'+Object.entries(roleSummary).map(([r,s])=>`<p><strong>${roleNames[r]}</strong> — ${esc(s)}</p>`).join('');container.querySelector('h1').after(summaries);
  container.querySelectorAll('[data-clinic]').forEach(el=>el.onchange=async()=>{if(el.value) await api.put(`/api/admin/clinic-areas/${el.dataset.clinic}`,{area_id:Number(el.value)});});
  const areaForm=(a={})=>{
    const editor=container.querySelector('#admin-editor');
    editor.innerHTML=`<form class="card"><h2>${a.id?'Edit':'Add'} Area</h2>${['name','latitude','longitude','default_zoom'].map(k=>`<label class="field">${k.replaceAll('_',' ')}<input name="${k}" value="${attr(a[k]??(k==='default_zoom'?12:''))}" required></label>`).join('')}
      <label><input type="checkbox" name="is_active" ${a.is_active!==0?'checked':''}> Active</label><p role="alert"></p><button class="btn btn-primary">Save Area</button></form>`;
    editor.scrollIntoView(); editor.querySelector('form').onsubmit=async e=>{e.preventDefault();let d=Object.fromEntries(new FormData(e.target));d.is_active=e.target.elements.is_active.checked;
      try{await(a.id?api.put(`/api/admin/areas/${a.id}`,d):api.post('/api/admin/areas',d));await renderAdmin(container);}catch(err){e.target.querySelector('[role=alert]').textContent=err.message;}};
  };
  container.querySelector('#add-area').onclick=()=>areaForm();
  container.querySelectorAll('[data-area]').forEach(el=>el.onclick=()=>areaForm(areas.find(a=>a.id===Number(el.dataset.area))));
  const userForm=(u={assignments:[]})=>{
    const editor=container.querySelector('#admin-editor');
    editor.innerHTML=`<form class="card"><h2>${u.id?'Edit':'Add'} user</h2>
      <label class="field">Display name<input name="display_name" value="${attr(u.display_name||'')}" required></label>
      <label class="field">Username<input name="username" value="${attr(u.username||'')}" required></label>
      <label class="field">${u.id?'Reset password (leave blank to keep)':'Temporary password'}<input type="password" name="password" minlength="12" autocomplete="new-password" ${u.id?'':'required'}></label>
      <label><input type="checkbox" name="is_active" ${u.is_active!==0?'checked':''}> Active</label>
      <label><input type="checkbox" name="must_change_password" ${u.must_change_password!==0?'checked':''}> Require password change</label>
      ${Object.entries(roleNames).map(([r,label])=>{const as=u.assignments.find(a=>a.role===r);return `<fieldset data-role="${r}"><legend><label><input type="checkbox" name="enabled" ${as?'checked':''}> ${label}</label></legend>
      ${r==='admin'?'Full access to every workspace, all Areas and global settings':`${areas.filter(a=>a.is_active).map(a=>`<label style="margin-right:12px"><input type="checkbox" name="area" value="${a.id}" ${as?.area_ids.includes(a.id)?'checked':''}> ${esc(a.name)}</label>`).join('')}
      <label>Default <select name="default_area_id"><option value="">Choose Area</option>${areas.filter(a=>a.is_active).map(a=>`<option value="${a.id}" ${as?.default_area_id===a.id?'selected':''}>${esc(a.name)}</option>`).join('')}</select></label>`}</fieldset>`;}).join('')}
      <p role="alert"></p><button class="btn btn-primary">Save user</button><p>Changing an account signs that user out of existing sessions.</p></form>`;
    editor.scrollIntoView();editor.querySelector('form').onsubmit=async e=>{e.preventDefault();const f=e.target,d=Object.fromEntries(new FormData(f));
      d.password=d.password||null; d.is_active=f.elements.is_active.checked;d.must_change_password=f.elements.must_change_password.checked;
      d.assignments=[...f.querySelectorAll('fieldset')].filter(fs=>fs.querySelector('[name=enabled]').checked).map(fs=>({role:fs.dataset.role,area_ids:[...fs.querySelectorAll('[name=area]:checked')].map(x=>Number(x.value)),default_area_id:Number(fs.querySelector('[name=default_area_id]')?.value)||null}));
      const access=d.assignments.some(a=>a.role==='admin')?'Full administrator access: all workspaces, all Areas and global settings.':d.assignments.map(a=>`${roleNames[a.role]}: ${a.area_ids.map(id=>areas.find(x=>x.id===id)?.name||id).join(', ')||'No Areas'}`).join('\n');
      if(!await confirmDialog(`Save access for ${d.display_name}?\n${access}\nExisting sessions will be signed out.`))return;
      try{await(u.id?api.put(`/api/admin/users/${u.id}`,d):api.post('/api/admin/users',d));if(u.id===user.id){location.reload();return;}await renderAdmin(container);}catch(err){f.querySelector('[role=alert]').textContent=err.message;}};
  };
  container.querySelector('#add-user').onclick=()=>userForm();
  container.querySelectorAll('[data-user]').forEach(el=>el.onclick=()=>userForm(users.find(u=>u.id===Number(el.dataset.user))));
}
