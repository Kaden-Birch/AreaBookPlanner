# Topology specification completion follow-up

This is a chronological development log. Outstanding and pending statements below describe the state at that pass, not the current release. See [current completion checklist](topology-completion-checklist.md) for the consolidated implementation and verification status.

## First pass

- Search now includes device/interface MACs, VLAN names/tags and documented VLAN subnet strings, IPv6 prefixes, rooms and rack positions, in addition to existing device/service fields. This is text matching, not subnet containment analysis.
- Optional “Only search matches” uses the existing non-mutating hidden-path compression.
- Quick filters cover servers/VMs, multiple structured addresses, device documentation issues and recorded statuses. Filters combine with type and VLAN restrictions.
- Choosing a search result clears the quick filter and reveals the device using the existing reveal behavior. Reset clears search and quick filters.
- Equipment topology VPN annotations are optional, default off, and remembered with the existing browser-scoped view preferences. The VPN detail directory remains available while the overlay is hidden.
- Export context records these view controls. Quick/search filters are session-only; no database migration is required.

## Second pass: navigation and saved presentation

- Logical topology supports dragging device cards in explicit Move devices mode. Keyboard users can focus a device and use arrows (10 units) or Shift+arrows (50 units).
- Coordinates are stored per existing user/clinic/site preference key, perspective and orientation in browser storage, not shared across browsers or users. Corrupt/out-of-range coordinates are ignored. Filtered-out device positions are retained.
- Reset positions restores automatic layout for the current orientation. Physical placement remains automatic to preserve room/rack group boundaries.
- A minimap shows the current viewport and all displayed devices/VPN annotations. Click to centre, use arrow keys to pan, or activate with Enter/Space to fit. It follows zoom and filters.
- JSON view exports now include displayed VPN annotations and visible device coordinates alongside the filter context. This is presentation data, not a restore/import format.

## Still outstanding

Open ticket/task filters, full routing-aware visual path tracing (remote sites, VLAN transitions and onward VPN hops) and VPN display refinements remain separate work. Manual positioning in grouped views and shared server-side layouts are not provided. These passes do not complete the original specification.

## Integration verification update

Browser checks on the local synthetic fixture confirmed local device trace output and focus breadcrumbs, missing VPN termination messaging, subnet grouping, hiding a recorded-down VPN, device-specific documentation review, and saving the IPv6 flag followed by its warning. Focus now scrolls the canvas into view. Earlier “browser verification pending” notes remain applicable to untested cases, including service/subnet trace selections and complete remote routing workflows. This is not production deployment verification or full acceptance of the original specification.

## VPN status display pass

Equipment topology now mutes recorded unknown/disabled VPNs and outlines recorded down VPNs in red. A session-only “Only VPNs recorded Up” filter hides all other statuses. It is not live monitoring or relative reachability. JSON exports use the same filtered VPN list as the canvas. Selecting a VPN trace explicitly reveals its tunnel, clearing the status filter. Reset filters also clears it. Source-relative onward VPN presentation remains outstanding. Browser verification is pending.

## IPv6 documentation pass

The network editor includes an explicit “IPv6 is enabled” documentation checkbox. The new device column defaults to false, meaning not explicitly marked enabled; it is not evidence that IPv6 is disabled. Enabled devices without a recorded IPv6 address receive a documentation warning. Existing callers omitting the field preserve the recorded value. This never changes network configuration. Browser verification remains pending.

## Subnet layout pass

The View selector now offers Subnet groups. Devices are grouped by site and identical documented subnet membership sets; multi-subnet devices appear once, with combined subnet headings. Unknown memberships have a separate group. Existing connections, filters, tracing, exports and minimap use the same derived graph. Group placement is automatic in both orientations. Tests cover unknown memberships, IPv4/IPv6 combinations, site isolation, unique node placement and input preservation. Browser verification is pending.

## Fifth pass: local adjacency tracing and focus navigation

- Source/destination device selectors find one shortest undirected documented connection chain in the current site/view scope. Unrelated devices/links dim; compressed links highlight only if their entire hidden chain belongs to the selected path.
- The trace lists intermediate devices even when hidden. Clicking a visible device focuses it; clicking a hidden device opens its documentation. A focus breadcrumb returns to the overall topology. Clear trace removes highlighting.
- This is not IP routing, live discovery or proof of reachability. It does not select service/subnet/site destinations, evaluate VLAN transitions or traverse VPN links. Alternate and parallel paths are not enumerated. No path found means documentation is insufficient, not that communication is impossible.
- Node tests cover cycles, reverse traversal, absent endpoints, disconnected devices and compressed-chain highlighting. Browser verification remains pending for this pass.

### Destination extension

The destination picker also accepts services (trace ends at the documented host) and documented subnets (trace ends at the nearest connected member). Subnet results report total members versus members with a documented adjacency chain. A member is not assumed to be a gateway, and reaching a host does not establish service/port reachability. These shortcuts do not replace the outstanding routing-aware site/VPN/VLAN-transition analysis. Tests cover disconnected subnet members and missing service records.

### VPN termination extension

VPN endpoint destinations now trace the local chain to the documented termination device, enable the VPN overlay and offer the tunnel detail screen. Missing termination devices or missing local chains produce explicit warnings. The recorded tunnel status is shown, including disabled/down/unknown; a local adjacency path is never labelled remote reachability. Remote internal paths and onward transit routing remain unimplemented in this canvas trace. VLAN memberships can be inspected per device along a chain, with an explicit distinction from interface-level VLAN transitions or routing. Browser verification remains pending.

## Fourth pass: actionable documentation review

- Dashboard missing-interface alerts now identify each affected device and link directly to its existing detail screen over the topology.
- Clicking a topology documentation badge scopes the review to that device and its connection issues. “All documentation issues” returns to the complete list.
- Added warnings for repeated addresses within a site (excluding IPv6/IPv4 link-local addresses and retired devices), primary-uplink cycles, and repeated endpoint pairs. Intentional shared addresses and parallel links are explicitly treated as possibilities, not confirmed faults.
- These checks operate only on the scoped topology data. They do not establish live connectivity or identify inaccessible/out-of-scope devices. Broader dashboard aggregation of every check remains future work.

## Third pass: logical groups and subnet filtering

- Shared site-scoped logical groups have names, descriptions, colours and explicit device membership. The group directory supports create, edit, delete, collapse and expand. Deleting a group never deletes devices or connections.
- Group edits are IT-only, Area-scoped and included in topology versions/audit. A new `topology_groups` table is created on startup. Members from other clinics/sites are rejected. Deleted or moved devices are excluded when reading a group.
- Collapse state is browser-local. A device in multiple groups remains hidden if any containing group is collapsed. Search reveal expands its containing groups; Reset filters and Expand all clear collapsed groups. Group controls remain accessible when members are hidden.
- Subnet filtering uses normalized IPv4/IPv6 interface prefixes and same-site VLAN networks that contain a documented device address. Legacy device IPs participate in VLAN subnet matching. It is documentation-based, not a routing/reachability assertion. Unknown-address devices are omitted from subnet results.
- Device ticket records currently have no open/closed status, and tasks have no per-device association. An accurate open-work filter needs those data-model/UI additions; ticket existence is not presented as open work.
