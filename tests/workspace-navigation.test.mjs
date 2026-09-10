import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const {workspaceDestination,hasUnsavedInputs}=await import('data:text/javascript;base64,'+Buffer.from(fs.readFileSync(new URL('../app/static/js/workspace-navigation.js',import.meta.url),'utf8')).toString('base64'));
test('workspace switch preserves supported pages and queries',()=>{
  assert.equal(workspaceDestination('#/clinics/7?tab=notes','manager'),'#/clinics/7?tab=notes');
  assert.equal(workspaceDestination('#/map?q=test','sales'),'#/map?q=test');
  assert.equal(workspaceDestination('#/clinics/7/equipment?view=topology','sales'),'#/clinics/7');
  assert.equal(workspaceDestination('#/quotes/9/edit','it'),'#/quotes/9');
  assert.equal(workspaceDestination('#/application-settings','sales'),'#/settings');
  assert.equal(workspaceDestination('#/application-settings','sales',true),'#/application-settings');
});
test('unsaved detector ignores search and detects editable values',()=>{
  const input={type:'text',value:'new',defaultValue:'old'};
  const root={querySelectorAll:()=>[input]};
  assert.equal(hasUnsavedInputs(root),true);
  input.value='old';assert.equal(hasUnsavedInputs(root),false);
  input.type='search';input.value='new';assert.equal(hasUnsavedInputs(root),false);
  input.type='checkbox';input.checked=true;input.defaultChecked=false;assert.equal(hasUnsavedInputs(root),true);
});
