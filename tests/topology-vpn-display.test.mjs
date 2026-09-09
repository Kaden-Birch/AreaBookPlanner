import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const code=await readFile(new URL('../app/static/js/topology-vpn-display.js',import.meta.url),'utf8');
const {displayedVpns,vpnDisplayClass}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('overlay status filtering is conservative and non-mutating',()=>{
  const links=['up','down','disabled','unknown','unexpected'].map(status=>({status}));
  assert.equal(displayedVpns(links,false,false).length,0);
  assert.equal(displayedVpns(links,true,false).length,5);
  assert.deepEqual(displayedVpns(links,true,true),[{status:'up'}]);
  assert.equal(links.length,5);
  assert.equal(vpnDisplayClass('unexpected'),'vpn-recorded-unknown');
});
