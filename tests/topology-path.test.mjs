import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const code=await readFile(new URL('../app/static/js/topology-path.js',import.meta.url),'utf8');
const {documentedPath,edgeOnPath,traceDestination,traceVpn}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('documented paths traverse both directions and terminate cycles',()=>{
  const nodes=[1,2,3,4].map(id=>({id})),edges=[{from:1,to:2},{from:2,to:3},{from:3,to:1}];
  assert.deepEqual(documentedPath(nodes,edges,2,1),[2,1]);
  assert.deepEqual(documentedPath(nodes,edges,2,2),[2]);
  assert.equal(documentedPath(nodes,edges,1,4),null);
  assert.equal(documentedPath(nodes,edges,1,999),null);
});
test('compressed path highlights require the entire chain in order',()=>{
  const edge={from:1,to:3,hidden:[2]};
  assert.ok(edgeOnPath(edge,[1,2,3]));assert.ok(edgeOnPath(edge,[3,2,1]));
  assert.equal(edgeOnPath(edge,[1,4,3]),false);
  assert.equal(edgeOnPath(edge,null),false);
});
test('service traces end at the host; subnet traces select nearest documented member',()=>{
  const nodes=[{id:1},{id:2,subnets:['10.0.0.0/24']},{id:3,subnets:['10.0.0.0/24'],services:[{id:9}]},{id:4,subnets:['10.0.0.0/24']}];
  const edges=[{from:1,to:2},{from:2,to:3}];
  assert.deepEqual(traceDestination(nodes,edges,1,'service:9').path,[1,2,3]);
  assert.deepEqual(traceDestination(nodes,edges,1,'subnet:10.0.0.0/24'),{path:[1,2],candidateCount:3,connectedCount:2});
  assert.equal(traceDestination(nodes,edges,1,'service:999').path,null);
});
test('VPN tracing never invents local termination or remote reachability',()=>{
  const nodes=[{id:1},{id:2}],edges=[{from:1,to:2}];
  assert.equal(traceVpn(nodes,edges,1,{}).path,null);
  const result=traceVpn(nodes,edges,1,{device_id:2,status:'disabled'});
  assert.deepEqual(result.path,[1,2]);assert.match(result.warning,/disabled/);assert.match(result.warning,/unverified/);
  assert.equal(traceVpn(nodes,edges,1,{device_id:99}).path,null);
});
