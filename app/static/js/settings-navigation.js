import {api} from './api.js';
import {esc,confirmDialog} from './ui.js';

let selectedSection='AI & integrations';

export function organizeGlobalSettings(container) {
  const cards=[...container.querySelectorAll('.card')].filter(c=>!c.parentElement.closest('.card'));
  const nav=document.createElement('nav');nav.className='actions settings-sections';nav.setAttribute('aria-label','Global settings sections');
  const content=document.createElement('div');content.id='global-settings-content';
  container.querySelector('.page-header').after(nav,content);
  const sections={};
  for(const name of ['AI & integrations','Quote pricing','Templates','Application defaults','Change history']) {
    const section=document.createElement('section');section.hidden=true;section.setAttribute('aria-label',name);content.append(section);sections[name]=section;
    const b=document.createElement('button');b.className='btn';b.textContent=name;b.setAttribute('aria-pressed','false');nav.append(b);
    b.onclick=()=>{selectedSection=name;for(const s of Object.values(sections))s.hidden=true;section.hidden=false;nav.querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));if(name==='Change history')history();};
  }
  for(const card of cards) {
    const title=card.querySelector('h3')?.textContent||'';
    const name=title.startsWith('AI')?'AI & integrations':title==='Quote price book'?'Quote pricing':/templates|Onboarding/.test(title)?'Templates':'Application defaults';
    sections[name].append(card);
  }
  container.querySelectorAll('.grid-2').forEach(g=>{if(!g.querySelector('.card'))g.remove();});
  const test=document.createElement('button');test.className='btn';test.textContent='Test saved AI connection';sections['AI & integrations'].prepend(test);
  const status=document.createElement('p');status.setAttribute('role','status');test.after(status);
  test.onclick=async()=>{if(!await confirmDialog('Test the saved shared key with OpenAI? This sends an authenticated connection check, not clinic data, and does not generate AI content.'))return;test.disabled=true;status.textContent='Testing saved connection…';try{const result=await api.post('/api/settings/test-ai',{});status.textContent=result.message;}catch(e){status.textContent=e.message;}finally{test.disabled=false;}};
  const history=async()=>{const section=sections['Change history'];section.innerHTML='<p>Loading shared-settings history…</p>';try{const rows=await api.get('/api/settings/history');section.innerHTML='<h2>Recent changes</h2><p>Who changed shared settings and when. Secret values are never included.</p>'+ (rows.length?rows.map(r=>`<p><strong>${esc(r.actor||'Former user')}</strong> · ${esc(r.created_at)} UTC · ${esc(r.method)} ${esc(r.path)}</p>`).join(''):'<p>No changes recorded since this feature was enabled.</p>');}catch(e){section.textContent=e.message;}};
  [...nav.querySelectorAll('button')].find(b=>b.textContent===selectedSection).click();
}
