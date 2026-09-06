import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../app/static/js/topology-graph.js', import.meta.url), 'utf8');
const { displayGraph, layoutGraph } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

const nodes = [
  {id:1,device_type:'switch'}, {id:2,device_type:'voip'},
  {id:3,device_type:'workstation'}, {id:4,device_type:'vm'},
];
const edge = (from,to,primary=true) => ({from,to,primary,link_type:'ethernet'});

test('hidden phones retain the nearest visible relationship without changing stored input',()=>{
  const edges=[edge(1,2),edge(2,3),edge(3,4)], original=JSON.stringify({nodes,edges});
  const g=displayGraph(nodes,edges,['voip']);
  assert.deepEqual(g.nodes.map(n=>n.id),[1,3,4]);
  assert.deepEqual(g.edges.find(e=>e.from===1&&e.to===3).hidden,[2]);
  assert.deepEqual(g.edges.find(e=>e.from===3&&e.to===4).hidden,[]);
  assert.equal(JSON.stringify({nodes,edges}),original);
});

test('multiple hidden hops, extra links and cycles terminate and preserve visible endpoints',()=>{
  const edges=[edge(1,2),edge(2,3),edge(3,2,false),edge(3,4,false)];
  const g=displayGraph(nodes,edges,['voip','workstation']);
  assert.equal(g.edges.length,1);
  assert.deepEqual(g.edges[0].hidden,[2,3]);
  assert.equal(g.edges[0].primary,false);
  assert.equal(g.edges[0].to,4);
});

test('collapse removes descendants without inventing a link through a collapsed group',()=>{
  const g=displayGraph(nodes,[edge(1,2),edge(2,3),edge(3,4)],[],[2]);
  assert.deepEqual(g.nodes.map(n=>n.id),[1,2]);
  assert.equal(g.counts.get(2),2);
  assert.equal(g.collapsedCount,2);
  const hiddenHeader=displayGraph(nodes,[edge(1,2),edge(2,3)],['voip'],[2]);
  assert.ok(hiddenHeader.nodes.some(n=>n.id===3));
});

test('hide all, unknown endpoints and disconnected devices produce valid graphs',()=>{
  const g=displayGraph(nodes,[edge(999,1)],['switch','voip','workstation','vm']);
  assert.deepEqual(g.nodes,[]);assert.deepEqual(g.edges,[]);
  assert.equal(layoutGraph([],[]).size,0);
  assert.equal(layoutGraph(nodes,[edge(1,2),edge(2,1)]).size,4);
});

test('wide branches use bounded width and separate rows',()=>{
  const many=Array.from({length:500},(_,id)=>({id,device_type:'workstation'}));
  const pos=layoutGraph(many,many.slice(1).map(n=>edge(0,n.id)));
  assert.equal(pos.size,500);
  assert.equal(new Set([...pos.values()].map(p=>p.y)).size,500);
  assert.ok(Math.max(...[...pos.values()].map(p=>p.x))<=300);
});
