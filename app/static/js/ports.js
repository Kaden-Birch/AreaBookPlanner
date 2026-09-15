import {api} from './api.js';
import {esc,attr,openModal,toast,confirmDialog} from './ui.js';
import {saveNetwork,openNetwork} from './network.js';
import {assignMembership} from './vlan-assignment.js';
import {openConnection} from './connections.js';
import {connectPort} from './port-connect.js';

export const speedColour=s=>!s?'#8a8f98':s<1000?'#d9342b':s<2500?'#547ee8':s<10000?'#22a06b':'#ed8b23';
export const speedLabel=s=>s?(s>=1000?`${s/1000} Gb`:`${s} Mb`):'Unknown speed';
export function parseSpeeds(text,field='Supported speeds') {
  const input=String(text??'').normalize('NFKC').trim();
  if(!input)return [];
  const tokens=input.split(/[,;\n\r]+/).map(s=>s.trim()).filter(Boolean);
  const values=tokens.map(token=>{
    const match=token.match(/^(\d+(?:\.\d+)?)\s*(k|m|g|t)?\s*(?:b(?:it)?\s*(?:ps|\/s)?|be)?$/i)||token.match(/^(\d+(?:\.\d+)?)\s*(k|m|g|t)?$/i);
    if(!match)throw Error(`${field}: “${token}” is not a speed. Enter 1000, 2500, 10000 (Mbps), or 1 Gbps, 2.5 Gbps, 10 Gbps.`);
    const value=Number(match[1])*({k:0.001,m:1,g:1000,t:1000000}[(match[2]||'m').toLowerCase()]);
    if(!Number.isInteger(value)||value<1||value>10000000)throw Error(`${field}: “${token}” must represent a whole Mbps value between 1 and 10000000.`);
    return value;
  });
  if(!values.length)throw Error(`${field}: enter a speed such as 1000, or leave the field empty for unknown.`);
  return [...new Set(values)].sort((a,b)=>a-b);
}
const connectors=['unknown','rj45','sfp','sfp+','qsfp','virtual','other'];

export function portGroupNames(interfaces) {
  return [...new Set([...interfaces].sort((a,b)=>a.id-b.id).map(i=>i.port_group||'Ports'))];
}

