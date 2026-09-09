import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const code=await readFile(new URL('../app/static/js/topology-export-data.js',import.meta.url),'utf8');
const {csvCell,viewData}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('CSV quotes text, embedded quotes and newlines, and neutralizes formulas',()=>{
  assert.equal(csvCell('a,"b"'),'"a,""b"""');
  for(const value of ['=1+1','+cmd','-1','@SUM(A1)','  =1','\tname','\nname'])
    assert.equal(csvCell(value)[1],"'");
  assert.equal(csvCell(null),'""');
  assert.equal(csvCell('2001:db8::1'),'"2001:db8::1"');
});
test('filtered export excludes hidden children and never modifies the display graph',()=>{
  const graph={nodes:[{id:1,children:[2,3]},{id:3}],edges:[{from:1,to:3,hidden:[2],details:null}]};
  const before=JSON.stringify(graph),result=viewData(graph,{site:'main'});
  assert.deepEqual(result.nodes[0].children,[3]);assert.equal(result.edges[0].hidden_count,1);
  assert.ok(!('hidden' in result.edges[0]));assert.equal(result.nodes.length,2);
  assert.equal(JSON.stringify(graph),before);
});
test('view exports carry displayed VPN context and presentation coordinates',()=>{
  const graph={nodes:[{id:1}],edges:[]};
  const context={show_vpn:true,vpn:[{vpn_id:2,device_id:1}],positions:{1:{x:50,y:60}}};
  assert.deepEqual(viewData(graph,context).vpn,context.vpn);
  assert.deepEqual(viewData(graph,context).positions,context.positions);
  assert.deepEqual(viewData(graph,{show_vpn:false,vpn:[]}).vpn,[]);
});
