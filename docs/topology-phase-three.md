# Topology Phase 3: connection documentation and physical placement

## Connections

Click a topology line to document its source and target interfaces, speed in
Mbps, duplex, media, VLAN mode, access/native VLAN, tagged VLANs, recorded
administrative status, and purpose/notes. Create the endpoint interfaces using
each device's Network screen first. Hover a line for a compact summary.

These are manually recorded facts, not live monitoring or device configuration.
Unknown is the default; enabled does not mean reachable. Never store credentials
or other secrets in connection notes.

Use Edit connections to create or remove actual relationships. Connection details
attach to an existing primary or extra device pair. They cannot create links.
Clicking a shortcut through hidden devices lists the real chain, with a separate
button for each actual segment; the shortcut itself is never editable.

Tagged VLANs require trunk mode. A native VLAN cannot also be tagged. Carried
VLANs must belong to both devices' site, and chosen interfaces must belong to
their respective endpoint. Referenced interfaces and VLANs cannot be deleted
until their connection references are removed. Devices carrying connection VLANs
cannot move sites until those assignments are removed.

## Views

The View selector offers Logical network and Physical placement, independently
of the horizontal/vertical layout selector. Preferences remain browser-local,
per user, clinic, and site.

Logical retains the network hierarchy, VMs, and purple virtual links. Physical
excludes VMs and virtual relationships and groups physical equipment by site,
room, and rack. Missing placement is explicitly labelled. Groups have bounded
width and compact rows; large inventories still need filters or zoom. This view
is a placement overview, not a scaled floor plan or rack elevation. Use Racks
for the existing detailed elevation.

Both views retain device colours, search, type filters, VLAN highlighting,
collapse, and pan/zoom/fit. Filters never change stored connections.

## Documentation review

The expandable review lists missing addresses, interfaces, VLAN memberships,
uplinks, server/VM services, VLAN subnets/gateways, and connection endpoint
interfaces. Trunks are checked for missing carried VLANs and disagreement with
tagged endpoint interface memberships. Retired devices are excluded from device
checks. These are review prompts, not proof of faults: some gaps are intentional.

Amber exclamation marks on devices open the review. Each review item links to
the relevant device, network, VLAN, or connection editor. The IT dashboard also
links clinics with missing interface documentation to their topology. Existing
IT role, Area, clinic, and selected-site scope remains enforced.

## Deployment and API

Back up the SQLite database and attachments before upgrading the Docker image.
Startup adds connection_details and connection_vlans, plus cleanup triggers;
existing links remain unchanged and start with unknown documentation.
Metadata is removed when its last actual primary/extra relationship is removed.

- GET/PUT /api/clinics/{cid}/connections/{parent}/{child}
- Topology adds edge details, physical_nodes, physical_edges, and documentation.

Run the Python test suite and node --test tests/topology-graph.test.mjs.
This phase does not implement discovery, live link status, automatic hardware
configuration, IP routing analysis, or parallel per-port cables between the same
device pair.
