# Port workflows

Device details display the port diagram directly. Port groups follow creation order in one horizontally scrollable strip, with labels above and no more than two rows per group. Single-port groups use one square.

Click a port to edit its name, MAC, notes, VLAN memberships and multiple IPv4/IPv6 addresses (prefix, purpose, primary designation, hostname and notes). Device IPv6 documentation remains available. Saves retain other interfaces and port capabilities, validate VLAN subnets, and reject stale network snapshots rather than overwrite another edit.

Ctrl/Command-click selects ports for bulk actions; Shift-click selects a range. Select all and Clear selection remain available. Bulk VLAN and capability editing are unchanged.

In topology, open Networks → Connect physical wire. Click the upstream device, select a free physical port or Unknown port, then click the downstream device and select its port. Saving uses the existing connection model: a device without an uplink gains one; a device with another uplink retains it and gains an extra relationship. An existing relationship between these endpoints is updated, not duplicated. Existing uplink selectors remain available.

Physical wiring rejects VMs, virtual interfaces, occupied sockets and invalid relationships on the server. Unknown port does not reserve a socket. Cancel wiring exits without saving. This is documentation only, not hardware configuration or live link detection.
