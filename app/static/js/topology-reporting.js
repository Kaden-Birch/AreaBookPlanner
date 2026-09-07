import { api, devices } from './api.js';
import { esc, attr, openModal, toast, showFormError } from './ui.js';
import { csvCell, viewData } from './topology-export-data.js';

export function download(content,name,type='application/json') {
  const url=URL.createObjectURL(new Blob([content],{type}));
  const a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}

const templates={
  devices:'name,device_type,ip_address,mac_address,serial,model,rack,rack_room,rack_position,notes,uplink_name\nExample switch,switch,192.0.2.1,,,,Rack A,Server room,20,,\n',
  vlans:'tag,name,subnets,description,color,dhcp_mode,notes\n20,Production,192.0.2.0/24;2001:db8:20::/64,,#547ee8,unknown,\n',
  interfaces:'device_name,interface_name,mac_address,address,prefix_length,vlan_tag,mode,hostname,notes\nExample switch,LAN,,192.0.2.1,24,20,access,,\n'
};
export async function openTopologyImport({clinic,site,onChanged}) {
  let sites;
  try{sites=(await devices.sites(clinic.id)).sites;}catch(e){toast(e.message,'error');return;}
  const modal=openModal({title:'Import topology CSV',size:'modal-lg',body:`<p>Additive import only: existing devices, VLANs and interfaces are never overwritten. Choose one site. Up to 500 rows / 1 MB. Create devices and VLANs before importing their interfaces.</p><p class="help">Do not include passwords or secrets. Templates contain example rows; replace them before importing.</p><form>
    <div class="field-row"><label>Site<select name="site">${sites.map(s=>`<option value="${attr(s.id)}" ${String(s.id)===String(site==='all'||!site?'main':site)?'selected':''}>${esc(s.name)}</option>`).join('')}</select></label>
    <label>Import type<select name="kind"><option value="devices">Devices</option><option value="vlans">VLANs</option><option value="interfaces">Interfaces / addresses</option></select></label></div>
    <button class="btn" type="button" data-template>Download CSV template</button><label>CSV file<input type="file" accept=".csv,text/csv" data-file></label>
    <label>Or paste CSV<textarea name="csv_text" rows="8" required maxlength="1000000"></textarea></label><button class="btn" type="submit">Preview import</button></form><div data-preview aria-live="polite"></div>`,
    footer:'<button class="btn" data-close>Cancel</button><button class="btn btn-primary" data-commit disabled>Import reviewed rows</button>'});
  const form=modal.body.querySelector('form'),host=modal.body.querySelector('[data-preview]'),commit=modal.root.querySelector('[data-commit]');
  let preview=null,revision=0,busy=false;
  const invalidate=()=>{revision++;preview=null;commit.disabled=true;host.innerHTML='';};
  form.oninput=invalidate;form.onchange=invalidate;
  form.querySelector('[data-template]').onclick=()=>download(templates[form.elements.kind.value],'topology-'+form.elements.kind.value+'.csv','text/csv');
  form.querySelector('[data-file]').onchange=async e=>{
    e.stopPropagation();
    invalidate();const file=e.target.files[0];if(!file)return;
    if(file.size>1000000){showFormError(form,'CSV must be no larger than 1 MB');return;}
    const current=revision;const text=await file.text();if(current===revision)form.elements.csv_text.value=text;
  };
  form.onsubmit=async e=>{
    e.preventDefault();if(busy||!form.reportValidity())return;invalidate();busy=true;
    const version=revision,payload=Object.fromEntries(new FormData(form));
    try {
      const result=await api.post(`/api/clinics/${clinic.id}/topology/import/preview`,payload);
      if(version!==revision)return;
      preview={...payload,preview_token:result.preview_token};commit.disabled=false;
      host.innerHTML=`<h3>${result.rows.length} rows validated — nothing saved yet</h3><div class="topology-import-preview">${result.rows.map(r=>`<p>Row ${r.row}: ${esc(r.action)} — ${esc(r.name)}</p>`).join('')}</div>`;
    }catch(error){showFormError(form,error.message);}finally{busy=false;}
  };
  commit.onclick=async()=>{
    if(!preview||busy)return;busy=true;commit.disabled=true;
    try{const result=await api.post(`/api/clinics/${clinic.id}/topology/import/commit`,preview);modal.close();toast(`Imported ${result.imported_rows} rows`,'success');onChanged?.();}
    catch(error){showFormError(form,error.message);invalidate();}finally{busy=false;}
  };
  modal.root.querySelector('[data-close]').onclick=()=>modal.close();
}

