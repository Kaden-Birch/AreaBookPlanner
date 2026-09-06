import { esc, attr } from './ui.js';
import { displayGraph, layoutGraph, layoutPhysical, nodeHeight } from './topology-graph.js';
import { accentClass } from './equipment.js';

export function mountTopology(body, topo, meta, key, actions) {
  let prefs;
  try { prefs = JSON.parse(localStorage.getItem(key) || '{}'); } catch { prefs = {}; }
  const perspective=prefs?.perspective==='physical'?'physical':'logical';
  const all=perspective==='physical'?(topo.physical_nodes||[]):[...topo.nodes,...(topo.offsite||[])];
  const edges=perspective==='physical'?(topo.physical_edges||[]):topo.edges;
  const byId=new Map(all.map(n=>[n.id,n]));
  let placementGroups=[];
  let hidden = new Set(Array.isArray(prefs?.hidden) ? prefs.hidden : []);
  let collapsed = new Set(Array.isArray(prefs?.collapsed) ? prefs.collapsed : []);
  let orientation=prefs?.orientation==='vertical'?'vertical':'horizontal';
  const vlanCatalog=topo.vlans||[];
  let selectedVlans=new Set((Array.isArray(prefs?.vlans)?prefs.vlans:[]).filter(id=>vlanCatalog.some(v=>v.id===id)));
  let vlanOnly=!!prefs?.vlanOnly;
  const member=(n,ids=selectedVlans)=>(n.vlan_memberships||[]).some(m=>ids.has(m.vlan_id));
  let graph, positions, vpnPositions = [], selected = null, drag = null, suppressClick = false;
  let view = { x: 0, y: 0, z: 1 };
  const save = (nextPerspective=perspective) => { try { localStorage.setItem(key, JSON.stringify({ perspective:nextPerspective,hidden: [...hidden], collapsed: [...collapsed],orientation,vlans:[...selectedVlans],vlanOnly })); } catch { /* Browser storage may be disabled. */ } };
  const types = Object.entries(meta.types).filter(([t]) => all.some(n => n.device_type === t));
  body.innerHTML = `<div class="topology-controls card">
    <div class="topology-toolbar">
      <label class="topology-search">Find a device or service<input type="search" id="topology-search" placeholder="Name, IP, service, serial, model…" autocomplete="off"></label>
      <details class="topology-types"><summary>Device types</summary><div class="topology-type-menu">
        <input type="search" aria-label="Find a device type" placeholder="Find a type…">
        <div class="actions"><button class="btn btn-sm" data-filter="all">Show all</button><button class="btn btn-sm" data-filter="none">Hide all</button></div>
        ${types.map(([t,v]) => `<label data-type-row="${attr(v.label.toLowerCase())}"><input type="checkbox" data-type="${attr(t)}" ${hidden.has(t)?'':'checked'}> ${esc(v.icon)} ${esc(v.label)} (${all.filter(n=>n.device_type===t).length})</label>`).join('')}
      </div></details>
      <button class="btn btn-sm" id="topology-collapse">Collapse branches</button><button class="btn btn-sm" id="topology-expand">Expand all</button>
      <button class="btn btn-sm" id="topology-reset">Reset filters</button>
      <button class="btn btn-sm" id="topology-edit">Edit connections</button>
      <label>Layout<select id="topology-orientation"><option value="horizontal" ${orientation==='horizontal'?'selected':''}>Horizontal →</option><option value="vertical" ${orientation==='vertical'?'selected':''}>Vertical ↓</option></select></label>
      <button class="btn btn-sm" id="topology-manage-vlans">Manage VLANs</button>
      <label>View<select id="topology-perspective"><option value="logical" ${perspective==='logical'?'selected':''}>Logical network</option><option value="physical" ${perspective==='physical'?'selected':''}>Physical placement</option></select></label>
    </div><p class="muted small" id="topology-summary" aria-live="polite"></p>
    <div class="topology-vlan-bar"><span>VLANs:</span>${vlanCatalog.map(v=>`<button class="btn btn-sm" data-vlan="${v.id}" aria-pressed="${selectedVlans.has(v.id)}" title="${attr(v.name+' · '+(v.location_name||'Main site')+' · '+v.subnets.join(', '))}"><span class="vlan-dot" style="background:${attr(v.color)}"></span>${v.tag} · ${esc(v.name)}</button>`).join('')||'<span class="muted small">No VLANs recorded.</span>'}<label><input type="checkbox" id="topology-vlan-only" ${vlanOnly?'checked':''}> Only selected VLANs</label><button class="btn btn-sm" id="topology-vlan-clear">Clear VLAN selection</button></div>
    <div id="topology-vlan-details" class="small"></div>
    <div id="topology-results" class="topology-results" aria-live="polite"></div>
  </div>
  <div class="topology-canvas" tabindex="0" role="region" aria-label="Network topology. Drag background to pan. Use arrow keys to pan and plus or minus to zoom.">
    <div class="topology-camera"><button class="btn btn-sm" data-camera="out" aria-label="Zoom out">−</button><span id="topology-zoom"></span><button class="btn btn-sm" data-camera="in" aria-label="Zoom in">+</button><button class="btn btn-sm" data-camera="fit">Fit to screen</button><button class="btn btn-sm" data-camera="actual">100%</button></div>
    <svg class="topology-stage" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg"><g class="topology-scene"></g></svg>
    <div id="topology-empty" class="topology-empty" hidden>No devices visible. Change the device filters or expand branches.</div>
  </div>
  <p class="muted small">Drag to pan · Scroll to zoom · Dashed shortcuts contain hidden devices · Hover a VLAN to preview; click to select.</p>
  <div class="topology-colour-legend"><span class="accent-network">■ Network</span><span class="accent-server">■ Server / VM · purple virtual links</span><span class="accent-endpoint">■ Workstation</span><span class="accent-phone">■ Phone / mobile</span><span class="accent-printer">■ Printer</span><span class="accent-security">■ Security</span><span>Solid: wired · dotted: wireless · dashed: shortcut</span></div>
  <div id="topology-inspector" class="card" hidden></div>
  <details class="card" id="topology-review"><summary>Documentation review (${(topo.documentation||[]).length} items)</summary><p class="muted">Missing or inconsistent documentation, not live faults or reachability. Review applicability before making changes. Physical placement excludes VMs; use Logical network to see them.</p><div id="topology-documentation"></div></details>
  ${topo.vpn?.length ? `<details class="card"><summary>VPN links (${topo.vpn.length})</summary><div class="actions">${topo.vpn.map(v=>`<button class="btn btn-sm" data-vpn-link="${v.vpn_id}">${esc(v.remote.kind==='endpoint'?v.remote.name:v.remote.clinic_name+' · '+v.remote.site_name)}</button>`).join('')}</div></details>`:''}`;
  const canvas = body.querySelector('.topology-canvas'), scene = body.querySelector('.topology-scene');
  const inspector = body.querySelector('#topology-inspector'), search = body.querySelector('#topology-search');
  const camera = () => { scene.setAttribute('transform', `translate(${view.x},${view.y}) scale(${view.z})`); body.querySelector('#topology-zoom').textContent = `${Math.round(view.z*100)}%`; };
  const zoom = (factor, x=canvas.clientWidth/2, y=canvas.clientHeight/2) => {
    const z=Math.min(3,Math.max(.03,view.z*factor)), ratio=z/view.z;
    view.x=x-(x-view.x)*ratio; view.y=y-(y-view.y)*ratio; view.z=z; camera();
  };
  const fit = () => {
    canvas.style.height=`${Math.max(280,window.innerHeight-(canvas.getBoundingClientRect().top+window.scrollY)-60)}px`;
    const points=[...[...positions].map(([id,p])=>({...p,h:nodeHeight(byId.get(id))})),...vpnPositions.map(p=>({...p,h:80})),...placementGroups.map(g=>({x:g.x+g.width-230,y:g.y,h:g.height}))];
    const minX=Math.min(30,...points.map(p=>p.x)),minY=Math.min(30,...points.map(p=>p.y));
    const width=Math.max(240,...points.map(p=>p.x+230))-minX, height=Math.max(120,...points.map(p=>p.y+p.h+10))-minY;
    view.z=Math.max(.03,Math.min(1,(canvas.clientWidth-32)/width,(canvas.clientHeight-50)/height));
    view.x=(canvas.clientWidth-width*view.z)/2-minX*view.z; view.y=42-minY*view.z; camera();
  };
  const focus = id => {
    const p=positions.get(id); if(!p)return;
    selected=id; view={x:canvas.clientWidth/2-(p.x+110),y:canvas.clientHeight/2-(p.y+50),z:1}; camera();
    scene.querySelectorAll('[data-device]').forEach(el=>el.classList.toggle('selected',Number(el.dataset.device)===id));
  };
  const shorten = (s,n=27) => String(s||'').length>n?String(s).slice(0,n-1)+'…':String(s||'');
  const draw = (refit=true) => {
    const vlanHidden=vlanOnly&&selectedVlans.size?all.filter(n=>!member(n)).map(n=>n.id):[];
    graph=displayGraph(all,edges,[...hidden],[...collapsed],vlanHidden);
    if(perspective==='physical') { const placement=layoutPhysical(graph.nodes,orientation);positions=placement.positions;placementGroups=placement.groups; }
    else { positions=layoutGraph(graph.nodes,graph.edges,orientation);placementGroups=[]; }
    const vpnX=Math.max(30,...[...positions.values()].map(p=>p.x+270));
    vpnPositions=(topo.vpn||[]).map((v,i)=>({x:vpnX,y:30+i*132}));
    if(selected&&!positions.has(selected))selected=null;
    inspector.hidden=true;
    body.querySelector('#topology-empty').hidden=!!graph.nodes.length||!!vpnPositions.length;
    body.querySelector('#topology-summary').textContent=`${graph.nodes.length} of ${all.length} devices visible · ${all.filter(n=>hidden.has(n.device_type)).length} hidden by type · ${graph.collapsedCount} inside collapsed branches${hidden.size||collapsed.size||selectedVlans.size?' · View filters active':''}. Preferences saved in this browser.`;
    scene.innerHTML=placementGroups.map(g=>`<g class="topology-placement"><rect x="${g.x}" y="${g.y}" width="${g.width}" height="${g.height}" rx="12"/><text x="${g.x+15}" y="${g.y+25}">${esc(shorten(g.label,70))}</text><title>${esc(g.label)}</title></g>`).join('')+graph.edges.map((e,i)=>{
      const a=positions.get(e.from), b=positions.get(e.to), vertical=orientation==='vertical';
      const x=a.x+(vertical?110:220),y=a.y+(vertical?nodeHeight(byId.get(e.from)):35),end=b.x+(vertical?110:0),ey=b.y+(vertical?0:35);
      const path=vertical?`M${x},${y} C${x},${y+20} ${end},${ey-20} ${end},${ey}`:`M${x},${y} C${x+25},${y} ${end-25},${ey} ${end},${ey}`;
      const label=e.hidden.length?`${e.hidden.length} hidden: ${e.hidden.map(id=>byId.get(id).name).join(' → ')}`:`${byId.get(e.from).name} → ${byId.get(e.to).name} (${e.link_type}${e.primary?'':', extra link'}) · ${e.details?.source_interface_name||'?'} → ${e.details?.target_interface_name||'?'}${e.details?.speed_mbps?' · '+e.details.speed_mbps+' Mbps':''} · ${e.details?.vlan_mode||'VLAN mode unknown'} · ${e.details?.admin_status||'unknown'} (recorded)`;
      return `<g class="topology-link ${e.hidden.length?'compressed':''} ${!e.primary?'secondary':''} ${e.link_type==='wireless'?'wireless':''} ${e.link_type==='virtual'?'virtual':''}" data-link="${i}" tabindex="0" role="button" aria-label="${attr(label)}"><title>${esc(label)}</title><path d="${path}"/><path class="hit" d="${path}"/>${e.hidden.length?`<text x="${x+10}" y="${y-8}">+${e.hidden.length} hidden</text>`:''}</g>`;
    }).join('')+graph.nodes.map(n=>{
      const p=positions.get(n.id), count=graph.counts.get(n.id), folded=collapsed.has(n.id),h=nodeHeight(n);
      const gaps=(topo.documentation||[]).filter(i=>i.kind==='device'&&i.id===n.id);
      return `<g class="topology-device ${accentClass(n.device_type,meta)} ${n.is_vm?'vm':''} ${n.status==='retired'?'retired':''} ${selected===n.id?'selected':''}" transform="translate(${p.x},${p.y})" data-device="${n.id}">
        <rect width="220" height="${h}" rx="9"/><rect class="type-stripe" x="0" y="8" width="4" height="${h-16}"/><g tabindex="0" role="button" data-open="${n.id}" aria-label="Open ${attr(n.name)}"><title>${esc(n.name)}${n.off_site?' · Off-site':''}</title><rect class="device-hit" width="220" height="65" rx="9"/><text x="10" y="22">${esc(n.icon)} ${esc(shorten(n.name,25))}</text><text class="muted-label" x="10" y="42">${esc(shorten(n.addresses?.[0]?.address||n.ip_address||n.designation||n.type_label))}</text><text class="muted-label" x="10" y="59">${esc(shorten(n.off_site?'Off-site':n.location_name||'Main site',17))}${n.status==='retired'?' · Retired':''}</text></g>
        ${gaps.length?`<text class="documentation-badge" x="204" y="22" tabindex="0" role="button" data-review="${n.id}" aria-label="Review documentation for ${attr(n.name)}"><title>${gaps.length} documentation items</title>!</text>`:''}
        <text class="service-link" tabindex="0" role="button" aria-label="Network addresses for ${attr(n.name)}" data-network="${n.id}" x="140" y="59">${n.addresses?.length>1?'+'+(n.addresses.length-1)+' addresses':'Network…'}</text>
        ${(n.services||[]).slice(0,2).map((s,i)=>`<text class="service-link" tabindex="0" role="button" aria-label="Open service ${attr(s.name)}" data-service="${s.id}" x="10" y="${74+i*14}">${esc(shorten(s.name,23))}</text>`).join('')}
        ${(n.services||[]).length>2?`<text class="service-link" tabindex="0" role="button" data-open="${n.id}" x="10" y="105">+${n.services.length-2} more services</text>`:''}
        ${count?`<g class="branch-toggle" tabindex="0" role="button" aria-expanded="${!folded}" aria-label="${folded?'Expand':'Collapse'} ${attr(n.name)} branch, ${count} devices" data-branch="${n.id}"><rect x="170" y="${h-19}" width="45" height="17" rx="4"/><text x="174" y="${h-6}">${folded?'+':'−'} ${count}</text></g>`:''}
      </g>`;
    }).join('')+(topo.vpn||[]).map((v,i)=>{
      const p=vpnPositions[i], local=positions.get(v.device_id);
      const label=v.remote.kind==='endpoint'?v.remote.name:v.remote.clinic_name+' · '+v.remote.site_name;
      return `${local?`<path class="topology-vpn-line" d="M${local.x+220},${local.y+35} L${p.x},${p.y+35}"/>`:''}<g class="topology-device topology-vpn" transform="translate(${p.x},${p.y})" tabindex="0" role="button" data-vpn-canvas="${v.vpn_id}" aria-label="Open VPN ${attr(label)}"><title>${esc(label)}</title><rect width="220" height="80" rx="9"/><text x="10" y="22">🔒 ${esc(shorten(label,25))}</text><text class="muted-label" x="10" y="43">${esc(shorten(v.name||'VPN tunnel'))}</text><text class="muted-label" x="10" y="64">${esc(v.status_label||v.status)}${!local&&v.device_id?' · local device hidden':''}</text></g>`;
    }).join('');
    scene.querySelectorAll('[data-open]').forEach(el=>el.onclick=()=>actions.device(Number(el.dataset.open)));
    scene.querySelectorAll('[data-service]').forEach(el=>el.onclick=()=>actions.service(Number(el.dataset.service)));
    scene.querySelectorAll('[data-network]').forEach(el=>el.onclick=()=>actions.network(Number(el.dataset.network)));
    scene.querySelectorAll('[data-review]').forEach(el=>el.onclick=()=>{const review=body.querySelector('#topology-review');review.open=true;review.scrollIntoView({block:'start'});});
    scene.querySelectorAll('[data-vpn-canvas]').forEach(el=>el.onclick=()=>actions.vpn(Number(el.dataset.vpnCanvas)));
    scene.querySelectorAll('[data-branch]').forEach(el=>el.onclick=()=>{const id=Number(el.dataset.branch);collapsed.has(id)?collapsed.delete(id):collapsed.add(id);save();draw();});
    scene.querySelectorAll('[data-link]').forEach(el=>el.onclick=()=>{
      const e=graph.edges[Number(el.dataset.link)], chain=[e.from,...e.hidden,e.to];
      if(!e.hidden.length){actions.connection(e.from,e.to);return;}
      inspector.hidden=false;
      inspector.innerHTML=`<strong>${e.hidden.length?'Connection through hidden devices':'Documented connection'}</strong><p>${chain.map(id=>esc(byId.get(id).name)).join(' → ')}</p>${e.hidden.length?'<p class="muted">This shortcut represents the documented chain. It is not a direct physical connection.</p>':''}`;
      chain.slice(1).forEach((id,i)=>{const button=document.createElement('button');button.className='btn btn-sm';button.textContent=byId.get(chain[i]).name+' → '+byId.get(id).name;button.onclick=()=>actions.connection(chain[i],id);inspector.append(button);});
      inspector.scrollIntoView({block:'nearest'});
    });
    scene.querySelectorAll('[role=button]').forEach(el=>el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();e.stopPropagation();el.onclick?.(e);}});
    if(refit)fit();else camera();
    highlight();
    vlanDetails();
    results();
  };
  const results = () => {
    const q=search.value.trim().toLowerCase(), host=body.querySelector('#topology-results');
    if(!q){host.innerHTML='';return;}
    const matches=all.filter(n=>[n.name,n.ip_address,n.serial,n.model,n.designation,n.user_name,n.location_name,...(n.services||[]).map(s=>s.name),...(n.addresses||[]).flatMap(a=>[a.address,a.hostname,a.interface_name])].filter(Boolean).join(' ').toLowerCase().includes(q));
    host.innerHTML=`<span class="muted small">${matches.length} matches${matches.length>30?' · showing first 30':''}</span>`+matches.slice(0,30).map(n=>`<button class="btn btn-sm" data-result="${n.id}">${esc(n.name)}${positions.has(n.id)?'':' · Reveal'}</button>`).join('');
    host.querySelectorAll('[data-result]').forEach(b=>b.onclick=()=>{
      const id=Number(b.dataset.result);hidden.delete(byId.get(id).device_type);
      if(vlanOnly&&selectedVlans.size&&!member(byId.get(id))) {vlanOnly=false;body.querySelector('#topology-vlan-only').checked=false;}
      const seen=new Set(); let ancestor=id;
      while(ancestor!=null&&!seen.has(ancestor)) {seen.add(ancestor);collapsed.delete(ancestor);ancestor=edges.find(e=>e.primary&&e.to===ancestor)?.from;}
      save();syncChecks();draw(false);focus(id);
    });
  };
  const syncChecks = () => body.querySelectorAll('[data-type]').forEach(c=>c.checked=!hidden.has(c.dataset.type));
  const highlight=(ids=selectedVlans)=>{
    scene.querySelectorAll('[data-device]').forEach(el=>el.classList.toggle('vlan-dim',ids.size>0&&!member(byId.get(Number(el.dataset.device)),ids)));
    scene.querySelectorAll('[data-link]').forEach(el=>{const e=graph.edges[Number(el.dataset.link)];el.classList.toggle('vlan-dim',ids.size>0&&![e.from,...e.hidden,e.to].some(id=>member(byId.get(id),ids)));});
  };
  const vlanDetails=()=>{
    const host=body.querySelector('#topology-vlan-details');
    host.innerHTML=vlanCatalog.filter(v=>selectedVlans.has(v.id)).map(v=>{
      const members=all.filter(n=>member(n,new Set([v.id])));
      return `<details><summary>${v.tag} · ${esc(v.name)} — ${members.length} devices · ${esc(v.subnets.join(', ')||'No subnets recorded')}</summary><p>${esc(v.description||'')} · Gateway: ${esc([v.gateway_device_name,v.gateway_interface_name].filter(Boolean).join(' / ')||'Not recorded')} · ${esc(v.dhcp_mode)}</p><p>${esc(v.notes||'')}</p><div class="topology-results">${members.slice(0,50).map(n=>`<button class="btn btn-sm" data-vlan-device="${n.id}">${esc(n.name)} · ${esc(n.vlan_memberships.filter(m=>m.vlan_id===v.id).map(m=>m.interface_name+': '+m.mode).join(', '))}</button>`).join('')}</div>${members.length>50?'<p>Showing first 50; use search to find more.</p>':''}</details>`;
    }).join('');
    host.querySelectorAll('[data-vlan-device]').forEach(b=>b.onclick=()=>actions.network(Number(b.dataset.vlanDevice)));
  };
  body.querySelectorAll('[data-vlan]').forEach(b=>{
    b.onmouseenter=()=>highlight(new Set([Number(b.dataset.vlan)]));b.onmouseleave=()=>highlight();
    b.onfocus=()=>highlight(new Set([Number(b.dataset.vlan)]));b.onblur=()=>highlight();
    b.onclick=()=>{const id=Number(b.dataset.vlan);selectedVlans.has(id)?selectedVlans.delete(id):selectedVlans.add(id);b.setAttribute('aria-pressed',selectedVlans.has(id));save();draw();};
  });
  body.querySelector('#topology-manage-vlans').onclick=actions.vlans;
  body.querySelector('#topology-perspective').onchange=e=>{save(e.target.value);actions.refresh();};
  const report=body.querySelector('#topology-documentation');
  let reportLimit=50;
  const showReport=()=>{
    const issues=topo.documentation||[];
    report.innerHTML=issues.slice(0,reportLimit).map((issue,i)=>`<p><button class="btn btn-sm" data-issue="${i}">${esc(issue.name)}</button> ${esc(issue.message)}</p>`).join('')||'<p>No documentation gaps detected by these checks.</p>';
    report.querySelectorAll('[data-issue]').forEach(b=>b.onclick=()=>{const issue=issues[Number(b.dataset.issue)];if(issue.kind==='connection')actions.connection(issue.parent,issue.child);else if(issue.kind==='vlan')actions.vlans();else if(['services','uplink'].includes(issue.code))actions.device(issue.id);else actions.network(issue.id);});
    if(issues.length>reportLimit){const more=document.createElement('button');more.className='btn';more.textContent='Show next 50';more.onclick=()=>{reportLimit+=50;showReport();};report.append(more);}
  };
  showReport();
  body.querySelector('#topology-orientation').onchange=e=>{orientation=e.target.value;save();draw();};
  body.querySelector('#topology-vlan-only').onchange=e=>{vlanOnly=e.target.checked;save();draw();};
  const clearVlans=()=>{selectedVlans.clear();body.querySelectorAll('[data-vlan]').forEach(b=>b.setAttribute('aria-pressed','false'));};
  body.querySelector('#topology-vlan-clear').onclick=()=>{clearVlans();save();draw();};
  search.oninput=results;
  body.querySelectorAll('[data-type]').forEach(c=>c.onchange=()=>{c.checked?hidden.delete(c.dataset.type):hidden.add(c.dataset.type);save();draw();});
  body.querySelector('.topology-type-menu input[type=search]').oninput=e=>body.querySelectorAll('[data-type-row]').forEach(r=>r.hidden=!r.dataset.typeRow.includes(e.target.value.toLowerCase()));
  body.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{hidden=new Set(b.dataset.filter==='none'?types.map(([t])=>t):[]);save();syncChecks();draw();});
  body.querySelector('#topology-collapse').onclick=()=>{collapsed=new Set(all.filter(n=>graph.counts.get(n.id)>0).map(n=>n.id));save();draw();};
  body.querySelector('#topology-expand').onclick=()=>{collapsed.clear();save();draw();};
  body.querySelector('#topology-reset').onclick=()=>{hidden.clear();collapsed.clear();clearVlans();vlanOnly=false;body.querySelector('#topology-vlan-only').checked=false;search.value='';save();syncChecks();draw();};
  body.querySelector('#topology-edit').onclick=actions.edit;
  body.querySelectorAll('[data-vpn-link]').forEach(b=>b.onclick=()=>actions.vpn(Number(b.dataset.vpnLink)));
  body.querySelectorAll('[data-camera]').forEach(b=>b.onclick=()=>{const a=b.dataset.camera;if(a==='fit')fit();else zoom(a==='in'?1.25:a==='out'?.8:1/view.z);});
  canvas.addEventListener('wheel',e=>{e.preventDefault();const r=canvas.getBoundingClientRect();zoom(e.deltaY<0?1.1:1/1.1,e.clientX-r.left,e.clientY-r.top);},{passive:false});
  canvas.addEventListener('pointerdown',e=>{
    if(e.button!==0||e.target.closest('[role=button],button'))return;
    drag={x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY};canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener('pointermove',e=>{if(!drag)return;view.x+=e.clientX-drag.x;view.y+=e.clientY-drag.y;drag.x=e.clientX;drag.y=e.clientY;if(Math.hypot(e.clientX-drag.startX,e.clientY-drag.startY)>4)suppressClick=true;camera();});
  canvas.addEventListener('pointerup',()=>{drag=null;setTimeout(()=>suppressClick=false,0);});
  canvas.addEventListener('pointercancel',()=>{drag=null;suppressClick=false;});
  canvas.addEventListener('click',e=>{if(suppressClick){e.preventDefault();e.stopImmediatePropagation();}},true);
  canvas.addEventListener('keydown',e=>{
    if(e.target!==canvas)return;
    if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','-','='].includes(e.key)){e.preventDefault();if(e.key==='+'||e.key==='=')zoom(1.25);else if(e.key==='-')zoom(.8);else {view.x+=e.key==='ArrowLeft'?40:e.key==='ArrowRight'?-40:0;view.y+=e.key==='ArrowUp'?40:e.key==='ArrowDown'?-40:0;camera();}}
  });
  draw();
}
