// Pure display transformations. Never mutate the API graph or write relationships.
export function displayGraph(nodes, edges, hiddenTypes = [], collapsed = []) {
  const byId = new Map(nodes.map(n => [n.id, n]));
  const hidden = new Set(hiddenTypes), folded = new Set(collapsed);
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
    if (byId.has(id) && !hidden.has(byId.get(id).device_type)) descendants(id).forEach(d => removed.add(d));
  }
  const visible = nodes.filter(n => !hidden.has(n.device_type) && !removed.has(n.id));
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
  return { nodes: visible, edges: links, counts, collapsedCount: [...removed].filter(id=>!hidden.has(byId.get(id).device_type)).length };
}

// Compact left-to-right outline: depth consumes width; sibling devices consume height.
export function layoutGraph(nodes, edges) {
  const ids = new Set(nodes.map(n => n.id)), child = new Map(nodes.map(n => [n.id, []])), parent = new Set();
  for (const e of edges) if (e.primary && !parent.has(e.to) && ids.has(e.from) && ids.has(e.to)) {
    child.get(e.from).push(e.to); parent.add(e.to);
  }
  const pos = new Map(), visited = new Set(); let row = 0;
  const walk = (id, depth) => {
    if (visited.has(id)) return;
    visited.add(id); pos.set(id, { x: 30 + depth * 270, y: 30 + row++ * 132 });
    child.get(id).forEach(c => walk(c, depth + 1));
  };
  nodes.filter(n => !parent.has(n.id)).forEach(n => walk(n.id, 0));
  nodes.forEach(n => walk(n.id, 0)); // Gracefully render cyclic or incomplete imports.
  return pos;
}