const changeHTML=changes=>changes.map(c=>`<details><summary>${esc(c.action)} · ${esc(c.table)} · ${esc(c.name)}</summary><table><thead><tr><th>Field</th><th>Before</th><th>After</th></tr></thead><tbody>${Object.entries(c.fields).map(([key,v])=>`<tr><td>${esc(key)}</td><td>${esc(JSON.stringify(v.before))}</td><td>${esc(JSON.stringify(v.after))}</td></tr>`).join('')}</tbody></table></details>`).join('')||'<p>No changes.</p>';
export async function openTopologyHistory({clinic,site}) {
  site=site||'all';const base=`/api/clinics/${clinic.id}/topology`,query='?'+new URLSearchParams({site});
  const modal=openModal({title:'Topology versions & audit',size:'modal-lg',body:`<p>Saved versions cover the selected site’s complete local documentation, independent of display filters. Read-only comparisons; no restore or rollback. Audit records start with this upgrade.</p><form><label>Version label<input name="label" required maxlength="120" placeholder="Before switch replacement"></label><button class="btn" type="submit">Save current version</button></form><div data-versions></div><h3>Web edit audit</h3><div data-audit></div><button class="btn" data-more>Load audit records</button>`,
    footer:'<button class="btn" data-close>Close</button>'});
  const form=modal.body.querySelector('form'),host=modal.body.querySelector('[data-versions]'),audit=modal.body.querySelector('[data-audit]'),more=modal.body.querySelector('[data-more]');
  let list=[],before=null;
  const refresh=async()=>{
    list=await api.get(base+'/versions'+query);
    host.innerHTML=`<h3>Saved versions (latest 200)</h3><label>Compare to<select data-target><option value="">Current documentation</option>${list.map(v=>`<option value="${v.id}">${esc(v.label)} · ${esc(v.created_at)}</option>`).join('')}</select></label>`+
      list.map(v=>`<p><strong>${esc(v.label)}</strong> · ${esc(v.actor)} · ${esc(v.created_at)} UTC <button class="btn btn-sm" data-compare="${v.id}">Compare</button><button class="btn btn-sm" data-download="${v.id}">JSON</button></p>`).join('');
    host.querySelectorAll('[data-compare]').forEach(b=>b.onclick=async()=>{
      try{const other=host.querySelector('[data-target]').value,result=await api.get(base+'/versions/'+b.dataset.compare+'/compare'+query+(other?'&other='+other:''));
        const detail=openModal({title:'Version comparison',size:'modal-lg',body:changeHTML(result.changes),footer:'<button class="btn" data-close>Close</button>'});detail.root.querySelector('[data-close]').onclick=()=>detail.close();
      }catch(e){toast(e.message,'error');}
    });
    host.querySelectorAll('[data-download]').forEach(b=>b.onclick=async()=>{try{download(JSON.stringify(await api.get(base+'/versions/'+b.dataset.download+query),null,2),'topology-version-'+b.dataset.download+'.json');}catch(e){toast(e.message,'error');}});
  };
  form.onsubmit=async e=>{e.preventDefault();const button=form.querySelector('button');if(button.disabled||!form.reportValidity())return;button.disabled=true;
    try{await api.post(base+'/versions',{label:form.elements.label.value,site});form.reset();await refresh();}catch(error){showFormError(form,error.message);}finally{button.disabled=false;}};
  more.onclick=async()=>{
    more.disabled=true;
    try{const data=await api.get(base+'/audit'+query+(before?'&before='+before:''));before=data.next_before;
      audit.insertAdjacentHTML('beforeend',data.items.map(item=>`<details><summary>${esc(item.created_at)} UTC · ${esc(item.actor)} · ${esc(item.method)} ${esc(item.request_path)} · ${item.changes.length} changes</summary>${changeHTML(item.changes)}</details>`).join('')||'<p>No matching changes in this page.</p>');
      more.hidden=!before;
    }catch(e){toast(e.message,'error');}finally{more.disabled=false;}
  };
  modal.root.querySelector('[data-close]').onclick=()=>modal.close();
  try{await refresh();await more.onclick();}catch(e){toast(e.message,'error');}
}

