# Topology Phase 2: interfaces, addresses, VLANs, and compact layouts

## Using the feature

In a clinic's topology, choose **Manage VLANs** to create the site's VLANs. Each
VLAN has an ID (1–4094), name, colour, description, IPv4 subnets and/or IPv6
prefixes, allocation mode, optional gateway interface, and notes. VLAN IDs are
unique within a site; another site may reuse the same number.

Open **Network…** on a topology node, or **Network interfaces & addresses** in
device details, to record interfaces. Each interface has a name, MAC address,
notes, addresses, and VLAN memberships. Assign a VLAN as access, tagged, native,
or routed. An interface may carry several tagged VLANs and at most one
access/native VLAN. Membership descriptions are documentation; they do not
configure hardware or establish that a route works.

Add as many IPv4/IPv6 addresses as needed, with optional prefix length, purpose,
hostname, notes, and VLAN association. An address's VLAN must also be assigned to
its interface. Choose one primary address per device; if none is chosen, the
first address becomes primary. IPv6-only devices are supported. Saving validates
IP versions, prefixes, MAC formatting, duplicate interface names/addresses, and
site ownership before applying the complete network edit in a transaction.
Interface removals are staged until Save; Cancel leaves stored records alone.

The topology shows the primary address and a `+N addresses` link for additional
addresses. All addresses and recorded hostnames are searchable in topology search.
The network editor displays the full list. A gateway interface cannot be removed,
or its device moved to another site, until its VLAN gateway reference is updated.
Devices with VLAN memberships must be unassigned before moving sites.

## VLAN controls

Hover or keyboard-focus a VLAN chip to preview its member devices. Click chips
to select one or more VLANs persistently. Unrelated devices dim while retaining
their type colours. Expand the selected VLAN summary for its subnets, gateway,
notes, and device/interface membership list. Tagged membership identifies an
interface carrying a VLAN and should not be interpreted as an endpoint address.

**Only selected VLANs** hides nonmember devices and retains the Phase 1 shortcut
paths through hidden intermediate devices. Search Reveal can turn off this filter
when necessary to reveal a result. Device-type filters still apply. Clear VLAN
selection returns to the ordinary view. Selections are saved per user/clinic/site
in the current browser, alongside the Phase 1 preferences.

## Layout and colours

Choose **Horizontal →** or **Vertical ↓**. Devices are packed by tier independently
of descendant counts: children no longer reserve empty rows between their parents.
Cards without services are smaller. The canvas uses the available screen height,
with fit-to-screen, pan, zoom, search focus, and branch collapse for larger networks.
Very large networks still require filtering/collapse to keep labels readable;
fit-to-screen shows the complete graph at the appropriate scale.

Device colours distinguish network equipment, servers/VMs, workstations, phones,
printers, and security equipment. VM cards have a purple background/border and
virtual links are purple. The legend and labels accompany the colour cues.
Wireless links remain dotted; compressed paths remain dashed. VLAN highlighting
does not replace device-type colours. The connection editor continues to show the
full documented graph, independently of view filters.

## Upgrade and API notes

Back up the database before deploying. Startup adds `network_interfaces`,
`network_addresses`, `vlans`, and `interface_vlans`. Existing valid single IPs
become a Primary interface/address with their MAC retained. Repeat startup does
not duplicate interfaces. Unknown legacy prefix lengths stay unknown; malformed
legacy text stays on the device for manual review. No VLAN is inferred from an IP.

The legacy primary IP/MAC fields remain for compatibility with list views and
existing reports. Network saves synchronize them. Once interfaces exist, ordinary
device edits cannot overwrite them; use the network editor. New devices created
with a legacy single IP can be converted in the network editor or at next startup.

IT and Area access checks cover all new APIs and tables. VLANs, memberships, and
gateway interfaces must belong to the correct clinic/site. Primary endpoints:

- `GET/PUT /api/devices/{id}/network` — complete interface/address/membership edit.
- `GET/POST /api/clinics/{id}/vlans` — catalog and creation; optional site filter.
- `PUT/DELETE /api/clinics/{id}/vlans/{vlan_id}` — edit/delete; assigned VLAN deletion is blocked.
- Existing topology responses include addresses, memberships, and VLAN metadata.

Interface IDs remain stable across edits. Address/membership rows are replaced
within the network-save transaction. These records do not yet support external
references to individual address IDs. Gateway references target stable interfaces.

Run the Python API/access suite and `node --test tests/topology-graph.test.mjs`.
Tests cover dual-stack saves, primary compatibility, invalid inputs, site/role
boundaries, gateway protections, migration repeatability, and compact tiers in
both orientations. Existing routing analysis, live discovery, and interface-aware
physical link configuration remain outside this phase.
