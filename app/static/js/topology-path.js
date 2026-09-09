// Undirected documented adjacency, not packet routing or reachability.
export function documentedPath(nodes,edges,source,target) {
  const ids=new Set(nodes.map(n=>n.id));
  if(!ids.has(source)||!ids.has(target))return null;
  const adjacency=new Map(nodes.map(n=>[n.id,[]]));
  for(const e of edges)if(ids.has(e.from)&&ids.has(e.to)){
    adjacency.get(e.from).push(e.to);adjacency.get(e.to).push(e.from);
  }
  const previous=new Map([[source,null]]),queue=[source];
  for(let i=0;i<queue.length;i++){
    const id=queue[i];if(id===target)break;
    for(const next of adjacency.get(id))if(!previous.has(next)){previous.set(next,id);queue.push(next);}
  }
  if(!previous.has(target))return null;
  const path=[];for(let id=target;id!==null;id=previous.get(id))path.push(id);
  return path.reverse();
}

export function edgeOnPath(edge,path) {
  if(!path)return false;
  const chain=[edge.from,...(edge.hidden||[]),edge.to];
  const forward=chain.every((id,i)=>path[path.indexOf(chain[0])+i]===id);
  const reverse=chain.every((id,i)=>path[path.indexOf(chain[0])-i]===id);
  return forward||reverse;
}

export function destinationDevices(nodes,destination) {
  if(destination.startsWith('service:'))return nodes.filter(n=>(n.services||[]).some(s=>String(s.id)===destination.slice(8)));
  if(destination.startsWith('subnet:'))return nodes.filter(n=>(n.subnets||[]).includes(destination.slice(7)));
  return nodes.filter(n=>String(n.id)===destination);
}

export function traceDestination(nodes,edges,source,destination) {
  const candidates=destinationDevices(nodes,destination);
  const paths=candidates.map(n=>documentedPath(nodes,edges,source,n.id)).filter(Boolean);
  paths.sort((a,b)=>a.length-b.length||a[a.length-1]-b[b.length-1]);
  return {path:paths[0]||null,candidateCount:candidates.length,connectedCount:paths.length};
}

export function traceVpn(nodes,edges,source,vpn) {
  if(!vpn)return {path:null,warning:'VPN record unavailable in this scope.'};
  if(!vpn.device_id)return {path:null,warning:'The local VPN termination device is not documented.'};
  const path=documentedPath(nodes,edges,source,vpn.device_id);
  return {path,warning:`Tunnel status is recorded as ${vpn.status||'unknown'}. Remote routing and reachability are unverified.${path?'':' No local connection chain to the VPN device is documented in this view.'}`};
}
