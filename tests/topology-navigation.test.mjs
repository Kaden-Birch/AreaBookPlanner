import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const code=await readFile(new URL('../app/static/js/topology-navigation.js',import.meta.url),'utf8');
const {validPositions,sceneBounds,viewportRect}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('saved coordinates reject corrupt and unbounded browser data',()=>{
  assert.deepEqual(validPositions(null),{});
  assert.deepEqual(validPositions([]),{});
  assert.deepEqual(validPositions({1:{x:25,y:-20},2:{x:'5',y:6},3:{x:Infinity,y:0},4:{x:1e6,y:0},oops:{x:0,y:0}}),{1:{x:25,y:-20}});
});
test('minimap bounds contain negative positions and large devices',()=>{
  const b=sceneBounds([{x:-200,y:-50,width:220,height:100},{x:900,y:700,width:220,height:150}]);
  assert.deepEqual(b,{x:-220,y:-70,width:1360,height:940});
  assert.deepEqual(sceneBounds([]),{x:0,y:0,width:240,height:160});
});
test('viewport rectangle reverses zoom and pan',()=>{
  assert.deepEqual(viewportRect({x:100,y:-50,z:.5},800,400),{x:-200,y:100,width:1600,height:800});
});