export function exportTopology({scene,graph,context,format}) {
  const stamp={...context,exported_at:new Date().toISOString(),note:'Filtered presentation; derived links are not physical cables.'};
  if(format==='json'){download(JSON.stringify(viewData(graph,stamp),null,2),'topology-view.json');return;}
  if(format==='csv'){
    const fields=['id','name','device_type','ip_address','location_name','status'];
    download([fields.join(','),...graph.nodes.map(n=>fields.map(f=>csvCell(n[f])).join(','))].join('\r\n'),'topology-view.csv','text/csv');return;
  }
  const box=scene.getBBox(),width=Math.max(240,box.width+40),height=Math.max(160,box.height+40);
  const clone=scene.cloneNode(true),source=[scene,...scene.querySelectorAll('*')],target=[clone,...clone.querySelectorAll('*')];
  source.forEach((el,i)=>{
    const style=getComputedStyle(el);
    for(const prop of ['fill','stroke','stroke-width','stroke-dasharray','opacity','font-size','font-family','font-weight'])target[i].style.setProperty(prop,style.getPropertyValue(prop));
    target[i].removeAttribute('tabindex');target[i].removeAttribute('role');
  });
  clone.setAttribute('transform',`translate(${20-box.x},${20-box.y})`);
  const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="100%" height="100%" fill="${getComputedStyle(scene.closest('.topology-canvas')).backgroundColor}"/>${new XMLSerializer().serializeToString(clone)}</svg>`;
  if(format==='svg'){download(svg,'topology-view.svg','image/svg+xml');return;}
  if(format==='print'){
    const modal=openModal({title:'Printable topology',size:'modal-lg',body:`<h1>${esc(context.clinic_name)}</h1><p>${esc(context.site)} · ${esc(context.perspective)} · ${esc(stamp.exported_at)} · ${graph.nodes.length} visible devices</p><p>${esc(stamp.note)}</p><p>Speed: red &lt;1 Gb; blue 1–&lt;2.5 Gb; green 2.5–&lt;10 Gb; orange ≥10 Gb; purple dots virtual; grey unknown/shortcut.</p>${svg}`,
      footer:'<button class="btn" data-close>Close</button><button class="btn btn-primary" data-print>Print / Save as PDF</button>',
      onClose:()=>document.body.classList.remove('topology-printing')});
    modal.root.classList.add('topology-print-preview');document.body.classList.add('topology-printing');
    modal.root.querySelector('[data-close]').onclick=()=>modal.close();
    modal.root.querySelector('[data-print]').onclick=()=>window.print();return;
  }
  const url=URL.createObjectURL(new Blob([svg],{type:'image/svg+xml'})),img=new Image();
  img.onload=()=>{
    const scale=Math.min(2,8192/width,8192/height,Math.sqrt(16000000/(width*height)));
    const canvas=document.createElement('canvas');canvas.width=Math.ceil(width*scale);canvas.height=Math.ceil(height*scale);
    canvas.getContext('2d').drawImage(img,0,0,canvas.width,canvas.height);
    canvas.toBlob(blob=>{
      if(!blob){toast('Unable to create image','error');return;}
      const u=URL.createObjectURL(blob);
      const preview=openModal({title:'PNG export preview',size:'modal-lg',body:`<p>Filtered topology · ${canvas.width} × ${canvas.height} pixels</p><img src="${u}" alt="Exported topology" style="max-width:100%;height:auto">`,
        footer:`<button class="btn" data-close>Close</button><a class="btn btn-primary" href="${u}" download="topology-view.png">Download PNG</a>`,
        onClose:()=>URL.revokeObjectURL(u)});
      preview.root.querySelector('[data-close]').onclick=()=>preview.close();
    },'image/png');
    URL.revokeObjectURL(url);
  };
  img.onerror=()=>{URL.revokeObjectURL(url);toast('Unable to render image; try SVG export','error');};img.src=url;
}
