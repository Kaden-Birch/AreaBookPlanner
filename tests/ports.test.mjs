import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const code=(await readFile(new URL('../app/static/js/ports.js',import.meta.url),'utf8')).replace(/^import .*;\n/gm,'');
const {speedColour,speedLabel,parseSpeeds,portGroupNames}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('port groups retain creation order, not alphabetical order',()=>{
  const interfaces=[{id:20,port_group:'SFP'},{id:1,port_group:'GbE'},{id:17,port_group:'WAN'},{id:2,port_group:'GbE'}];
  assert.deepEqual(portGroupNames(interfaces),['GbE','WAN','SFP']);
  assert.equal(interfaces[0].id,20);
});
test('speed input accepts single values, lists, units and pasted separators',()=>{
  assert.deepEqual(parseSpeeds('1000'),[1000]);
  assert.deepEqual(parseSpeeds('10,100,1000'),[10,100,1000]);
  assert.deepEqual(parseSpeeds('1 Gbps, 2.5 Gbps, 10 Gb/s'),[1000,2500,10000]);
  assert.deepEqual(parseSpeeds('1000 Mbps; 2500\n10000,'),[1000,2500,10000]);
  assert.deepEqual(parseSpeeds('１０００，２５００'),[1000,2500]);
  assert.deepEqual(parseSpeeds('10GbE, 1G, 1000'),[1000,10000]);
  assert.deepEqual(parseSpeeds(''),[]);
  assert.throws(()=>parseSpeeds('unknown','Installed module speeds'),/Installed module speeds/);
  for(const value of ['0','-1','0.5 Mbps','1e3','10000001','1 GBps nonsense',','])assert.throws(()=>parseSpeeds(value));
});
test('port colours and labels distinguish unknown and speed bands',()=>{
  assert.equal(speedColour(null),'#8a8f98');assert.equal(speedColour(100),'#d9342b');
  assert.equal(speedColour(1000),'#547ee8');assert.equal(speedColour(2500),'#22a06b');assert.equal(speedColour(10000),'#ed8b23');
  assert.equal(speedLabel(null),'Unknown speed');assert.equal(speedLabel(2500),'2.5 Gb');assert.equal(speedLabel(100),'100 Mb');
});
