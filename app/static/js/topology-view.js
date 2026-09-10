import { esc, attr, toast, confirmDialog } from './ui.js';
import { api } from './api.js';
import { editTopologyGroup } from './topology-groups.js';
import { traceDestination, traceVpn, edgeOnPath, destinationDevices } from './topology-path.js';
import { displayedVpns, vpnDisplayClass } from './topology-vpn-display.js';
import { openRemoteTrace } from './topology-remote-trace.js';
import { displayGraph, layoutGraph, layoutPhysical, layoutSubnets, nodeHeight, linkSpeedClass } from './topology-graph.js';
import { accentClass } from './equipment.js';
import { exportTopology } from './topology-reporting.js';
import { matchesTopologySearch, matchesTopologyFilter } from './topology-search.js';
import { validPositions, sceneBounds, viewportRect } from './topology-navigation.js';
import { organizeTopology } from './topology-workspace.js';
import {assignDeviceVlan} from './vlan-assignment.js';

export function mountTopology(body, topo, meta, key, actions) {
  let prefs;
  try { prefs = JSON.parse(localStorage.getItem(key) || '{}'); } catch { prefs = {}; }
  const perspective=['physical','subnet'].includes(prefs?.perspective)?prefs.perspective:'logical';
  const all=perspective==='physical'?(topo.physical_nodes||[]):[...topo.nodes,...(topo.offsite||[])];
  const edges=perspective==='physical'?(topo.physical_edges||[]):topo.edges;
  const byId=new Map(all.map(n=>[n.id,n]));
  let placementGroups=[];
  let hidden = new Set(Array.isArray(prefs?.hidden) ? prefs.hidden : []);
  let collapsed = new Set(Array.isArray(prefs?.collapsed) ? prefs.collapsed : []);
  let orientation=prefs?.orientation==='vertical'?'vertical':'horizontal';
  let manualMode=false;
  const positionKey=()=>`${key}:positions:${perspective}:${orientation}`;
  const loadPositions=()=>{try{return validPositions(JSON.parse(localStorage.getItem(positionKey())||'{}'));}catch{return {};}};
  let savedPositions=loadPositions();
  const savePositions=()=>{try{localStorage.setItem(positionKey(),JSON.stringify(savedPositions));}catch{ /* Session positions still work without storage. */ }};
  const vlanCatalog=topo.vlans||[];
  let assigning=false,assignmentBusy=false;
  let selectedVlans=new Set((Array.isArray(prefs?.vlans)?prefs.vlans:[]).filter(id=>vlanCatalog.some(v=>v.id===id)));
  let vlanOnly=!!prefs?.vlanOnly;
  let showVpn=prefs?.showVpn===true, quickFilter='', searchOnly=false;
  let vpnOnlyUp=false;
  let subnet='';
  let tracedPath=null;
  let tracedVpn=null;
  const groups=topo.groups||[];
  const foldedGroups=new Set((Array.isArray(prefs?.foldedGroups)?prefs.foldedGroups:[]).filter(id=>groups.some(g=>g.id===id)));
  const member=(n,ids=selectedVlans)=>(n.vlan_memberships||[]).some(m=>ids.has(m.vlan_id));
  let graph, positions, vpnPositions = [], selected = null, drag = null, suppressClick = false;
  let view = { x: 0, y: 0, z: 1 };
  const save = (nextPerspective=perspective) => { try { localStorage.setItem(key, JSON.stringify({ perspective:nextPerspective,hidden: [...hidden], collapsed: [...collapsed],orientation,vlans:[...selectedVlans],vlanOnly,showVpn,foldedGroups:[...foldedGroups] })); } catch { /* Browser storage may be disabled. */ } };
  const types = Object.entries(meta.types).filter(([t]) => all.some(n => n.device_type === t));
  body.innerHTML = `<div class="topology-controls card">
    <div class="topology-toolbar">
      <label class="topology-search">Find a device or service<input type="search" id="topology-search" placeholder="Name, IP, MAC, VLAN, subnet, service, room, rack…" autocomplete="off"></label>
      <label><input type="checkbox" id="topology-search-only"> Only search matches</label>
      <label>Quick filter<select id="topology-quick-filter"><option value="">All devices</option><option value="servers">Servers and VMs</option><option value="multiple">Multiple addresses</option><option value="documentation">Documentation needs attention</option>${[...new Set(all.map(n=>n.status).filter(Boolean))].sort().map(s=>`<option value="status:${attr(s)}">Status: ${esc(s)}</option>`).join('')}</select></label>
      <label><input type="checkbox" id="topology-show-vpn" ${showVpn?'checked':''}> Show VPN links</label>
      <label title="Uses manually recorded status, not live monitoring"><input type="checkbox" id="topology-vpn-up"> Only VPNs recorded Up</label>
      <label>Subnet<select id="topology-subnet"><option value="">All subnets</option>${[...new Set(all.flatMap(n=>n.subnets||[]))].sort().map(s=>`<option value="${attr(s)}">${esc(s)}</option>`).join('')}</select></label>
      <details class="topology-types"><summary>Device types</summary><div class="topology-type-menu">
        <input type="search" aria-label="Find a device type" placeholder="Find a type…">
        <div class="actions"><button class="btn btn-sm" data-filter="all">Show all</button><button class="btn btn-sm" data-filter="none">Hide all</button></div>
        ${types.map(([t,v]) => `<label data-type-row="${attr(v.label.toLowerCase())}"><input type="checkbox" data-type="${attr(t)}" ${hidden.has(t)?'':'checked'}> ${esc(v.icon)} ${esc(v.label)} (${all.filter(n=>n.device_type===t).length})</label>`).join('')}
      </div></details>
      <button class="btn btn-sm" id="topology-collapse">Collapse branches</button><button class="btn btn-sm" id="topology-expand">Expand all</button>
      <button class="btn btn-sm" id="topology-reset">Reset filters</button>
      <button class="btn btn-sm" id="topology-edit">Edit connections</button>
      <label>Layout<select id="topology-orientation"><option value="horizontal" ${orientation==='horizontal'?'selected':''}>Horizontal →</option><option value="vertical" ${orientation==='vertical'?'selected':''}>Vertical ↓</option></select></label>
      <label><input type="checkbox" id="topology-manual"> Move devices</label><button class="btn btn-sm" id="topology-auto-layout">Reset positions</button>
      <button class="btn btn-sm" id="topology-manage-vlans">Manage VLANs</button>
      <div id="topology-assign-controls"><button class="btn btn-sm" id="topology-assign" ${vlanCatalog.length?'':'disabled'}>Assign VLANs</button><label>VLAN to assign<select id="topology-assign-vlan">${vlanCatalog.map(v=>`<option value="${v.id}">${esc(v.location_name||'Main site')} · ${v.tag} · ${esc(v.name)}</option>`).join('')}</select></label><p class="help">Click devices consecutively to assign interfaces. Documentation only; no physical configuration changes.</p></div>
      <button class="btn btn-sm" id="topology-routing">VPN IP path review</button>
      <button class="btn btn-sm" id="topology-remote-trace">Cross-site path</button>
      <details class="topology-report-menu"><summary>Administration & reports</summary><div class="actions"><button class="btn btn-sm" id="topology-import">Import CSV</button><button class="btn btn-sm" id="topology-history">Versions & audit</button><button class="btn btn-sm" data-export="json">JSON</button><button class="btn btn-sm" data-export="csv">CSV</button><button class="btn btn-sm" data-export="svg">SVG</button><button class="btn btn-sm" data-export="png">PNG</button><button class="btn btn-sm" data-export="print">Print / PDF</button></div><p class="help">Exports use visible devices. Versions capture complete local documentation for this site.</p></details>
      <label>View<select id="topology-perspective"><option value="logical" ${perspective==='logical'?'selected':''}>Logical network</option><option value="physical" ${perspective==='physical'?'selected':''}>Physical placement</option><option value="subnet" ${perspective==='subnet'?'selected':''}>Subnet groups</option></select></label>
    </div><p class="muted small" id="topology-summary" aria-live="polite"></p>
    <div class="topology-vlan-bar"><span>VLANs:</span>${vlanCatalog.map(v=>`<button class="btn btn-sm" data-vlan="${v.id}" aria-pressed="${selectedVlans.has(v.id)}" title="${attr(v.name+' · '+(v.location_name||'Main site')+' · '+v.subnets.join(', '))}"><span class="vlan-dot" style="background:${attr(v.color)}"></span>${v.tag} · ${esc(v.name)}</button>`).join('')||'<span class="muted small">No VLANs recorded.</span>'}<label><input type="checkbox" id="topology-vlan-only" ${vlanOnly?'checked':''}> Only selected VLANs</label><button class="btn btn-sm" id="topology-vlan-clear">Clear VLAN selection</button></div>
    <div id="topology-vlan-details" class="small"></div>
    ${perspective==='subnet'?'<p class="help">Grouped by site and identical documented subnet memberships. Multi-subnet devices appear once in a combined group. Lines remain documented connections—not proof of routing between subnets. Use the Subnet filter to isolate one network.</p>':''}
    <details><summary>Logical groups (${groups.length})</summary><p class="help">Collapsing hides group members and preserves documented paths. Group membership is shared; collapse state is personal.</p><button class="btn btn-sm" id="topology-new-group">Add logical group</button><div id="topology-groups"></div></details>
    <div id="topology-results" class="topology-results" aria-live="polite"></div>
    <details><summary>Trace documented device path</summary><p class="help">Shows one shortest connection chain within this view’s site scope, not verified traffic routing. Parallel paths, firewall rules and VLAN reachability are not evaluated. Hidden intermediate devices remain in the trace.</p>
      <label>Source device<select id="topology-path-source">${all.map(n=>`<option value="${n.id}">${esc(n.name)}</option>`).join('')}</select></label>
      <label>Destination<select id="topology-path-target"><optgroup label="Devices">${all.map(n=>`<option value="${n.id}">${esc(n.name)}</option>`).join('')}</optgroup><optgroup label="Services (host device)">${all.flatMap(n=>(n.services||[]).map(s=>`<option value="service:${s.id}">${esc(s.name)} · ${esc(n.name)}</option>`)).join('')}</optgroup><optgroup label="Subnets (nearest documented member)">${[...new Set(all.flatMap(n=>n.subnets||[]))].sort().map(s=>`<option value="subnet:${attr(s)}">${esc(s)}</option>`).join('')}</optgroup></select></label>
      <button class="btn btn-sm" id="topology-trace">Trace path</button><button class="btn btn-sm" id="topology-clear-trace">Clear trace</button><div id="topology-path-result" aria-live="polite"></div></details>
    <nav id="topology-breadcrumb" aria-label="Topology focus"></nav>
  </div>
  <div class="topology-canvas" tabindex="0" role="region" aria-label="Network topology. Drag background to pan. Use arrow keys to pan and plus or minus to zoom.">
    <div class="topology-camera"><button class="btn btn-sm" data-camera="out" aria-label="Zoom out">−</button><span id="topology-zoom"></span><button class="btn btn-sm" data-camera="in" aria-label="Zoom in">+</button><button class="btn btn-sm" data-camera="fit">Fit to screen</button><button class="btn btn-sm" data-camera="actual">100%</button></div>
    <svg class="topology-stage" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg"><g class="topology-scene"></g></svg>
    <button class="topology-minimap" type="button" aria-label="Topology overview: click to centre the view, or use arrow keys to pan"><svg width="180" height="110" preserveAspectRatio="none" aria-hidden="true"></svg></button>
    <div id="topology-empty" class="topology-empty" hidden>No devices visible. Change the device filters or expand branches.</div>
  </div>
  <p class="muted small">Drag to pan · Scroll to zoom · Dashed shortcuts contain hidden devices · Hover a VLAN to preview; click to select. Move devices: drag a card or focus it and use arrow keys (Shift for larger steps). Manual positions are browser-local and available in Logical network; Physical placement follows room/rack groups.</p>
  <div class="topology-colour-legend"><span class="accent-network">■ Network</span><span class="accent-server">■ Server / VM · purple virtual links</span><span class="accent-endpoint">■ Workstation</span><span class="accent-phone">■ Phone / mobile</span><span class="accent-printer">■ Printer</span><span class="accent-security">■ Security</span><span>Red: &lt;1 Gb · blue: 1–&lt;2.5 Gb · green: 2.5–&lt;10 Gb · orange: ≥10 Gb · grey: unknown/shortcut · purple dots: virtual</span></div>
  <div id="topology-inspector" class="card" hidden></div>
  <details class="card" id="topology-review"><summary>Documentation review (${(topo.documentation||[]).length} items)</summary><p class="muted">Missing or inconsistent documentation, not live faults or reachability. Review applicability before making changes. Physical placement excludes VMs; use Logical network to see them.</p><div id="topology-documentation"></div></details>
  ${topo.vpn?.length ? `<details class="card"><summary>VPN links (${topo.vpn.length})</summary><div class="actions">${topo.vpn.map(v=>`<button class="btn btn-sm" data-vpn-link="${v.vpn_id}">${esc(v.remote.kind==='endpoint'?v.remote.name:v.remote.clinic_name+' · '+v.remote.site_name)}</button>`).join('')}</div></details>`:''}`;
  organizeTopology(body);
  const canvas = body.querySelector('.topology-canvas'), scene = body.querySelector('.topology-scene');
  const assignmentBanner=document.createElement('div');assignmentBanner.className='vlan-assignment-banner';assignmentBanner.hidden=true;canvas.before(assignmentBanner);
  const assignmentVlan=()=>vlanCatalog.find(v=>v.id===Number(body.querySelector('#topology-assign-vlan').value));
  const assignmentHighlight=()=>scene.querySelectorAll('[data-device]').forEach(el=>el.classList.toggle('vlan-assigned',assigning&&(byId.get(Number(el.dataset.device))?.vlan_memberships||[]).some(m=>m.vlan_id===assignmentVlan()?.id)));
  const assignmentState=()=>{
    assignmentBanner.hidden=!assigning;
    body.querySelector('#topology-assign').textContent=assigning?'Done assigning':'Assign VLANs';
    body.querySelector('#topology-assign').setAttribute('aria-pressed',String(assigning));
    const v=assignmentVlan();assignmentBanner.innerHTML=assigning?`<span>Assigning ${esc(v?.name)} · VLAN ${v?.tag} — click devices. Outlined devices already have this VLAN.</span> <button class="btn btn-sm">Done</button>`:'';
    assignmentBanner.querySelector('button')?.addEventListener('click',()=>{assigning=false;assignmentState();});assignmentHighlight();
  };
  body.querySelector('#topology-assign').onclick=()=>{assigning=!assigning;assignmentState();};
  body.querySelector('#topology-assign-vlan').onchange=assignmentState;
  body.addEventListener('keydown',e=>{if(e.key==='Escape'&&assigning){assigning=false;assignmentState();}},true);
  const assignClick=async(id)=>{
    if(assignmentBusy)return;assignmentBusy=true;
    const vlan=assignmentVlan();
    try{const result=await assignDeviceVlan(id,vlan,vlanCatalog);if(result){const n=byId.get(id);n.vlan_memberships=result.interfaces.flatMap(i=>i.memberships);n.addresses=result.interfaces.flatMap(i=>i.addresses);n.interface_count=result.interfaces.length;
      try{const fresh=await api.get(`/api/clinics/${actions.reportContext.clinic_id}/topology`,{site:actions.reportContext.site});const updated=[...(fresh.nodes||[]),...(fresh.offsite||[]),...(fresh.physical_nodes||[])].find(node=>node.id===id);if(updated)Object.assign(n,updated);topo.documentation=fresh.documentation;}catch{toast('Assignment saved. Refresh to update documentation review.');}
      if(body.isConnected)draw(false);toast(`VLAN ${vlan.tag} assigned to ${n.name}`,'success');}}
    catch(e){toast(e.message,'error');}finally{assignmentBusy=false;}
  };
  canvas.addEventListener('click',e=>{const device=e.target.closest('[data-device]');if(assigning&&device){e.preventDefault();e.stopImmediatePropagation();if(!suppressClick)assignClick(Number(device.dataset.device));}},true);
  canvas.addEventListener('keydown',e=>{const device=e.target.closest('[data-device]');if(assigning&&device&&['Enter',' '].includes(e.key)){e.preventDefault();e.stopImmediatePropagation();assignClick(Number(device.dataset.device));}},true);
  for(const [value,label] of [['open-work','Open tickets or tasks'],['open-tickets','Open tickets'],['open-tasks','Open tasks']]){const option=document.createElement('option');option.value=value;option.textContent=label;body.querySelector('#topology-quick-filter').append(option);}
  const inspector = body.querySelector('#topology-inspector'), search = body.querySelector('#topology-search');
  const minimap=body.querySelector('.topology-minimap'), miniSvg=minimap.querySelector('svg');
  let miniBounds={x:0,y:0,width:240,height:160};
  const updateMinimap=()=>{
    if(!positions)return;
    const rects=[...[...positions].map(([id,p])=>({...p,width:220,height:nodeHeight(byId.get(id))})),...vpnPositions.map(p=>({...p,width:220,height:80}))];
    const viewport=viewportRect(view,canvas.clientWidth,canvas.clientHeight);
    miniBounds=sceneBounds([...rects,viewport]);
    miniSvg.setAttribute('viewBox',`${miniBounds.x} ${miniBounds.y} ${miniBounds.width} ${miniBounds.height}`);
    miniSvg.innerHTML=rects.map(p=>`<rect class="minimap-node" x="${p.x}" y="${p.y}" width="${p.width}" height="${p.height}"/>`).join('')+
      `<rect class="minimap-viewport" x="${viewport.x}" y="${viewport.y}" width="${viewport.width}" height="${viewport.height}"/>`;
  };
  const camera = () => { scene.setAttribute('transform', `translate(${view.x},${view.y}) scale(${view.z})`); body.querySelector('#topology-zoom').textContent = `${Math.round(view.z*100)}%`;updateMinimap(); };
  const zoom = (factor, x=canvas.clientWidth/2, y=canvas.clientHeight/2) => {
    const z=Math.min(3,Math.max(.03,view.z*factor)), ratio=z/view.z;
    view.x=x-(x-view.x)*ratio; view.y=y-(y-view.y)*ratio; view.z=z; camera();
  };
  const fit = () => {
    const points=[...[...positions].map(([id,p])=>({...p,h:nodeHeight(byId.get(id))})),...vpnPositions.map(p=>({...p,h:80})),...placementGroups.map(g=>({x:g.x+g.width-230,y:g.y,h:g.height}))];
    const minX=Math.min(30,...points.map(p=>p.x)),minY=Math.min(30,...points.map(p=>p.y));
    const width=Math.max(240,...points.map(p=>p.x+230))-minX, height=Math.max(120,...points.map(p=>p.y+p.h+10))-minY;
    view.z=Math.max(.03,Math.min(1,(canvas.clientWidth-32)/width,(canvas.clientHeight-50)/height));
    view.x=(canvas.clientWidth-width*view.z)/2-minX*view.z; view.y=42-minY*view.z; camera();
  };
  const focus = id => {
    const p=positions.get(id); if(!p)return;
    selected=id; view={x:canvas.clientWidth/2-(p.x+110),y:canvas.clientHeight/2-(p.y+50),z:1}; camera();
    canvas.scrollIntoView({block:'nearest'});
    scene.querySelectorAll('[data-device]').forEach(el=>el.classList.toggle('selected',Number(el.dataset.device)===id));
    const crumb=body.querySelector('#topology-breadcrumb');
    crumb.innerHTML=`<button class="btn btn-sm" data-overview>Topology overview</button> › <span>${esc(byId.get(id).name)}</span>`;
    crumb.querySelector('[data-overview]').onclick=()=>{selected=null;crumb.innerHTML='';draw();};
  };
  const shorten = (s,n=27) => String(s||'').length>n?String(s).slice(0,n-1)+'…':String(s||'');
  const draw = (refit=true) => {
    const groupHidden=new Set(groups.filter(g=>foldedGroups.has(g.id)).flatMap(g=>g.device_ids));
    const vlanHidden=all.filter(n=>(vlanOnly&&selectedVlans.size&&!member(n))||!matchesTopologyFilter(n,quickFilter,topo.documentation)||
      (subnet&&!(n.subnets||[]).includes(subnet))||groupHidden.has(n.id)||(searchOnly&&!matchesTopologySearch(n,search.value,vlanCatalog))).map(n=>n.id);
    graph=displayGraph(all,edges,[...hidden],[...collapsed],vlanHidden);
    if(perspective!=='logical') { const placement=(perspective==='subnet'?layoutSubnets:layoutPhysical)(graph.nodes,orientation);positions=placement.positions;placementGroups=placement.groups; }
    else { positions=layoutGraph(graph.nodes,graph.edges,orientation);placementGroups=[]; }
    // Physical group boundaries must stay aligned with their automatically placed devices.
    if(perspective==='logical')for(const [id,p] of positions)if(savedPositions[id])positions.set(id,{...savedPositions[id]});
    const vpnX=Math.max(30,...[...positions.values()].map(p=>p.x+270));
    const visibleVpns=displayedVpns(topo.vpn||[],showVpn,vpnOnlyUp);
    vpnPositions=visibleVpns.map((v,i)=>({x:vpnX,y:30+i*132}));
    if(selected&&!positions.has(selected)){selected=null;body.querySelector('#topology-breadcrumb').innerHTML='';}
    inspector.hidden=true;
    body.querySelector('#topology-empty').hidden=!!graph.nodes.length||!!vpnPositions.length;
    body.querySelector('#topology-summary').textContent=`${graph.nodes.length} of ${all.length} devices visible · ${all.filter(n=>hidden.has(n.device_type)).length} hidden by type · ${graph.collapsedCount} inside collapsed branches · ${foldedGroups.size} groups collapsed${hidden.size||collapsed.size||selectedVlans.size||quickFilter||searchOnly||subnet||foldedGroups.size?' · View filters active':''}. Layout, device types, VLAN and VPN preferences saved in this browser.`;
    scene.innerHTML=placementGroups.map(g=>`<g class="topology-placement"><rect x="${g.x}" y="${g.y}" width="${g.width}" height="${g.height}" rx="12"/><text x="${g.x+15}" y="${g.y+25}">${esc(shorten(g.label,70))}</text><title>${esc(g.label)}</title></g>`).join('')+graph.edges.map((e,i)=>{
      const a=positions.get(e.from), b=positions.get(e.to), vertical=orientation==='vertical';
      const x=a.x+(vertical?110:220),y=a.y+(vertical?nodeHeight(byId.get(e.from)):35),end=b.x+(vertical?110:0),ey=b.y+(vertical?0:35);
      const path=vertical?`M${x},${y} C${x},${y+20} ${end},${ey-20} ${end},${ey}`:`M${x},${y} C${x+25},${y} ${end-25},${ey} ${end},${ey}`;
      const label=e.hidden.length?`${e.hidden.length} hidden: ${e.hidden.map(id=>byId.get(id).name).join(' → ')}`:`${byId.get(e.from).name} → ${byId.get(e.to).name} (${e.link_type}${e.primary?'':', extra link'}) · ${e.details?.source_interface_name||'Unknown port'} → ${e.details?.target_interface_name||'Unknown port'}${e.details?.speed_mbps?' · '+e.details.speed_mbps+' Mbps ('+(e.details.speed_source||'recorded')+')':''} · ${e.details?.vlan_mode||'VLAN mode unknown'} · ${e.details?.admin_status||'unknown'} (recorded)`;
      return `<g class="topology-link ${linkSpeedClass(e)} ${e.hidden.length?'compressed':''} ${!e.primary?'secondary':''} ${e.link_type==='wireless'?'wireless':''} ${e.link_type==='virtual'?'virtual':''}" data-link="${i}" tabindex="0" role="button" aria-label="${attr(label)}"><title>${esc(label)}</title><path d="${path}"/><path class="hit" d="${path}"/>${e.hidden.length?`<text x="${x+10}" y="${y-8}">+${e.hidden.length} hidden</text>`:''}</g>`;
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
    }).join('')+visibleVpns.map((v,i)=>{
      const p=vpnPositions[i], local=positions.get(v.device_id);
      const label=v.remote.kind==='endpoint'?v.remote.name:v.remote.clinic_name+' · '+v.remote.site_name;
      return `${local?`<path class="topology-vpn-line" d="M${local.x+220},${local.y+35} L${p.x},${p.y+35}"/>`:''}<g class="topology-device topology-vpn" transform="translate(${p.x},${p.y})" tabindex="0" role="button" data-vpn-canvas="${v.vpn_id}" aria-label="Open VPN ${attr(label)}"><title>${esc(label)}</title><rect width="220" height="80" rx="9"/><text x="10" y="22">🔒 ${esc(shorten(label,25))}</text><text class="muted-label" x="10" y="43">${esc(shorten(v.name||'VPN tunnel'))}</text><text class="muted-label" x="10" y="64">${esc(v.status_label||v.status)}${!local&&v.device_id?' · local device hidden':''}</text></g>`;
    }).join('');
    scene.querySelectorAll('[data-open]').forEach(el=>el.onclick=()=>actions.device(Number(el.dataset.open)));
    scene.querySelectorAll('[data-service]').forEach(el=>el.onclick=()=>actions.service(Number(el.dataset.service)));
    scene.querySelectorAll('[data-network]').forEach(el=>el.onclick=()=>actions.network(Number(el.dataset.network)));
    scene.querySelectorAll('[data-review]').forEach(el=>el.onclick=()=>{reviewDevice=Number(el.dataset.review);reportLimit=50;showReport();const review=body.querySelector('#topology-review');review.open=true;review.scrollIntoView({block:'start'});});
    scene.querySelectorAll('[data-vpn-canvas]').forEach(el=>el.onclick=()=>actions.vpn(Number(el.dataset.vpnCanvas)));
    scene.querySelectorAll('[data-vpn-canvas]').forEach(el=>{const v=visibleVpns.find(v=>v.vpn_id===Number(el.dataset.vpnCanvas));el.classList.add(vpnDisplayClass(v.status));if(el.previousElementSibling?.classList.contains('topology-vpn-line'))el.previousElementSibling.classList.add(vpnDisplayClass(v.status));el.setAttribute('aria-label',el.getAttribute('aria-label')+` · Recorded ${v.status||'unknown'}, not live monitoring`);});
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
    assignmentHighlight();
    vlanDetails();
    results();
    scene.querySelectorAll('[data-device]').forEach(el=>el.classList.toggle('path-dim',!!tracedPath&&!tracedPath.includes(Number(el.dataset.device))));
    scene.querySelectorAll('[data-link]').forEach(el=>el.classList.toggle('path-dim',!!tracedPath&&!edgeOnPath(graph.edges[Number(el.dataset.link)],tracedPath)));
    scene.querySelectorAll('[data-vpn-canvas]').forEach(el=>el.classList.toggle('path-dim',tracedVpn!==null&&Number(el.dataset.vpnCanvas)!==tracedVpn));
    const groupHost=body.querySelector('#topology-groups');
    groupHost.innerHTML=groups.map(g=>`<div><button class="btn btn-sm" data-group="${g.id}" aria-expanded="${!foldedGroups.has(g.id)}"><span class="vlan-dot" style="background:${attr(g.color)}"></span>${esc(g.name)} · ${g.device_ids.length} devices · ${foldedGroups.has(g.id)?'Expand':'Collapse'}</button><button class="btn btn-sm" data-group-edit="${g.id}">Edit ${esc(g.name)}</button><button class="btn btn-sm" data-group-delete="${g.id}">Delete ${esc(g.name)}</button><p class="help">${esc(g.description)}</p></div>`).join('');
    groupHost.querySelectorAll('[data-group]').forEach(b=>b.onclick=()=>{const id=Number(b.dataset.group);foldedGroups.has(id)?foldedGroups.delete(id):foldedGroups.add(id);save();draw();});
    groupHost.querySelectorAll('[data-group-edit]').forEach(b=>b.onclick=()=>editTopologyGroup(actions.reportContext.clinic_id,groups.find(g=>g.id===Number(b.dataset.groupEdit)),actions.refresh).catch(e=>toast(e.message,'error')));
    groupHost.querySelectorAll('[data-group-delete]').forEach(b=>b.onclick=async()=>{if(!await confirmDialog('Delete this presentation group? Devices and connections will remain unchanged.'))return;try{await api.del(`/api/clinics/${actions.reportContext.clinic_id}/topology/groups/${b.dataset.groupDelete}`);actions.refresh();}catch(e){toast(e.message,'error');}});
  };
  const results = () => {
    const q=search.value.trim().toLowerCase(), host=body.querySelector('#topology-results');
    if(!q){host.innerHTML='';return;}
    const matches=all.filter(n=>matchesTopologySearch(n,q,vlanCatalog));
    host.innerHTML=`<span class="muted small">${matches.length} matches${matches.length>30?' · showing first 30':''}</span>`+matches.slice(0,30).map(n=>`<button class="btn btn-sm" data-result="${n.id}">${esc(n.name)}${positions.has(n.id)?'':' · Reveal'}</button>`).join('');
    host.querySelectorAll('[data-result]').forEach(b=>b.onclick=()=>{
      const id=Number(b.dataset.result);hidden.delete(byId.get(id).device_type);
      quickFilter='';body.querySelector('#topology-quick-filter').value='';
      subnet='';body.querySelector('#topology-subnet').value='';groups.filter(g=>g.device_ids.includes(id)).forEach(g=>foldedGroups.delete(g.id));
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
  const vpnOptions=document.createElement('optgroup');vpnOptions.label='VPN remote endpoints (documented tunnel)';
  for(const v of topo.vpn||[]){const option=document.createElement('option');option.value=`vpn:${v.vpn_id}`;option.textContent=(v.remote.kind==='endpoint'?v.remote.name:v.remote.clinic_name+' · '+v.remote.site_name)+` · ${v.name||'VPN'} (${v.status||'unknown'})`;vpnOptions.append(option);}
  body.querySelector('#topology-path-target').append(vpnOptions);
  for(const side of ['source','target']) {
    const endpoint=body.querySelector(`#topology-path-${side}`),label=document.createElement('label');
    label.textContent=side==='source'?'Source VLAN':'Destination VLAN';
    const select=document.createElement('select');select.id=`topology-path-${side}-vlan`;label.append(select);endpoint.closest('label').after(label);
    const update=()=>{const nodes=side==='source'?all.filter(n=>String(n.id)===endpoint.value):destinationDevices(all,endpoint.value);const ids=new Set(nodes.flatMap(n=>(n.vlan_memberships||[]).map(m=>m.vlan_id)));select.innerHTML='<option value="">Automatic (single VLAN only)</option>'+vlanCatalog.filter(v=>ids.has(v.id)).map(v=>`<option value="${v.id}">${v.tag} · ${esc(v.name)}</option>`).join('');label.hidden=ids.size<=1;};
    endpoint.addEventListener('change',update);update();
  }
  body.querySelector('#topology-trace').onclick=()=>{
    const source=Number(body.querySelector('#topology-path-source').value),target=body.querySelector('#topology-path-target').value;
    const vpn=target.startsWith('vpn:')?(topo.vpn||[]).find(v=>String(v.vpn_id)===target.slice(4)):null;
    tracedVpn=vpn?.vpn_id??null;
    if(vpn){showVpn=true;vpnOnlyUp=false;body.querySelector('#topology-vpn-up').checked=false;body.querySelector('#topology-show-vpn').checked=true;save();}
    const result=vpn?traceVpn(all,edges,source,vpn):traceDestination(all,edges,source,target,vlanCatalog,{sourceVlan:body.querySelector('#topology-path-source-vlan').value,targetVlan:body.querySelector('#topology-path-target-vlan').value});
    tracedPath=result.path;draw();
    const host=body.querySelector('#topology-path-result');
    const explanation=target.startsWith('subnet:')?`Subnet destination: nearest member with a documented path, respecting configured VLAN gateways. ${result.connectedCount} of ${result.candidateCount} members have a documented chain.`:target.startsWith('service:')?'Service destination: showing its host device, not verification that the service or its ports are reachable.':'';
    host.innerHTML=`<p>${esc(explanation)}</p>`+(tracedPath?'<p>Documented adjacency only — reachability unverified.</p>'+tracedPath.map(id=>`<button class="btn btn-sm" data-path-device="${id}">${esc(byId.get(id).name)}</button>`).join(' → '):'<p>No documented connection chain found in this view. This does not prove the devices cannot communicate.</p>');
    host.querySelectorAll('[data-path-device]').forEach(b=>b.onclick=()=>{const id=Number(b.dataset.pathDevice);if(positions.has(id))focus(id);else actions.device(id);});
    if(!vpn&&result.warning){const note=document.createElement('p');note.textContent=result.warning;host.append(note);}
    if(vpn){const note=document.createElement('p');note.textContent=result.warning;host.append(note);const button=document.createElement('button');button.className='btn btn-sm';button.textContent='Inspect VPN tunnel and remote endpoint';button.onclick=()=>actions.vpn(vpn.vpn_id);host.append(button);}
    if(tracedPath?.length>1){const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Documented VLAN memberships along this chain';details.append(summary);
      const note=document.createElement('p');note.textContent='Memberships are device-level documentation, not proof of carried VLANs or inter-VLAN routing. Use connection details to inspect ports and trunks.';details.append(note);
      for(const id of tracedPath){const node=byId.get(id),tags=new Set((node.vlan_memberships||[]).map(m=>m.vlan_id));const row=document.createElement('p');row.textContent=node.name+': '+(vlanCatalog.filter(v=>tags.has(v.id)).map(v=>`${v.tag} · ${v.name}`).join(', ')||'VLAN membership unknown');details.append(row);}host.append(details);
    }
  };
  body.querySelector('#topology-clear-trace').onclick=()=>{tracedPath=null;tracedVpn=null;body.querySelector('#topology-path-result').innerHTML='';draw();};
  body.querySelector('#topology-new-group').onclick=()=>editTopologyGroup(actions.reportContext.clinic_id,null,actions.refresh).catch(e=>toast(e.message,'error'));
  body.querySelector('#topology-subnet').onchange=e=>{subnet=e.target.value;draw();};
  body.querySelector('#topology-routing').onclick=actions.routing;
  body.querySelector('#topology-remote-trace').onclick=()=>openRemoteTrace(actions.reportContext.clinic_id,all).catch(e=>toast(e.message,'error'));
  body.querySelector('#topology-import').onclick=actions.import;
  body.querySelector('#topology-history').onclick=actions.history;
  body.querySelectorAll('[data-export]').forEach(b=>b.onclick=()=>exportTopology({scene,graph,context:{...actions.reportContext,perspective,orientation,hidden_types:[...hidden],selected_vlans:[...selectedVlans],vlan_only:vlanOnly,show_vpn:showVpn,vpn_only_recorded_up:vpnOnlyUp,quick_filter:quickFilter,subnet,collapsed_groups:[...foldedGroups],search_only:searchOnly,search:search.value,vpn:displayedVpns(topo.vpn||[],showVpn,vpnOnlyUp),positions:Object.fromEntries(positions)},format:b.dataset.export}));
  body.querySelector('#topology-perspective').onchange=e=>{save(e.target.value);actions.refresh();};
  const report=body.querySelector('#topology-documentation');
  let reportLimit=50,reviewDevice=null;
  const showReport=()=>{
    const issues=(topo.documentation||[]).filter(i=>reviewDevice===null||(i.kind==='device'&&i.id===reviewDevice)||(i.kind==='connection'&&(i.parent===reviewDevice||i.child===reviewDevice)));
    report.innerHTML=issues.slice(0,reportLimit).map((issue,i)=>`<p><button class="btn btn-sm" data-issue="${i}">${esc(issue.name)}</button> ${esc(issue.message)}</p>`).join('')||'<p>No documentation gaps detected by these checks.</p>';
    report.querySelectorAll('[data-issue]').forEach(b=>b.onclick=()=>{const issue=issues[Number(b.dataset.issue)];if(issue.kind==='connection')actions.connection(issue.parent,issue.child);else if(issue.kind==='vlan')actions.vlans();else if(['services','uplink'].includes(issue.code))actions.device(issue.id);else actions.network(issue.id);});
    if(reviewDevice!==null){const back=document.createElement('button');back.className='btn btn-sm';back.textContent='All documentation issues';back.onclick=()=>{reviewDevice=null;reportLimit=50;showReport();};report.prepend(back);const title=document.createElement('h3');title.textContent=byId.get(reviewDevice)?.name||'Device documentation';report.prepend(title);}
    if(issues.length>reportLimit){const more=document.createElement('button');more.className='btn';more.textContent='Show next 50';more.onclick=()=>{reportLimit+=50;showReport();};report.append(more);}
  };
  showReport();
  body.querySelector('#topology-orientation').onchange=e=>{orientation=e.target.value;savedPositions=loadPositions();save();draw();};
  const manualControl=body.querySelector('#topology-manual');
  manualControl.disabled=perspective!=='logical';
  manualControl.parentElement.title=perspective!=='logical'?'Grouped views use automatic placement; use Logical network for manual positioning.':'Drag device cards, or focus a device and use arrow keys. Positions are saved in this browser.';
  manualControl.onchange=e=>{manualMode=e.target.checked;canvas.classList.toggle('manual-positioning',manualMode);};
  body.querySelector('#topology-auto-layout').onclick=()=>{savedPositions={};savePositions();draw();};
  minimap.onclick=e=>{
    if(e.detail===0){fit();return;}
    const r=miniSvg.getBoundingClientRect(),x=miniBounds.x+(e.clientX-r.left)/r.width*miniBounds.width,y=miniBounds.y+(e.clientY-r.top)/r.height*miniBounds.height;
    view.x=canvas.clientWidth/2-x*view.z;view.y=canvas.clientHeight/2-y*view.z;camera();
  };
  minimap.onkeydown=e=>{if(e.key.startsWith('Arrow')){e.preventDefault();view.x+=e.key==='ArrowLeft'?80:e.key==='ArrowRight'?-80:0;view.y+=e.key==='ArrowUp'?80:e.key==='ArrowDown'?-80:0;camera();}};
  body.querySelector('#topology-vlan-only').onchange=e=>{vlanOnly=e.target.checked;save();draw();};
  const clearVlans=()=>{selectedVlans.clear();body.querySelectorAll('[data-vlan]').forEach(b=>b.setAttribute('aria-pressed','false'));};
  body.querySelector('#topology-vlan-clear').onclick=()=>{clearVlans();save();draw();};
  search.oninput=()=>searchOnly?draw():results();
  body.querySelector('#topology-search-only').onchange=e=>{searchOnly=e.target.checked;draw();};
  body.querySelector('#topology-quick-filter').onchange=e=>{quickFilter=e.target.value;draw();};
  body.querySelector('#topology-show-vpn').onchange=e=>{showVpn=e.target.checked;save();draw();};
  body.querySelector('#topology-vpn-up').onchange=e=>{vpnOnlyUp=e.target.checked;draw();};
  body.querySelector('#topology-reset').addEventListener('click',()=>{vpnOnlyUp=false;body.querySelector('#topology-vpn-up').checked=false;},true);
  body.querySelectorAll('[data-type]').forEach(c=>c.onchange=()=>{c.checked?hidden.delete(c.dataset.type):hidden.add(c.dataset.type);save();draw();});
  body.querySelector('.topology-type-menu input[type=search]').oninput=e=>body.querySelectorAll('[data-type-row]').forEach(r=>r.hidden=!r.dataset.typeRow.includes(e.target.value.toLowerCase()));
  body.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{hidden=new Set(b.dataset.filter==='none'?types.map(([t])=>t):[]);save();syncChecks();draw();});
  body.querySelector('#topology-collapse').onclick=()=>{collapsed=new Set(all.filter(n=>graph.counts.get(n.id)>0).map(n=>n.id));save();draw();};
  body.querySelector('#topology-expand').onclick=()=>{collapsed.clear();foldedGroups.clear();save();draw();};
  body.querySelector('#topology-reset').onclick=()=>{hidden.clear();collapsed.clear();foldedGroups.clear();subnet='';body.querySelector('#topology-subnet').value='';clearVlans();vlanOnly=false;quickFilter='';searchOnly=false;body.querySelector('#topology-quick-filter').value='';body.querySelector('#topology-search-only').checked=false;body.querySelector('#topology-vlan-only').checked=false;search.value='';save();syncChecks();draw();};
  body.querySelector('#topology-edit').onclick=actions.edit;
  body.querySelectorAll('[data-vpn-link]').forEach(b=>b.onclick=()=>actions.vpn(Number(b.dataset.vpnLink)));
  body.querySelectorAll('[data-camera]').forEach(b=>b.onclick=()=>{const a=b.dataset.camera;if(a==='fit')fit();else zoom(a==='in'?1.25:a==='out'?.8:1/view.z);});
  canvas.addEventListener('wheel',e=>{e.preventDefault();const r=canvas.getBoundingClientRect();zoom(e.deltaY<0?1.1:1/1.1,e.clientX-r.left,e.clientY-r.top);},{passive:false});
  canvas.addEventListener('pointerdown',e=>{
    const device=e.target.closest('[data-device]');
    if(e.button===0&&manualMode&&device&&!assigning){const id=Number(device.dataset.device);drag={id,x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY};canvas.setPointerCapture(e.pointerId);e.preventDefault();return;}
    if(e.button!==0||e.target.closest('[role=button],button'))return;
    drag={x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY};canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener('pointermove',e=>{if(!drag)return;
    const dx=e.clientX-drag.x,dy=e.clientY-drag.y;
    if(drag.id){const p=positions.get(drag.id);savedPositions[drag.id]={x:Math.max(-100000,Math.min(100000,p.x+dx/view.z)),y:Math.max(-100000,Math.min(100000,p.y+dy/view.z))};}
    else {view.x+=dx;view.y+=dy;}
    drag.x=e.clientX;drag.y=e.clientY;if(Math.hypot(e.clientX-drag.startX,e.clientY-drag.startY)>4)suppressClick=true;
    if(drag.id)draw(false);else camera();});
  canvas.addEventListener('pointerup',()=>{if(drag?.id)savePositions();drag=null;setTimeout(()=>suppressClick=false,0);});
  canvas.addEventListener('pointercancel',()=>{drag=null;suppressClick=false;});
  canvas.addEventListener('click',e=>{if(suppressClick){e.preventDefault();e.stopImmediatePropagation();}},true);
  canvas.addEventListener('keydown',e=>{
    const device=e.target.closest('[data-device]');
    if(manualMode&&device&&['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){
      e.preventDefault();const id=Number(device.dataset.device),p=positions.get(id),step=e.shiftKey?50:10;
      savedPositions[id]={x:p.x+(e.key==='ArrowLeft'?-step:e.key==='ArrowRight'?step:0),y:p.y+(e.key==='ArrowUp'?-step:e.key==='ArrowDown'?step:0)};
      savedPositions=validPositions(savedPositions);savePositions();draw(false);scene.querySelector(`[data-open="${id}"]`)?.focus();return;
    }
    if(e.target!==canvas)return;
    if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','-','='].includes(e.key)){e.preventDefault();if(e.key==='+'||e.key==='=')zoom(1.25);else if(e.key==='-')zoom(.8);else {view.x+=e.key==='ArrowLeft'?40:e.key==='ArrowRight'?-40:0;view.y+=e.key==='ArrowUp'?40:e.key==='ArrowDown'?-40:0;camera();}}
  });
  draw();
}
