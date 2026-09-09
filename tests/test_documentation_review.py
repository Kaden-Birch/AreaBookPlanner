from app.routers.connections import documentation_issues


def test_duplicate_addresses_are_site_scoped_and_deduplicated():
    nodes=[dict(id=i,name=str(i),device_type='router',location_id=site,ip_address='10.0.0.1',addresses=[{'address':'10.0.0.1'}]) for i,site in [(1,None),(2,None),(3,5)]]
    issues=documentation_issues(nodes,[],[])
    assert [i['id'] for i in issues if i['code']=='duplicate_address']==[1,2]
    for n in nodes:n['ip_address']='fe80::1';n['addresses']=[]
    assert not any(i['code']=='duplicate_address' for i in documentation_issues(nodes,[],[]))


def test_cycles_and_duplicate_links_are_documentation_warnings():
    nodes=[dict(id=i,name=str(i),device_type='switch',uplink_id=3-i) for i in [1,2]]
    edges=[{'from':1,'to':2,'primary':True},{'from':2,'to':1,'primary':True},{'from':1,'to':2,'primary':False}]
    issues=documentation_issues(nodes,edges,[])
    assert len([i for i in issues if 'cycle' in i['message']])==2
    assert len([i for i in issues if i['code']=='duplicate_link'])==1
def test_trace_interface_evidence_follows_traversal_direction(monkeypatch):
    from app.routers import topology_trace
    nodes = [
        {'id': 1, 'vlan_memberships': [{'interface_id': 10, 'vlan_id': 100}]},
        {'id': 2, 'vlan_memberships': [{'interface_id': 20, 'vlan_id': 200}]},
    ]
    edge = {'from': 1, 'to': 2, 'link_type': 'ethernet', 'details': {
        'source_interface_id': 10, 'target_interface_id': 20,
        'source_interface_name': 'LAN A', 'target_interface_name': 'LAN B',
        'vlan_mode': 'routed',
    }}
    monkeypatch.setattr(topology_trace, 'topology', lambda *args: {
        'nodes': nodes, 'offsite': [], 'edges': [edge],
        'vlans': [{'id': 100, 'tag': 10, 'name': 'Office'}, {'id': 200, 'tag': 20, 'name': 'Servers'}],
    })
    result = topology_trace.local_segment(None, 1, 'main', 2, 1)
    link = result['links'][0]
    assert result['complete'] and [n['id'] for n in result['nodes']] == [2, 1]
    assert link['details']['source_interface_name'] == 'LAN B'
    assert link['source_vlans'] == ['20 · Servers']
    assert link['destination_vlans'] == ['10 · Office']
    assert 'routed interface documented' in link['vlan_boundary']
    assert edge['details']['source_interface_name'] == 'LAN A'
