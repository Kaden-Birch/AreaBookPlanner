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
  const forward=path.some((start,index)=>start===chain[0]&&chain.every((id,i)=>path[index+i]===id));
  const reverse=path.some((start,index)=>start===chain[0]&&chain.every((id,i)=>path[index-i]===id));
  return forward||reverse;
}

export function destinationDevices(nodes,destination) {
  if(destination.startsWith('service:'))return nodes.filter(n=>(n.services||[]).some(s=>String(s.id)===destination.slice(8)));
  if(destination.startsWith('subnet:'))return nodes.filter(n=>(n.subnets||[]).includes(destination.slice(7)));
  return nodes.filter(n=>String(n.id)===destination);
}

export function vlanPath(nodes,edges,source,target,catalog=[],selection={}) {
  const deviceVlans=id=>[...new Set((nodes.find(n=>n.id===id)?.vlan_memberships||[]).map(m=>m.vlan_id))];
  const from=deviceVlans(source),to=deviceVlans(target);
  const resolve=(ids,chosen)=>chosen?ids.includes(Number(chosen))?Number(chosen):null:ids.length===1?ids[0]:null;
  const a=resolve(from,selection.sourceVlan),b=resolve(to,selection.targetVlan);
  if((from.length>1&&!a)||(to.length>1&&!b)||selection.sourceVlan&&!a||selection.targetVlan&&!b)return {path:null,warning:'Select the source and destination VLANs for multi-VLAN devices; no routing path is assumed.'};
  if(a&&b&&a!==b) {
    const av=catalog.find(v=>v.id===a),bv=catalog.find(v=>v.id===b);
    if(!av?.gateway_device_id||!bv?.gateway_device_id)return {path:null,warning:'Inter-VLAN routing is undocumented. Configure a gateway interface for both VLANs in Manage VLANs.'};
    const waypoints=[source,av.gateway_device_id,bv.gateway_device_id,target],path=[source];
    for(let i=1;i<waypoints.length;i++){
      const segment=documentedPath(nodes,edges,waypoints[i-1],waypoints[i]);
      if(!segment)return {path:null,warning:'No documented connection chain through the configured VLAN gateways is available.'};
      path.push(...segment.slice(1));
    }
    return {path,warning:'Inter-VLAN path passes through the configured gateways. Routing tables, ACLs and live reachability are not verified.'};
  }
  return {path:documentedPath(nodes,edges,source,target)};
}

export function traceDestination(nodes,edges,source,destination,catalog=[],selection={}) {
  const candidates=destinationDevices(nodes,destination);
  const results=candidates.map(n=>vlanPath(nodes,edges,source,n.id,catalog,selection));
  const paths=results.map(r=>r.path).filter(Boolean);
  paths.sort((a,b)=>a.length-b.length||a[a.length-1]-b[b.length-1]);
  const warning=results.find(r=>r.path===paths[0])?.warning||(!paths.length&&results.find(r=>r.warning)?.warning);
  return {path:paths[0]||null,candidateCount:candidates.length,connectedCount:paths.length,...(warning?{warning}:{})};
}

export function traceVpn(nodes,edges,source,vpn) {
  if(!vpn)return {path:null,warning:'VPN record unavailable in this scope.'};
  if(!vpn.device_id)return {path:null,warning:'The local VPN termination device is not documented.'};
  const path=documentedPath(nodes,edges,source,vpn.device_id);
  return {path,warning:`Tunnel status is recorded as ${vpn.status||'unknown'}. Remote routing and reachability are unverified.${path?'':' No local connection chain to the VPN device is documented in this view.'}`};
}
