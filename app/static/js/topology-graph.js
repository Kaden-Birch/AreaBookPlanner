// Pure display transformations. Never mutate the API graph or write relationships.
export function displayGraph(nodes, edges, hiddenTypes = [], collapsed = [], hiddenDevices = []) {
  const byId = new Map(nodes.map(n => [n.id, n]));
  const hidden = new Set(hiddenTypes), folded = new Set(collapsed);
  const hiddenIds = new Set(hiddenDevices), isHidden=n=>hidden.has(n.device_type)||hiddenIds.has(n.id);
  const children = new Map(nodes.map(n => [n.id, []]));
  const outgoing = new Map(nodes.map(n => [n.id, []]));
  for (const e of edges) {
    if (!byId.has(e.from) || !byId.has(e.to)) continue;
    outgoing.get(e.from).push(e);
    if (e.primary) children.get(e.from).push(e.to);
  }
  const descendants = id => {
    const seen = new Set([id]), result = [], stack = [...children.get(id)];
    while (stack.length) {
      const next = stack.pop();
      if (seen.has(next)) continue;
      seen.add(next); result.push(next); stack.push(...children.get(next));
    }
    return result;
  };
  const counts = new Map(nodes.map(n => [n.id, descendants(n.id).length]));
  const removed = new Set();
  for (const id of folded) {
    // A hidden group header must not invisibly swallow its visible children.
    if (byId.has(id) && !isHidden(byId.get(id))) descendants(id).forEach(d => removed.add(d));
  }
  const visible = nodes.filter(n => !isHidden(n) && !removed.has(n.id));
  const ids = new Set(visible.map(n => n.id)), links = [], keys = new Set();
  for (const n of visible) {
    const queue = outgoing.get(n.id).map(e => ({ e, path: [], primary: !!e.primary }));
    const visited = new Set();
    for (let i = 0; i < queue.length; i++) {
      const { e, path, primary } = queue[i], id = e.to;
      if (id === n.id || removed.has(id)) continue;
      if (ids.has(id)) {
        const key = `${n.id}:${id}:${primary}:${path.length ? 'compressed' : 'direct'}`;
        if (!keys.has(key)) { keys.add(key); links.push({ ...e, from: n.id, primary, hidden: path }); }
        continue;
      }
      const key = `${id}:${primary}`;
      if (visited.has(key)) continue;
      visited.add(key);
      for (const next of outgoing.get(id) || []) queue.push({ e: next, path: [...path, id], primary: primary && !!next.primary });
    }
  }
  return { nodes: visible, edges: links, counts, collapsedCount: [...removed].filter(id=>!isHidden(byId.get(id))).length };
}

export const nodeHeight = n => n.services?.length ? (n.services.length > 1 ? 112 : 98) : 80;

// Pack each tier independently; descendants never reserve blank space in higher tiers.
export function layoutGraph(nodes, edges, orientation = 'horizontal') {
  const ids = new Set(nodes.map(n => n.id)), child = new Map(nodes.map(n => [n.id, []])), parent = new Set();
  for (const e of edges) if (e.primary && !parent.has(e.to) && ids.has(e.from) && ids.has(e.to)) {
    child.get(e.from).push(e.to); parent.add(e.to);
  }
  const pos = new Map(), visited = new Set(), tiers=[];
  const walk=(root)=>{
    const queue=[{id:root,depth:0}];
    for(let j=0;j<queue.length;j++){
      const {id,depth}=queue[j];if(visited.has(id))continue;
      visited.add(id);(tiers[depth] ||= []).push(id);
      child.get(id).forEach(c=>queue.push({id:c,depth:depth+1}));
    }
  };
  nodes.filter(n=>!parent.has(n.id)).forEach(n=>walk(n.id));
  nodes.forEach(n=>walk(n.id));
  const widest=Math.max(1,...tiers.map(t=>t.length));
  const byId=new Map(nodes.map(n=>[n.id,n]));
  const tierHeights=tiers.map(t=>t.reduce((sum,id)=>sum+nodeHeight(byId.get(id))+16,0));
  const tallest=Math.max(0,...tierHeights);let tierY=30;
  tiers.forEach((tier,depth)=>{
    let rowY=30+(tallest-tierHeights[depth])/2;
    tier.forEach((id,index)=>{
      const slot=index+(widest-tier.length)/2;
      pos.set(id,orientation==='vertical'?{x:30+slot*240,y:tierY}:{x:30+depth*270,y:rowY});
      rowY+=nodeHeight(byId.get(id))+16;
    });
    tierY+=Math.max(...tier.map(id=>nodeHeight(byId.get(id))))+32;
  });
  return pos;
}
