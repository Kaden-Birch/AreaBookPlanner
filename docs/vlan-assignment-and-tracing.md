# VLAN assignment, address checks and gateway-aware traces

In the topology's **Networks** tools, select a site-local VLAN and click **Assign
VLANs**. Click devices consecutively. **Done** or Escape exits the mode. A banner
identifies the active VLAN; dashed green outlines identify existing membership.
Filters, search, pan and zoom remain available. Changing the site/view exits mode.

- No interfaces: create **Port 1**, preserving any legacy address/MAC; never invent
  an address or configure physical hardware.
- One unassigned interface: assign an access membership immediately.
- Otherwise: choose one or multiple interfaces. The picker shows current addresses
  and membership modes. Tagged/routed additions preserve existing memberships.
- Replacing access/native membership requires confirmation. Explicit address-VLAN
  associations on the replaced membership follow the new VLAN and are validated.
- Existing membership is a no-op; no duplicate interfaces or memberships are added.
- If another edit occurred while the picker was open, saving is rejected instead
  of overwriting that edit. Existing interface/site/role checks remain enforced.

The interface editor checks IPv4/IPv6 addresses against the selected address VLAN,
or the sole interface VLAN when no address VLAN is selected. Multiple subnets are
supported. IPv6 link-local addresses are described separately. Missing subnet data
is reported as unvalidated. An out-of-subnet address requires **Save anyway**;
invalid IP syntax is rejected. These are documentation checks, not live probes.
Use the regular interface editor to correct or remove an assignment; this release
does not provide one-click Undo.

For device/service/subnet traces between different VLANs, the path visits the
gateway interface's device configured on **each VLAN**. Configure these in
**Manage VLANs → Edit → Gateway interface**. A router or Layer 3 switch can serve
as the documented controller. A shared Layer 2 switch is not treated as a router.
Repeated switches in a path are intentional (endpoint → switch → router → switch
→ endpoint). Missing gateways or missing connection chains produce an explanation,
not a fabricated shortcut. Multi-VLAN devices require explicit endpoint VLAN
selection. Membership alone does not verify ACLs, routing tables or reachability.
VPN endpoint tracing remains a documented local connection trace.

No schema migration is needed. `/api/devices/{id}/network/validate` returns
address-level checks; network PUT requires `confirm_subnet_warnings` for mismatches.
Quick assignment supplies `expected_interfaces` for optimistic conflict checking.
VLAN catalog responses include `gateway_device_id` for gateway-aware tracing.
