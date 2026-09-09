# Topology completion checklist

## Delivered implementation

| Specification area | Implementation |
| --- | --- |
| Device visibility | Type selection, show/hide/reset, search, counts and saved browser preferences. Hidden intermediate devices become explicitly marked compressed relationships without changing stored connections. Storage, UPS and Medical Equipment are selectable types; Other handles uncategorized equipment. |
| VLANs | Site-scoped VLAN documentation, IPv4/IPv6 subnets, interface memberships, hover preview, persistent selection and member filtering. |
| Addresses | Multiple structured addresses per interface, IPv4/IPv6 validation and primary-address display. Explicit IPv6-enabled documentation supports missing-address warnings. |
| Layout/navigation | Compact horizontal/vertical layouts, logical/physical/subnet grouping, pan/zoom/fit, branch collapse, minimap, focus navigation and manual logical-view positioning. |
| Logical groups | Shared site-scoped name, description, colour and device membership; browser-local collapse/expand. Removing a group preserves equipment. |
| Connections | Interface-aware connection metadata and documentation review; speed colours remain red below 1 Gb, blue from 1 Gb, green from 2.5 Gb and orange from 10 Gb. Virtual relationships retain purple dotted lines. Unknown and compressed links remain distinct. |
| Search/filters | Device/service/address/MAC/VLAN/subnet/placement search; type, site, VLAN, subnet, status, server/VM, multiple-address, incomplete-documentation and open-work filtering. |
| Local path analysis | Documented device chains, service-host and nearest documented subnet-member destinations, VPN termination analysis, hidden-chain highlighting and focus navigation. |
| Cross-site path analysis | Source-device-relative local chains plus direct or explicitly configured onward VPN hops. Device/service-host or site-termination destinations, interface/VLAN evidence, tunnel notes and documented site subnets. Missing local chains and terminations are explicit. |
| VPN presentation | Optional equipment overlay, recorded-status presentation and Up-only filter; source-relative direct/onward path presentation uses green/orange. Existing VPN map and IP path review remain available. |
| Documentation review | Device-specific topology review and dashboard links, missing network documentation, duplicate addresses, ambiguous parallel connections and uplink cycles. Warnings are review prompts, not proven network faults. |
| Import/export/history | Existing device/VLAN/interface imports, filtered reports and view exports, topology versions and audit history. Export context includes the new filtering and visible positions. Group and device-linked task/ticket changes participate in history. |

## Open-work behaviour

- Device and service-linked tickets have manually recorded `unknown`, `open` or `closed` status. Existing tickets migrate to `unknown`; their existence is never treated as an open issue.
- IT can associate a technical task with a device in the same clinic. Device detail offers creation and editing, including completion.
- Open-work filters count explicitly open tickets and incomplete device-linked tasks. Closed tickets, unknown statuses and completed tasks do not match.
- Clinic/Area visibility and role checks apply on the server, including direct trace requests. A client cannot assign a task to equipment in another clinic.
- If the task device list fails to load, saving is blocked rather than silently clearing an existing association.

## Intentional limits

- This release documents networks; it does not probe equipment or establish live reachability. Recorded Up is not proof of connectivity. Firewall policy, NAT, return routing and actual subnet forwarding remain unverified.
- Local tracing selects one shortest undirected documented adjacency chain, not every alternate path. Service selection ends at its host; subnet selection does not imply every member is reachable.
- Cross-site tracing follows the existing direct/explicit one-intermediate-site transit model. It does not invent additional transit permissions or discover arbitrary recursive routes. Disabled tunnels are excluded; down/unknown remain clearly recorded, not live, statuses.
- VLAN/interface evidence indicates shared membership, mismatch, routed documentation or missing evidence. It does not simulate switching or routing policy.
- Manual positions are browser-local, scoped by user/clinic/site/view/orientation, and available in Logical network. Grouped physical/subnet layouts remain automatic. Group membership is shared, but collapse state is local.
- Multiple MAC addresses per interface and live discovery remain future work, as anticipated by the original specification.
- Exports are documentation/presentation reports; exported browser coordinates are not a database restore format.

## Verification and rollout

- Automated coverage exercises authenticated role/Area isolation, directional explicit transit, disabled tunnels, open-work counts, group validation/history, IPv4/IPv6 subnet membership, documentation checks, compression/layout, filtering, navigation, exports and trace evidence orientation.
- Local synthetic-fixture browser checks covered topology rendering, local tracing/focus, groups, subnet layout, IPv6 documentation, VPN status filtering, cross-site incomplete-termination messaging, and device-linked task creation/detail display.
- Full end-to-end browser coverage of every filter combination, complete remote route and production migration is not claimed. Run a deployment smoke test against a backed-up staging database before production rollout.
- Startup migrations add ticket status, device-linked tasks, logical groups and the IPv6 documentation flag without discarding existing records. Back up the SQLite database before updating.
- Release validation: 83 Python tests and 25 JavaScript tests pass, including a populated legacy-schema upgrade repeated across two startups, SQLite integrity/foreign-key checks, JavaScript syntax checks and `git diff --check`.
- The local Docker daemon was unavailable, so a container build/runtime smoke test was not performed. The Python application startup is exercised by the authenticated API tests. Production deployment remains a separate step after pushing the release.
