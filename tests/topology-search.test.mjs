import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source=await readFile(new URL('../app/static/js/topology-search.js',import.meta.url),'utf8');
const {matchesTopologySearch:search,matchesTopologyFilter:filter}=await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const node={id:1,name:'Host',device_type:'server',status:'active',rack_room:'Basement',rack:'Rack A',rack_position:0,
  interface_macs:['aa:bb:cc:dd:ee:ff'],addresses:[{address:'2001:db8::1',prefix_length:64},{address:'10.2.0.1'}],
  vlan_memberships:[{vlan_id:2}],services:[{name:'Records'}]};
const vlans=[{id:2,tag:42,name:'Clinical',subnets:['10.2.0.0/24']},{id:3,name:'Unrelated',subnets:[]}];
test('search covers interface MAC, IPv6, VLAN, subnet, service and placement',()=>{
  for(const q of ['AA:BB','2001:db8::1/64','clinical','42','10.2.0.0/24','Records','basement','rack a','0'])assert.ok(search(node,q,vlans),q);
  assert.equal(search(node,'Unrelated',vlans),false);
  assert.ok(search({},'',[]));
});
test('quick filters select only matching documented devices without mutation',()=>{
  const before=JSON.stringify(node);
  for(const q of ['servers','multiple','status:active'])assert.ok(filter(node,q));
  assert.equal(filter(node,'status:retired'),false);
  assert.equal(filter(node,'documentation',[]),false);
  assert.ok(filter(node,'documentation',[{kind:'device',id:1}]));
  assert.equal(filter(node,'documentation',[{kind:'vlan',id:1}]),false);
  assert.equal(JSON.stringify(node),before);
});
test('open-work filters do not mistake ticket existence for open status',()=>{
  assert.equal(filter({ticket_count:8},'open-work'),false);
  assert.ok(filter({open_ticket_count:1},'open-work'));
  assert.ok(filter({open_task_count:2},'open-tasks'));
  assert.equal(filter({open_task_count:2},'open-tickets'),false);
});
