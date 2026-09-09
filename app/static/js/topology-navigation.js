// Presentation-only coordinates. Never change network relationships.
export function validPositions(value) {
  if(!value||typeof value!=='object'||Array.isArray(value))return {};
  return Object.fromEntries(Object.entries(value).filter(([id,p])=>/^\d+$/.test(id)&&p&&
    Number.isFinite(p.x)&&Number.isFinite(p.y)&&Math.abs(p.x)<=100000&&Math.abs(p.y)<=100000)
    .map(([id,p])=>[id,{x:p.x,y:p.y}]));
}

export function sceneBounds(rectangles) {
  if(!rectangles.length)return {x:0,y:0,width:240,height:160};
  const x=Math.min(...rectangles.map(p=>p.x))-20,y=Math.min(...rectangles.map(p=>p.y))-20;
  return {x,y,width:Math.max(240,Math.max(...rectangles.map(p=>p.x+p.width))-x+20),
    height:Math.max(160,Math.max(...rectangles.map(p=>p.y+p.height))-y+20)};
}

export function viewportRect(view,width,height) {
  return {x:-view.x/view.z,y:-view.y/view.z,width:width/view.z,height:height/view.z};
}
