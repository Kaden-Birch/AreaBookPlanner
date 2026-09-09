// Search documentation, not live discovery. Keep this independent of the DOM.
export function matchesTopologySearch(node, query, vlans=[]) {
  const memberships=new Set((node.vlan_memberships||[]).map(m=>m.vlan_id));
  const values=[node.name,node.ip_address,node.mac_address,node.serial,node.model,
    node.designation,node.user_name,node.location_name,node.rack,node.rack_room,node.rack_position,
    ...(node.interface_macs||[]),...(node.services||[]).map(s=>s.name),
    ...(node.addresses||[]).flatMap(a=>[a.address,a.hostname,a.interface_name,
      a.prefix_length!=null?`${a.address}/${a.prefix_length}`:null]),
    ...vlans.filter(v=>memberships.has(v.id)).flatMap(v=>[v.name,v.tag,...(v.subnets||[])])];
  return values.filter(v=>v!=null).join(' ').toLowerCase().includes(query.trim().toLowerCase());
}

export function matchesTopologyFilter(node, filter, issues=[]) {
  if(filter==='open-work')return (node.open_task_count||0)+(node.open_ticket_count||0)>0;
  if(filter==='open-tickets')return (node.open_ticket_count||0)>0;
  if(filter==='open-tasks')return (node.open_task_count||0)>0;
  if(filter==='servers')return ['server','vm'].includes(node.device_type);
  if(filter==='multiple')return (node.addresses||[]).length>1;
  if(filter==='documentation')return issues.some(i=>i.kind==='device'&&i.id===node.id);
  if(filter.startsWith('status:'))return node.status===filter.slice(7);
  return true;
}
