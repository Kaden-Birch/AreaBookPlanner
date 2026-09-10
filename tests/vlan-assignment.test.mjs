import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const code=(await readFile(new URL('../app/static/js/vlan-assignment.js',import.meta.url),'utf8')).replace(/^import .*;\n/gm,'');
const {assignMembership}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('assignment preserves trunks, addresses, unselected interfaces and input',()=>{
  const rows=[{memberships:[{vlan_id:1,mode:'native'},{vlan_id:2,mode:'tagged'}],addresses:[{address:'10.0.0.1',vlan_id:1}]},{memberships:[],addresses:[]}];
  const added=assignMembership(rows,[0],3,'tagged');
  assert.equal(added[0].memberships.length,3);assert.equal(rows[0].memberships.length,2);
  const replaced=assignMembership(rows,[0],3,'access');
  assert.deepEqual(replaced[0].memberships,[{vlan_id:2,mode:'tagged'},{vlan_id:3,mode:'access'}]);
  assert.equal(replaced[0].addresses[0].vlan_id,3);assert.deepEqual(replaced[1],rows[1]);
  assert.deepEqual(assignMembership(added,[0],3,'tagged'),added);
});