export async function openPorts({clinic,deviceId,onChanged,container=null}) {
  let data,catalog,selected=new Set(),anchor=null,busy=false,colour='speed';
  const pref=`port-colour:${(await api.get('/api/auth/me')).id}`;
  try{colour=localStorage.getItem(pref)||'speed';}catch{}
  const modal=container?{body:container,root:container}:openModal({title:'Ports & connections',size:'modal-lg',body:'Loading ports…',footer:'<button class="btn" data-close>Close</button>',onClose:()=>onChanged?.()});
  if(!container)modal.root.querySelector('[data-close]').onclick=()=>modal.close();
  const load=async()=>{[data,catalog]=await Promise.all([api.get(`/api/devices/${deviceId}/network`),api.get(`/api/clinics/${clinic.id}/vlans`)]);selected.clear();draw();};
  const save=async(rows)=>{if(busy)return false;busy=true;try{const result=await saveNetwork(deviceId,{interfaces:rows,expected_interfaces:data.interfaces});if(result){toast('Ports saved','success');await load();return true;}return false;}catch(e){toast(e.message,'error');return false;}finally{busy=false;}};
  const draw=()=>{
    if(!data.interfaces.length){
      modal.body.innerHTML='<p class="help">No interfaces recorded yet. Add a port group manually, or use Syncro import to fill missing network information.</p><button class="btn" id="port-add">+ Add port group</button>';
      modal.body.querySelector('#port-add').onclick=()=>capabilities(true);return;
    }
    const vlans=catalog.vlans.filter(v=>v.location_id===data.location_id);
    const groups=portGroupNames(data.interfaces);
    modal.body.innerHTML=`<p class="help">Documented configuration, not live monitoring. Click ports to select; Shift-click selects a range. Each group uses at most two rows.</p><div class="actions"><label>Colour by<select id="port-colour"><option value="speed" ${colour==='speed'?'selected':''}>Speed</option><option value="vlan" ${colour==='vlan'?'selected':''}>VLAN</option></select></label><button class="btn" id="port-add">+ Add port group</button><button class="btn" id="port-network">Network interfaces & addresses</button><button class="btn" id="port-all">Select all</button><button class="btn" id="port-clear">Clear selection</button></div><p class="help">${colour==='speed'?'Red <1 Gb · Blue 1–<2.5 Gb · Green 2.5–<10 Gb · Orange ≥10 Gb · Grey unknown. Connected ports use documented link speed; unused ports use capability.':'Port fill: access/native VLAN. Coloured markers: tagged VLANs. T = trunk. Grey = no untagged VLAN.'}</p>${groups.map(group=>{const ports=data.interfaces.filter(i=>(i.port_group||'Ports')===group).sort((a,b)=>a.port_order-b.port_order||a.id-b.id);return `<h3>${esc(group)}</h3><div class="port-scroll"><div class="port-grid" style="grid-template-columns:repeat(${Math.ceil(ports.length/2)},76px)">${ports.map(i=>{
      const links=data.connections.filter(c=>c.source_interface_id===i.id||c.target_interface_id===i.id),link=links[0];
      const capability=i.connector==='sfp'||i.connector==='sfp+'||i.connector==='qsfp'?i.supported_speeds.filter(s=>i.module_speeds?.includes(s)):i.supported_speeds;
      const speed=link?link.speed_mbps:Math.max(0,...capability),native=i.memberships.find(m=>['access','native'].includes(m.mode)),tags=i.memberships.filter(m=>m.mode==='tagged');
      const color=colour==='speed'?speedColour(speed):vlans.find(v=>v.id===native?.vlan_id)?.color||'#8a8f98';
      const info=`${i.name} · ${speedLabel(speed)} (${link?link.speed_source:'capability'}) · ${links.length?'Connected: '+links.map(c=>c.uplink_id===deviceId?c.target_device_name:c.source_device_name).join(', '):'No port-level connection documented'} · ${i.memberships.map(m=>`${vlans.find(v=>v.id===m.vlan_id)?.name||m.vlan_id} ${m.mode}`).join(', ')}`;
      return `<button type="button" class="port-square" data-port="${i.id}" aria-pressed="${selected.has(i.id)}" title="${attr(info)}" style="--port-colour:${attr(color)}"><strong>${esc(i.name)}</strong><small>${esc(colour==='speed'?speedLabel(speed):native?`VLAN ${vlans.find(v=>v.id===native.vlan_id)?.tag??'?'}`:'—')}</small><small>${tags.length?'T · ':''}${links.length?'● linked':'○'}</small>${colour==='vlan'?`<span>${tags.slice(0,3).map(m=>`<i class="vlan-dot" style="background:${attr(vlans.find(v=>v.id===m.vlan_id)?.color||'#888')}"></i>`).join('')}${tags.length>3?`+${tags.length-3}`:''}</span>`:''}</button>`;}).join('')}</div></div>`;}).join('')||'<p>No interfaces yet. Add a port group or use the network editor.</p>'}<h3>${selected.size} ports selected</h3><p class="help">Selection may have mixed configuration. Nothing changes until you apply an action.</p><div class="actions"><label>VLAN<select id="port-vlan">${vlans.map(v=>`<option value="${v.id}">${v.tag} · ${esc(v.name)}</option>`).join('')}</select></label><label>Action<select id="port-action"><option value="tagged">Add tagged VLAN</option><option value="remove">Remove selected VLAN</option><option value="access">Replace access/native VLAN</option><option value="native">Set native VLAN</option><option value="routed">Add routed membership</option></select></label><button class="btn" id="port-apply" ${selected.size&&vlans.length?'':'disabled'}>Apply VLAN</button><button class="btn" id="port-capability" ${selected.size?'':'disabled'}>Edit capabilities</button></div><div id="port-connections"></div>`;
    const rail=document.createElement('div');rail.className='port-group-rail';rail.setAttribute('aria-label','Port groups in creation order');
    const first=modal.body.querySelector('.port-scroll');if(first)first.previousElementSibling.before(rail);
    modal.body.querySelectorAll('.port-scroll').forEach(scroll=>{const section=document.createElement('section');section.className='port-group';const heading=scroll.previousElementSibling;section.append(heading,scroll);rail.append(section);});
    modal.body.querySelectorAll('.port-grid').forEach(grid=>{grid.style.gridTemplateColumns=`repeat(${Math.ceil(grid.children.length/2)},60px)`;grid.style.gridTemplateRows=`repeat(${Math.min(2,grid.children.length)},minmax(64px,auto))`;});
    modal.body.querySelector('#port-colour').onchange=e=>{colour=e.target.value;try{localStorage.setItem(pref,colour);}catch{}draw();};
    modal.body.querySelectorAll('[data-port]').forEach(b=>b.onclick=e=>{const id=Number(b.dataset.port),ids=[...modal.body.querySelectorAll('[data-port]')].map(x=>Number(x.dataset.port));if(e.shiftKey&&anchor!==null){const a=ids.indexOf(anchor),z=ids.indexOf(id);ids.slice(Math.min(a,z),Math.max(a,z)+1).forEach(x=>selected.add(x));}else{selected.has(id)?selected.delete(id):selected.add(id);anchor=id;}draw();if(!e.shiftKey&&!e.ctrlKey&&!e.metaKey)openNetwork({clinic,deviceId,interfaceId:id,onChanged:load});});
    modal.body.querySelector('#port-all').onclick=()=>{selected=new Set(data.interfaces.map(i=>i.id));draw();};modal.body.querySelector('#port-clear').onclick=()=>{selected.clear();draw();};
    modal.body.querySelector('#port-network').remove();
    modal.body.querySelector('.help').textContent='Click a port to edit its MAC, IPv4/IPv6 addresses, VLANs and notes. Ctrl/⌘-click selects ports for bulk changes; Shift-click selects a range. Groups use at most two rows.';
    modal.body.querySelector('#port-add').onclick=()=>capabilities(true);
    modal.body.querySelector('#port-capability').onclick=()=>capabilities(false);
    const vlanSelect=modal.body.querySelector('#port-vlan');vlanSelect.multiple=true;vlanSelect.size=Math.min(5,Math.max(2,vlans.length));
    const replace=document.createElement('option');replace.value='replace';replace.textContent='Replace all tagged VLANs';modal.body.querySelector('#port-action').append(replace);
    modal.body.querySelector('#port-apply').onclick=async()=>{const ids=[...vlanSelect.selectedOptions].map(o=>Number(o.value)),mode=modal.body.querySelector('#port-action').value;const indices=data.interfaces.flatMap((i,index)=>selected.has(i.id)?[index]:[]);
      if(!ids.length){toast('Select at least one VLAN.');return;}
      if(['access','native'].includes(mode)&&ids.length!==1){toast('Access/native mode requires exactly one VLAN.');return;}
      if(['access','native','remove','replace'].includes(mode)&&!await confirmDialog('Change VLAN membership on all selected ports? Existing address-VLAN associations may need review.',{okLabel:'Apply changes',danger:false}))return;
      let rows=structuredClone(data.interfaces);
      if(mode==='remove'||mode==='replace')for(const index of indices){const removed=rows[index].memberships.filter(m=>mode==='remove'?ids.includes(m.vlan_id):m.mode==='tagged'&&!ids.includes(m.vlan_id)).map(m=>m.vlan_id);rows[index].memberships=rows[index].memberships.filter(m=>!removed.includes(m.vlan_id));for(const a of rows[index].addresses)if(removed.includes(a.vlan_id))a.vlan_id=null;}
      if(['access','native'].includes(mode))for(const index of indices)rows[index].memberships=rows[index].memberships.filter(m=>!ids.includes(m.vlan_id));
      if(mode!=='remove')for(const id of ids)rows=assignMembership(rows,indices,id,mode==='replace'?'tagged':mode);
      await save(rows);
    };
    const host=modal.body.querySelector('#port-connections');
    if(selected.size===1){const button=document.createElement('button');button.className='btn';button.textContent='Connect selected port to device';button.onclick=()=>connectPort({clinic,deviceId,portId:[...selected][0],onChanged:load}).catch(e=>toast(e.message,'error'));host.append(button);}
    for(const link of data.connections.filter(c=>!selected.size||selected.has(c.source_interface_id)||selected.has(c.target_interface_id))){const b=document.createElement('button');b.className='btn';b.textContent=`${link.source_device_name||'Upstream'} · ${link.source_interface_name||'Unknown port'} → ${link.target_device_name||'Downstream'} · ${link.target_interface_name||'Unknown port'} · ${speedLabel(link.speed_mbps)} (${link.speed_source})`;b.onclick=()=>openConnection({clinic,parent:link.uplink_id,child:link.device_id,onChanged:load});host.append(b);}
  };
  const capabilities=adding=>{
    const single=!adding&&selected.size===1?data.interfaces.find(i=>selected.has(i.id)):null;
    const editor=openModal({title:adding?'Add port group':'Set selected port capabilities',body:`<form>${adding?'<label>Group name<input name="group" required placeholder="24 × GbE"></label><label>Number of ports<input name="count" type="number" min="1" max="96" value="24" required></label><label>Numbering<select name="numbering"><option value="rows">Sequential across rows</option><option value="pairs">Odd/even pairs</option></select></label>':''}<label>Connector<select name="connector">${connectors.map(c=>`<option ${single?.connector===c?'selected':''}>${c}</option>`).join('')}</select></label><label>Supported speeds (Mbps, comma-separated)<input name="speeds" value="${attr(single?.supported_speeds?.join(',')??(adding?'10,100,1000':''))}" placeholder="1000,2500,5000,10000"></label><label>Installed module speeds (SFP/SFP+/QSFP)<input name="module" value="${attr(single?.module_speeds?.join(',')||'')}" placeholder="Blank = module unknown"></label><p class="help">These are capabilities, not a measured link speed. Empty supported speeds means unknown. Bulk editing replaces capabilities on every selected port.</p></form>`,footer:'<button class="btn" data-cancel>Cancel</button><button class="btn btn-primary" data-save>Save</button>'});
    const speedHint=document.createElement('p');speedHint.className='help';speedHint.textContent='Examples: 1000 or 1000, 2500, 10000. Units also work: 1 Gbps, 2.5 Gbps, 10 Gbps. Leave module speeds blank if no module is documented.';editor.body.querySelector('form').prepend(speedHint);
    editor.root.querySelector('[data-cancel]').onclick=()=>editor.close();editor.root.querySelector('[data-save]').onclick=async()=>{const f=editor.body.querySelector('form');if(!f.reportValidity())return;try{const fields=Object.fromEntries(new FormData(f)),speeds=parseSpeeds(fields.speeds),module=fields.module.trim()?parseSpeeds(fields.module,'Installed module speeds'):null;let rows=structuredClone(data.interfaces);
      if(adding){const count=Number(fields.count),group=fields.group.trim();if(!group||rows.some(i=>i.port_group===group))throw Error('Use a new, nonempty group name.');if(rows.length+count>100)throw Error('A device supports up to 100 documented interfaces.');for(let index=0;index<count;index++){const number=fields.numbering==='pairs'?(index<Math.ceil(count/2)?index*2+1:(index-Math.ceil(count/2))*2+2):index+1;rows.push({name:`${group} ${number}`,port_group:group,port_order:index,connector:fields.connector,supported_speeds:speeds,module_speeds:module,addresses:[],memberships:[]});}}
      else rows=rows.map(i=>selected.has(i.id)?{...i,connector:fields.connector,supported_speeds:speeds,module_speeds:module}:i);
      if(await save(rows))editor.close();}catch(e){toast(e.message,'error');}};
  };
  try{await load();}catch(e){modal.body.textContent=e.message;}
}
