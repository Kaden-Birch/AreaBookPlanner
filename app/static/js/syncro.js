import {api} from './api.js';
import {esc,attr,openModal,toast,navigate} from './ui.js';

export async function syncroSettings(container){
  const settings=await api.get('/api/syncro/settings');
  const card=document.createElement('section');card.className='card mb';
  card.innerHTML=`<h2>Syncro · read-only integration</h2><p>Administrator-managed imports. Credentials stay on the server. Use a dedicated read-only key.</p><label>Syncro subdomain<input name="subdomain" value="${attr(settings.subdomain)}" placeholder="your-company"></label><label>API key<input name="key" type="password" autocomplete="off" placeholder="${settings.configured?'Saved — leave blank to keep':'Enter read-only key'}"></label><div class="actions"><button class="btn" data-save>Save connection</button><button class="btn" data-test>Test connection</button><button class="btn" data-import>Import from Syncro</button><button class="btn" data-clear>Remove key</button></div><p role="status"></p>`;
  container.append(card);
  const status=card.querySelector('[role=status]');
  card.querySelector('[data-save]').onclick=async()=>{try{const key=card.querySelector('[name=key]');await api.put('/api/syncro/settings',{subdomain:card.querySelector('[name=subdomain]').value.trim(),...(key.value?{api_key:key.value}:{})});key.value='';status.textContent='Connection saved.';}catch(e){status.textContent=e.message;}};
  card.querySelector('[data-clear]').onclick=async()=>{try{await api.put('/api/syncro/settings',{subdomain:card.querySelector('[name=subdomain]').value.trim(),api_key:''});status.textContent='Key removed.';}catch(e){status.textContent=e.message;}};
  card.querySelector('[data-test]').onclick=async()=>{try{await api.get('/api/syncro/customers',{page:1});status.textContent='Customer read succeeded. Each import checks the other category permissions separately.';}catch(e){status.textContent=e.message;}};
  card.querySelector('[data-import]').onclick=()=>importSyncro();
}

