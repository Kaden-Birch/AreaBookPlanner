// Reuse existing controls and handlers, but separate tools from the diagram.
export function organizeTopology(body) {
  const controls=body.querySelector('.topology-controls');
  const toolbar=controls.querySelector('.topology-toolbar');
  const canvas=body.querySelector('.topology-canvas');
  const header=document.createElement('div');header.className='topology-commandbar';
  const workspace=document.createElement('div');workspace.className='topology-workspace';
  const panel=document.createElement('aside');panel.className='topology-toolpanel';panel.hidden=true;
  panel.id='topology-tools';panel.setAttribute('aria-label','Topology tools');
  const main=document.createElement('div');main.className='topology-diagram';
  controls.before(header,workspace);workspace.append(main,panel);main.append(canvas);
  header.append(body.querySelector('.topology-search'));
  const sections={};
  for(const [name,help] of Object.entries({
    Filters:'Choose which devices appear. Hidden devices stay in the documented connection path.',
    Layout:'Change the direction or grouping of the diagram. Moving cards changes presentation only.',
    Networks:'Highlight VLAN membership or display documented VPN links.',
    Trace:'Follow documented connections. A path is not proof of live reachability.',
    Reports:'Import equipment, review history or export the visible diagram.'
  })) {
    const button=document.createElement('button');button.className='btn btn-sm';button.textContent=name;
    button.setAttribute('aria-controls',panel.id);button.setAttribute('aria-expanded','false');header.append(button);
    const section=document.createElement('section');section.hidden=true;
    const title=document.createElement('h3');title.textContent=name;
    const hint=document.createElement('p');hint.className='help';hint.textContent=help;section.append(title,hint);panel.append(section);sections[name]=section;
    button.onclick=()=>{
      const close=!panel.hidden&&!section.hidden;
      panel.hidden=close;workspace.classList.toggle('tools-open',!close);
      for(const s of Object.values(sections))s.hidden=true;
      for(const b of header.querySelectorAll('[aria-controls]'))b.setAttribute('aria-expanded','false');
      if(!close){section.hidden=false;button.setAttribute('aria-expanded','true');}
    };
  }
  const move=(section,selectors)=>selectors.forEach(selector=>{const el=body.querySelector(selector);if(el)sections[section].append(el.matches('input,select')?el.closest('label'):el);});
  move('Filters',['#topology-search-only','#topology-quick-filter','#topology-subnet','.topology-types','#topology-reset']);
  move('Layout',['#topology-perspective','#topology-orientation','#topology-manual','#topology-auto-layout','#topology-collapse','#topology-expand','#topology-edit']);
  move('Networks',['#topology-show-vpn','#topology-vpn-up','#topology-manage-vlans','.topology-vlan-bar','#topology-vlan-details']);
  move('Trace',['#topology-routing','#topology-remote-trace']);
  move('Reports',['.topology-report-menu']);
  for(const detail of [...controls.querySelectorAll(':scope > details')]) {
    if(detail.querySelector('#topology-path-source')) {
      detail.open=true;
      detail.querySelector('summary').textContent='Within this site';
      detail.querySelector('.help').textContent='Choose a start and destination. Hidden intermediate devices remain in the trace.';
    }
    sections[detail.querySelector('#topology-groups')?'Layout':'Trace'].append(detail);
  }
  const results=body.querySelector('#topology-results');main.prepend(results);
  main.prepend(body.querySelector('#topology-summary'),body.querySelector('#topology-breadcrumb'));
  // Preserve any explanatory content not explicitly categorized above.
  toolbar.remove();sections.Layout.append(...controls.childNodes);controls.remove();
  const close=document.createElement('button');close.className='btn btn-sm';close.textContent='Close tools';panel.prepend(close);
  const dismiss=()=>{const active=header.querySelector('[aria-expanded="true"]');active?.click();active?.focus();};
  close.onclick=dismiss;panel.onkeydown=e=>{if(e.key==='Escape'){e.stopPropagation();dismiss();}};
  const fullscreen=document.createElement('button');fullscreen.className='btn btn-sm';fullscreen.textContent='Expand diagram';
  fullscreen.setAttribute('aria-pressed','false');header.append(fullscreen);
  fullscreen.onclick=()=>{const expanded=workspace.classList.toggle('expanded');fullscreen.textContent=expanded?'Exit expanded view':'Expand diagram';fullscreen.setAttribute('aria-pressed',String(expanded));if(expanded)workspace.prepend(header);else workspace.before(header);fullscreen.focus();};
  workspace.addEventListener('keydown',e=>{if(e.key==='Escape'&&workspace.classList.contains('expanded'))fullscreen.click();});
}
