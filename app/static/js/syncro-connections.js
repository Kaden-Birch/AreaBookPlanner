import {api} from './api.js';
import {esc,attr,openModal,confirmDialog} from './ui.js';

export async function connectionSettings(container){
  const card=document.createElement('section');card.className='card mb';container.append(card);
  async function load(){
    const rows=await api.get('/api/syncro/connections');
    card.innerHTML=`<h2>Additional Syncro connections</h2><p>Use the default connection for customers in the same account. Add a named connection when another API key or subdomain is needed. Multiple customers from any connection can map to one clinic/site.</p><button class="btn" data-add>Add Syncro connection</button>${rows.filter(r=>r.id).map(r=>`<p>${esc(r.name)} · ${esc(r.subdomain)} · ${r.configured?'Key saved':'Key missing'} <button class="btn btn-sm" data-edit="${r.id}">Manage</button></p>`).join('')}<p role="status"></p>`;
    card.querySelector('[data-add]').onclick=()=>edit();
    card.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>edit(rows.find(r=>r.id===Number(b.dataset.edit))));
  }
  function edit(row){
    const modal=openModal({title:row?'Manage Syncro connection':'Add Syncro connection',body:`<label>Name<input name="name" value="${attr(row?.name||'')}" placeholder="Pharmacy Syncro"></label><label>Syncro subdomain<input name="tenant" value="${attr(row?.subdomain||'')}" ${row?'disabled':''}></label><label>API key<input name="key" type="password" autocomplete="off" placeholder="${row?'Leave blank to keep saved key':'Read-only API key'}"></label><p>Only GET requests are sent to Syncro. Removing a key preserves imported records but stops successful refreshes for customers using it.</p><p role="status"></p>`,footer:`<button class="btn" data-close>Close</button>${row?'<button class="btn" data-test>Test saved key</button><button class="btn" data-remove>Remove key</button>':''}<button class="btn btn-primary" data-save>Save</button>`});
    const q=s=>modal.root.querySelector(s);
    q('[data-close]').onclick=()=>modal.close();
    async function save(remove=false){
      const payload={name:q('[name=name]').value.trim(),subdomain:q('[name=tenant]').value.trim(),...(remove?{api_key:''}:q('[name=key]').value?{api_key:q('[name=key]').value}:{})};
      try{if(row)await api.put('/api/syncro/connections/'+row.id,payload);else await api.post('/api/syncro/connections',payload);modal.close();await load();}catch(e){q('[role=status]').textContent=e.message;}
    }
    q('[data-save]').onclick=()=>save();
    if(row){q('[data-remove]').onclick=async()=>{if(await confirmDialog('Remove this connection’s API key? Its customer records remain in AreaBook.'))save(true);};q('[data-test]').onclick=async()=>{try{await api.get('/api/syncro/customers',{connection_id:row.id});q('[role=status]').textContent='Customer read succeeded.';}catch(e){q('[role=status]').textContent=e.message;}};}
  }
  try{await load();}catch(e){card.textContent=e.message;}
}