export async function importSyncro(){
  const modal=openModal({title:'Import clinic from Syncro',size:'modal-lg',body:'Loading…',footer:'<button class="btn" data-close>Close</button>'});
  modal.root.querySelector('[data-close]').onclick=()=>modal.close();
  try{
    const [areas,clinics]=await Promise.all([api.get('/api/admin/areas'),api.get('/api/clinics')]);
    modal.body.innerHTML=`<p>Review before importing. No writes are sent to Syncro. Existing local records are preserved; source snapshots refresh on reimport.</p><div class="actions"><input name="query" aria-label="Search Syncro customers" placeholder="Customer name"><button class="btn" data-search>Search</button><button class="btn" data-next>Next page</button></div><p data-status role="status"></p><div data-results></div><div data-preview></div>`;
    let page=1;
    const status=modal.body.querySelector('[data-status]'),results=modal.body.querySelector('[data-results]'),preview=modal.body.querySelector('[data-preview]');
    async function search(){status.textContent='Reading Syncro…';try{const data=await api.get('/api/syncro/customers',{query:modal.body.querySelector('[name=query]').value,page});results.innerHTML=data.customers.map(c=>`<p><button class="btn" data-customer="${c.id}">${esc(c.name)} · ${esc(c.city)}${c.clinic_id?' · Already linked':''}</button></p>`).join('')||'<p>No customers found.</p>';status.textContent=`Page ${page}`;results.querySelectorAll('[data-customer]').forEach(b=>b.onclick=()=>choose(Number(b.dataset.customer)));}catch(e){status.textContent=e.message;}}
    modal.body.querySelector('[data-search]').onclick=()=>{page=1;search();};modal.body.querySelector('[data-next]').onclick=()=>{page++;search();};
    function choose(id){
      preview.innerHTML=`<h3>Choose import categories</h3>${['contacts','assets','tickets','invoices'].map(k=>`<label><input type="checkbox" name="category" value="${k}" checked> ${k==='assets'?'Machines & reported interfaces':k}</label>`).join('')}<button class="btn" data-build>Build preview</button><p>Large collections may take a minute. Unsupported fields, notes, comments, attachments and custom properties are not copied. No VLAN, uplink or site relationships are inferred.</p>`;
      preview.querySelector('[data-build]').onclick=async e=>{e.target.disabled=true;status.textContent='Building reviewed import…';try{const data=await api.post('/api/syncro/preview',{customer_id:id,categories:[...preview.querySelectorAll('[name=category]:checked')].map(i=>i.value)});review(data);}catch(error){status.textContent=error.message;e.target.disabled=false;}};
    }
    function review(data){
      status.textContent='Preview ready. Nothing has been imported.';
      const list=Array.isArray(clinics)?clinics:clinics.clinics||[];
      preview.innerHTML=`<h3>Review import</h3><label>Clinic name<input name="name" value="${attr(data.clinic.name)}"></label><p>${esc([data.clinic.address,data.clinic.city,data.clinic.province,data.clinic.postal_code,data.clinic.phone,data.clinic.email].filter(Boolean).join(' · '))}</p><label>Area<select name="area">${areas.filter(a=>a.is_active).map(a=>`<option value="${a.id}">${esc(a.name)}</option>`).join('')}</select></label><label>Match existing clinic<select name="clinic" ${data.clinic_id?'disabled':''}><option value="">Create a new current-client clinic</option>${list.map(c=>`<option value="${c.id}" ${c.id===data.clinic_id?'selected':''}>${esc(c.name)}</option>`).join('')}</select></label><p>Check for an existing clinic before creating one. Machines start at the main site without uplinks; review their types and site assignments after import. Invoice history stays separate from AreaBook billing.</p>${data.warnings.map(w=>`<p class="text-danger">${esc(w)}</p>`).join('')}${Object.entries(data.records).map(([kind,rows])=>`<details><summary>${esc(kind)}: ${rows.length} records</summary>${rows.map(r=>`<pre style="white-space:pre-wrap">${esc(JSON.stringify(r,null,2))}</pre>`).join('')}</details>`).join('')}<button class="btn btn-primary" data-confirm>Confirm import</button>`;
      const chosen=list.find(c=>c.id===data.clinic_id);if(chosen)preview.querySelector('[name=area]').value=chosen.area_id;
      const fill=document.createElement('label');fill.innerHTML='<input type="checkbox" name="fill-network"> Fill missing network information: initialize empty machines, or add addresses to MAC-matched Syncro adapters with no addresses or VLAN assignments. Existing addresses and documentation are never overwritten.';preview.querySelector('[data-confirm]').before(fill);
      preview.querySelectorAll('pre').forEach(pre=>{
        const record=JSON.parse(pre.textContent),details=document.createElement('dl');
        details.innerHTML=Object.entries(record).filter(([key,value])=>key!=='id'&&key!=='url'&&value!==''&&value!==null).map(([key,value])=>{
          const label=key.replaceAll('_',' ');
          const content=key==='interfaces'?value.map(i=>`${i.name} · ${i.mac_address||'MAC not reported'} · ${i.addresses.map(a=>a.address+(a.prefix===null?'':'/'+a.prefix)).join(', ')||'IP not reported'}`).join(' | '):key==='addresses'?value.map(a=>a.address+(a.prefix===null?'':'/'+a.prefix)).join(', '):Array.isArray(value)?value.join(', '):String(value);
          return `<dt>${esc(label)}</dt><dd>${esc(content||'Not recorded')}</dd>`;
        }).join('');pre.replaceWith(details);
        if(record.interfaces){
          const button=document.createElement('button');button.className='btn btn-sm';button.textContent='Download network diagnostics';details.after(button);
          button.onclick=async()=>{
            const {confirmDialog}=await import('./ui.js');
            if(!await confirmDialog('Download filtered network field names and IP/MAC addresses for this asset? The file excludes raw text and credentials, but contains network identifiers. Review it before sharing. This does not import or change anything.',{danger:false,okLabel:'Download'}))return;
            button.disabled=true;
            try{
              const report=await api.post('/api/syncro/network-diagnostics',{token:data.token,asset_id:record.id});
              const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));
              const link=document.createElement('a');link.href=url;link.download=`syncro-network-${record.id}.json`;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
              status.textContent='Diagnostics downloaded. Review the JSON file before sharing it. No records were imported.';
            }catch(error){status.textContent=error.message;}finally{button.disabled=false;}
          };
        }
      });
      preview.querySelector('[data-confirm]').onclick=async e=>{e.target.disabled=true;try{const result=await api.post('/api/syncro/import',{token:data.token,fill_missing_network:preview.querySelector('[name=fill-network]').checked,name:preview.querySelector('[name=name]').value,area_id:Number(preview.querySelector('[name=area]').value),clinic_id:Number(preview.querySelector('[name=clinic]').value)||null});modal.close();toast(`Syncro: ${result.created} new records, ${result.preserved} local records preserved, ${result.interfaces_added||0} interfaces added or filled.`,'success');navigate('#/clinics/'+result.clinic_id);}catch(error){status.textContent=error.message;e.target.disabled=false;}};
    }
    await search();
  }catch(e){modal.body.textContent=e.message;}
}

export async function syncroClinic(container,cid){
  const data=await api.get(`/api/syncro/clinics/${cid}`);if(!data.link||!container.isConnected)return;
  const card=document.createElement('section');card.className='card mb';
  card.innerHTML=`<h2>Syncro records</h2><p>Read-only source snapshot · Last imported ${esc(data.link.updated_at)} UTC. Not live data. Local edits are preserved; ask an administrator to reimport to refresh source records.</p>${['contacts','assets','tickets','invoices'].map(k=>{const rows=data.records.filter(r=>r.kind===k);return rows.length?`<details><summary>${k} (${rows.length})</summary>${rows.map(({data:r})=>`<p>${r.url?`<a href="${attr(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.name||r.title||'Invoice '+r.number)}</a>`:esc(r.name)} ${esc(r.status||'')} ${k==='invoices'?esc(`Total ${r.total} · Balance ${r.balance_due} · ${r.paid?'Paid':'Not marked paid'}`):''}</p>`).join('')}</details>`:'';}).join('')}`;
  container.append(card);
}
