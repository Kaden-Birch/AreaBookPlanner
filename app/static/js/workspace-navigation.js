// Pure route policy: server authorization remains authoritative.
export function workspaceDestination(hash, role, isAdmin=false) {
  const path=(hash||'#/').split('?')[0];
  if(role==='admin') return ['#/settings','#/application-settings'].includes(path)?hash:'#/';
  const clinic=path.match(/^#\/clinics\/(\d+)(.*)$/);
  if(clinic && ((clinic[2].startsWith('/equipment') && role!=='it') ||
    (clinic[2]==='/quote' && !['sales','manager'].includes(role)))) return `#/clinics/${clinic[1]}`;
  if(path==='#/application-settings'&&!isAdmin)return '#/settings';
  if(/^#\/(pipeline|analytics)/.test(path)&&!['sales','manager'].includes(role))return '#/';
  if(/^#\/(billing|clients|invoices|call-sheet)/.test(path)&&role==='it')return '#/';
  if(/^#\/quotes\/\d+\/edit$/.test(path)&&!['sales','manager'].includes(role))return path.replace(/\/edit$/,'');
  return hash||'#/';
}

export function hasUnsavedInputs(root=document) {
  return [...root.querySelectorAll('form input,form textarea,form select,.modal input,.modal textarea,.modal select,#global-settings-content input,#global-settings-content textarea,#global-settings-content select')].some(el=>{
    if(el.disabled||['search','hidden','submit','button'].includes(el.type))return false;
    if(el.type==='file')return !!el.files?.length;
    if(['checkbox','radio'].includes(el.type))return el.checked!==el.defaultChecked;
    if(el.tagName==='SELECT')return [...el.options].some(o=>o.selected!==o.defaultSelected) && el.value!==(el.querySelector('option[selected]')?.value||el.options[0]?.value);
    return el.value!==el.defaultValue;
  });
}
