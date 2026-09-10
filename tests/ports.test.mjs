import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const code=(await readFile(new URL('../app/static/js/ports.js',import.meta.url),'utf8')).replace(/^import .*;\n/gm,'');
const {speedColour,speedLabel}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('port colours and labels distinguish unknown and speed bands',()=>{
  assert.equal(speedColour(null),'#8a8f98');assert.equal(speedColour(100),'#d9342b');
  assert.equal(speedColour(1000),'#547ee8');assert.equal(speedColour(2500),'#22a06b');assert.equal(speedColour(10000),'#ed8b23');
  assert.equal(speedLabel(null),'Unknown speed');assert.equal(speedLabel(2500),'2.5 Gb');assert.equal(speedLabel(100),'100 Mb');
});
