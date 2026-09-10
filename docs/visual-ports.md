# Visual ports and uplink selection

Open device details → **Ports & connections**. Add named groups such as 24 GbE
ports and four SFP+ ports. Groups use two rows with sequential-across-row or
odd/even numbering. Odd counts leave a spare position; large groups scroll rather
than wrapping into three rows. The existing 100-interface/device limit remains.

**Colour by Speed/VLAN** is stored per user in the current browser. Speed colour
uses the documented connection speed when connected, otherwise the interface's
capability. Grey means unknown, not down. VLAN mode shows access/native colour,
tagged markers, a trunk badge and overflow count. Hover for configuration details.
Click ports individually, Shift-click a range, or select all. Bulk actions add or
remove selected VLANs, replace all tagged memberships, or set access/native/routed
membership. No changes apply merely by selecting ports.

Capabilities include supported Mbps values, connector and optional installed-module
speeds. SFP/SFP+/QSFP inference requires module capability. The highest intersecting
speed is inferred only when both endpoint capabilities are known. Link overrides
take priority and are labelled separately; incompatible overrides show a warning.
Existing stored speeds remain overrides without a destructive migration. Editing
addresses in the older network editor preserves the new interface metadata.

The device editor exposes **Uplink port** after choosing an uplink, plus **This
device's interface**. Unknown port is a nullable endpoint, not a fabricated NIC.
Changing the uplink clears old choices. Occupied physical ports are marked and
server-side checks prevent reuse. Device/uplink/port edits commit atomically.
To reuse a port, first edit the old connection to another or unknown endpoint.
There is no silent automatic disconnect of another device.

Selecting one graphical port offers **Connect selected port to device**. A device
with no uplink receives a primary connection; otherwise a new pair is an extra
connection. The pair is shared by both endpoint views. Existing pairs are updated
without losing their link-speed overrides or carried-VLAN notes. Failures roll back
the whole connection operation.

Connection details preview upstream VLAN availability and warn about native VLAN
disagreement or missing upstream tagged memberships. They do not copy upstream
configuration into downstream interfaces. These are documentation checks, not
switch configuration or live monitoring. Full virtual-switch/port-group modelling,
multi-hop VLAN propagation, drag-selection and one-click reassignment of occupied
ports are not included in this initial implementation.

Database migration is additive in `network_schema.initialize`. Existing interface
IDs and connection IDs are preserved. New interfaces default to unknown capability.
IT-scoped APIs remain authoritative; UI visibility is not an authorization boundary.
