import { esc, attr } from './ui.js';
import { displayGraph, layoutGraph } from './topology-graph.js';

export function mountTopology(body, topo, meta, key, actions) {
  const all = [...topo.nodes, ...(topo.offsite || [])], byId = new Map(all.map(n => [n.id, n]));
  let prefs;
  try { prefs = JSON.parse(localStorage.getItem(key) || '{}'); } catch { prefs = {}; }
  let hidden = new Set(Array.isArray(prefs?.hidden) ? prefs.hidden : []);
  let collapsed = new Set(Array.isArray(prefs?.collapsed) ? prefs.collapsed : []);
  let graph, positions, vpnPositions = [], selected = null, drag = null, suppressClick = false;
  let view = { x: 0, y: 0, z: 1 };
  const save = () => { try { localStorage.setItem(key, JSON.stringify({ hidden: [...hidden], collapsed: [...collapsed] })); } catch { /* Browser storage may be disabled. */ } };
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
    </div><p class="muted small" id="topology-summary" aria-live="polite"></p>
    <div id="topology-results" class="topology-results" aria-live="polite"></div>
  </div>
  <div class="topology-canvas" tabindex="0" role="region" aria-label="Network topology. Drag background to pan. Use arrow keys to pan and plus or minus to zoom.">
    <div class="topology-camera"><button class="btn btn-sm" data-camera="out" aria-label="Zoom out">−</button><span id="topology-zoom"></span><button class="btn btn-sm" data-camera="in" aria-label="Zoom in">+</button><button class="btn btn-sm" data-camera="fit">Fit to screen</button><button class="btn btn-sm" data-camera="actual">100%</button></div>
    <svg class="topology-stage" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg"><g class="topology-scene"></g></svg>
    <div id="topology-empty" class="topology-empty" hidden>No devices visible. Change the device filters or expand branches.</div>
  </div>
  <p class="muted small">Drag the background to pan. Scroll to zoom. Dashed shortcut links contain hidden devices; select one to see its path. Branch buttons expand or collapse downstream equipment.</p>
  <div id="topology-inspector" class="card" hidden></div>
  ${topo.vpn?.length ? `<details class="card"><summary>VPN links (${topo.vpn.length})</summary><div class="actions">${topo.vpn.map(v=>`<button class="btn btn-sm" data-vpn-link="${v.vpn_id}">${esc(v.remote.kind==='endpoint'?v.remote.name:v.remote.clinic_name+' · '+v.remote.site_name)}</button>`).join('')}</div></details>`:''}`;
  const canvas = body.querySelector('.topology-canvas'), scene = body.querySelector('.topology-scene');
  const inspector = body.querySelector('#topology-inspector'), search = body.querySelector('#topology-search');
  const camera = () => { scene.setAttribute('transform', `translate(${view.x},${view.y}) scale(${view.z})`); body.querySelector('#topology-zoom').textContent = `${Math.round(view.z*100)}%`; };
  const zoom = (factor, x=canvas.clientWidth/2, y=canvas.clientHeight/2) => {
    const z=Math.min(3,Math.max(.03,view.z*factor)), ratio=z/view.z;
    view.x=x-(x-view.x)*ratio; view.y=y-(y-view.y)*ratio; view.z=z; camera();
  };
  const fit = () => {
    const points=[...positions.values(),...vpnPositions];
    const width=Math.max(260,...points.map(p=>p.x+240)), height=Math.max(140,...points.map(p=>p.y+120));
    view.z=Math.max(.03,Math.min(1,(canvas.clientWidth-40)/width,(canvas.clientHeight-70)/height));
    view.x=(canvas.clientWidth-width*view.z)/2; view.y=50; camera();
  };
  const focus = id => {
    const p=positions.get(id); if(!p)return;
    selected=id; view={x:canvas.clientWidth/2-(p.x+110),y:canvas.clientHeight/2-(p.y+50),z:1}; camera();
    scene.querySelectorAll('[data-device]').forEach(el=>el.classList.toggle('selected',Number(el.dataset.device)===id));
  };
  const shorten = (s,n=27) => String(s||'').length>n?String(s).slice(0,n-1)+'…':String(s||'');
  const draw = (refit=true) => {
    graph=displayGraph(all,topo.edges,[...hidden],[...collapsed]); positions=layoutGraph(graph.nodes,graph.edges);
    const vpnX=Math.max(30,...[...positions.values()].map(p=>p.x+270));
    vpnPositions=(topo.vpn||[]).map((v,i)=>({x:vpnX,y:30+i*132}));
    if(selected&&!positions.has(selected))selected=null;
    inspector.hidden=true;
    body.querySelector('#topology-empty').hidden=!!graph.nodes.length||!!vpnPositions.length;
    body.querySelector('#topology-summary').textContent=`${graph.nodes.length} of ${all.length} devices visible · ${all.filter(n=>hidden.has(n.device_type)).length} hidden by type · ${graph.collapsedCount} inside collapsed branches${hidden.size||collapsed.size?' · View filters active':''}. Preferences saved in this browser.`;
    scene.innerHTML=graph.edges.map((e,i)=>{
      const a=positions.get(e.from), b=positions.get(e.to), x=a.x+220, y=a.y+35, end=b.x, ey=b.y+35;
      const path=`M${x},${y} C${x+25},${y} ${end-25},${ey} ${end},${ey}`;
      const label=e.hidden.length?`${e.hidden.length} hidden: ${e.hidden.map(id=>byId.get(id).name).join(' → ')}`:`${byId.get(e.from).name} → ${byId.get(e.to).name} (${e.link_type}${e.primary?'':', extra link'})`;
      return `<g class="topology-link ${e.hidden.length?'compressed':''} ${!e.primary?'secondary':''} ${e.link_type==='wireless'?'wireless':''}" data-link="${i}" tabindex="0" role="button" aria-label="${attr(label)}"><title>${esc(label)}</title><path d="${path}"/><path class="hit" d="${path}"/>${e.hidden.length?`<text x="${x+10}" y="${y-8}">+${e.hidden.length} hidden</text>`:''}</g>`;
    }).join('')+graph.nodes.map(n=>{
      const p=positions.get(n.id), count=graph.counts.get(n.id), folded=collapsed.has(n.id);
      return `<g class="topology-device ${n.is_vm?'vm':''} ${n.status==='retired'?'retired':''} ${selected===n.id?'selected':''}" transform="translate(${p.x},${p.y})" data-device="${n.id}">
        <rect width="220" height="116" rx="9"/><g tabindex="0" role="button" data-open="${n.id}" aria-label="Open ${attr(n.name)}"><title>${esc(n.name)}${n.off_site?' · Off-site':''}</title><rect class="device-hit" width="220" height="70" rx="9"/><text x="10" y="22">${esc(n.icon)} ${esc(shorten(n.name,25))}</text><text class="muted-label" x="10" y="42">${esc(shorten(n.ip_address||n.designation||n.type_label))}</text><text class="muted-label" x="10" y="59">${esc(n.off_site?'Off-site':n.location_name||'Main site')}${n.status==='retired'?' · Retired':''}</text></g>
        ${(n.services||[]).slice(0,2).map((s,i)=>`<text class="service-link" tabindex="0" role="button" aria-label="Open service ${attr(s.name)}" data-service="${s.id}" x="10" y="${76+i*15}">${esc(shorten(s.name))}</text>`).join('')}
        ${(n.services||[]).length>2?`<text class="service-link" tabindex="0" role="button" data-open="${n.id}" x="10" y="108">+${n.services.length-2} more services</text>`:''}
        ${count?`<g class="branch-toggle" tabindex="0" role="button" aria-expanded="${!folded}" aria-label="${folded?'Expand':'Collapse'} ${attr(n.name)} branch, ${count} devices" data-branch="${n.id}"><rect x="160" y="94" width="55" height="19" rx="4"/><text x="164" y="108">${folded?'+':'−'} ${count}</text></g>`:''}
      </g>`;
    }).join('')+(topo.vpn||[]).map((v,i)=>{
      const p=vpnPositions[i], local=positions.get(v.device_id);
      const label=v.remote.kind==='endpoint'?v.remote.name:v.remote.clinic_name+' · '+v.remote.site_name;
      return `${local?`<path class="topology-vpn-line" d="M${local.x+220},${local.y+35} L${p.x},${p.y+35}"/>`:''}<g class="topology-device topology-vpn" transform="translate(${p.x},${p.y})" tabindex="0" role="button" data-vpn-canvas="${v.vpn_id}" aria-label="Open VPN ${attr(label)}"><title>${esc(label)}</title><rect width="220" height="80" rx="9"/><text x="10" y="22">🔒 ${esc(shorten(label,25))}</text><text class="muted-label" x="10" y="43">${esc(shorten(v.name||'VPN tunnel'))}</text><text class="muted-label" x="10" y="64">${esc(v.status_label||v.status)}${!local&&v.device_id?' · local device hidden':''}</text></g>`;
    }).join('');
    scene.querySelectorAll('[data-open]').forEach(el=>el.onclick=()=>actions.device(Number(el.dataset.open)));
    scene.querySelectorAll('[data-service]').forEach(el=>el.onclick=()=>actions.service(Number(el.dataset.service)));
    scene.querySelectorAll('[data-vpn-canvas]').forEach(el=>el.onclick=()=>actions.vpn(Number(el.dataset.vpnCanvas)));
    scene.querySelectorAll('[data-branch]').forEach(el=>el.onclick=()=>{const id=Number(el.dataset.branch);collapsed.has(id)?collapsed.delete(id):collapsed.add(id);save();draw();});
    scene.querySelectorAll('[data-link]').forEach(el=>el.onclick=()=>{
      const e=graph.edges[Number(el.dataset.link)], chain=[e.from,...e.hidden,e.to];
      inspector.hidden=false;
      inspector.innerHTML=`<strong>${e.hidden.length?'Connection through hidden devices':'Documented connection'}</strong><p>${chain.map(id=>esc(byId.get(id).name)).join(' → ')}</p>${e.hidden.length?'<p class="muted">This shortcut represents the documented chain. It is not a direct physical connection.</p>':''}`;
      inspector.scrollIntoView({block:'nearest'});
    });
    scene.querySelectorAll('[role=button]').forEach(el=>el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();e.stopPropagation();el.onclick?.(e);}});
    if(refit)fit();else camera();
    results();
  };
  const results = () => {
    const q=search.value.trim().toLowerCase(), host=body.querySelector('#topology-results');
    if(!q){host.innerHTML='';return;}
    const matches=all.filter(n=>[n.name,n.ip_address,n.serial,n.model,n.designation,n.user_name,n.location_name,...(n.services||[]).map(s=>s.name)].filter(Boolean).join(' ').toLowerCase().includes(q));
    host.innerHTML=`<span class="muted small">${matches.length} matches${matches.length>30?' · showing first 30':''}</span>`+matches.slice(0,30).map(n=>`<button class="btn btn-sm" data-result="${n.id}">${esc(n.name)}${positions.has(n.id)?'':' · Reveal'}</button>`).join('');
    host.querySelectorAll('[data-result]').forEach(b=>b.onclick=()=>{
      const id=Number(b.dataset.result);hidden.delete(byId.get(id).device_type);
      const seen=new Set(); let ancestor=id;
      while(ancestor!=null&&!seen.has(ancestor)) {seen.add(ancestor);collapsed.delete(ancestor);ancestor=topo.edges.find(e=>e.primary&&e.to===ancestor)?.from;}
      save();syncChecks();draw(false);focus(id);
    });
  };
  const syncChecks = () => body.querySelectorAll('[data-type]').forEach(c=>c.checked=!hidden.has(c.dataset.type));
  search.oninput=results;
  body.querySelectorAll('[data-type]').forEach(c=>c.onchange=()=>{c.checked?hidden.delete(c.dataset.type):hidden.add(c.dataset.type);save();draw();});
  body.querySelector('.topology-type-menu input[type=search]').oninput=e=>body.querySelectorAll('[data-type-row]').forEach(r=>r.hidden=!r.dataset.typeRow.includes(e.target.value.toLowerCase()));
  body.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{hidden=new Set(b.dataset.filter==='none'?types.map(([t])=>t):[]);save();syncChecks();draw();});
  body.querySelector('#topology-collapse').onclick=()=>{collapsed=new Set(all.filter(n=>graph.counts.get(n.id)>0).map(n=>n.id));save();draw();};
  body.querySelector('#topology-expand').onclick=()=>{collapsed.clear();save();draw();};
  body.querySelector('#topology-reset').onclick=()=>{hidden.clear();collapsed.clear();search.value='';save();syncChecks();draw();};
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
