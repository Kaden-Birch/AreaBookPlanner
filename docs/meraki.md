# Meraki read-only integration

## Setup

Each clinic has its **own server-side API key**. There is no shared/global Meraki credential and no fallback to another clinic's key.

1. Enable Dashboard API access in Meraki. Use a dedicated Dashboard identity with read-only access to the intended organizations/networks; API-key permissions follow that identity. AreaBook itself implements only allowlisted GET requests, even if a more privileged key is supplied.
2. As an AreaBook administrator, open **Global settings → AI & integrations → Meraki**, choose the clinic and click **Set up / import Meraki**. The same button appears in the clinic's Meraki section.
3. Save that clinic's key, then click **Test key & load organizations**. Select the organization, Meraki network and matching AreaBook site (Main Site or an existing additional site).
4. Build a preview, review matches and confirm. A remote network can map to only one clinic/site; an AreaBook site can have only one Meraki mapping. Multiple sites in a clinic use that clinic's key.
5. To refresh periodically, enable [Automatic integration sync](integration-sync.md). Meraki joins the staggered queue, with the same default 30-minute target, pause, interval and queued Sync now controls. It reads the key belonging to each job's clinic.

Removing a key preserves documentation, but that clinic's refreshes fail safely until a key is restored. Replacing/removing a key invalidates its outstanding previews. Keys are never returned by the API, included in snapshots, or included in the application JSON export. They are stored in the database, not in a separate encrypted vault: protect Docker volumes and full database backups. Local JSON export does not back up mappings or credentials.

## Imported information

- Managed devices: name, product type, model, serial, manufacturer, firmware, management IP/MAC when supplied.
- Clients observed in the last 24 hours: description, manufacturer/OS, MAC, eligible IPv4/IPv6 addresses, reported status and latest attachment/VLAN observations. An observed client is not necessarily online now.
- New switches: reported port inventory, with port name/order and allowlisted access/trunk/native/allowed/voice VLAN, PoE, enabled and negotiation settings recorded as port notes. Supported speeds and connector types are not invented. Existing port layouts are preserved.
- Appliance VLAN names/tags/subnets can fill missing local VLAN definitions. Existing definitions, controller assignments and interface memberships are not replaced or inferred.
- Site-to-site VPN mode, hub network IDs and advertised local subnets are observations, not automatic VPN links or proof of routed reachability. No shared secrets, usernames, raw configuration blobs or arbitrary source notes are retained.
- Network LLDP/CDP nodes and links are available in the source observations. Undirected/discovered/stack links are not assigned arbitrary uplink directions or treated as verified physical cables. A Meraki network without supported topology data shows a warning.

Unique exact MAC matches in the selected clinic/site reuse existing devices, including Syncro imports. IP/name-only matches and duplicate MACs need review. Existing names, VM types/hosts, services, manual fields, addresses and wiring are preserved. An explicitly selected match must belong to that same site. Existing source links cannot be silently reassigned or recreated after a local deletion.

The optional uplink checkbox fills only missing relationships from **online clients with explicit wired/wireless attachment reports**, and only between selected devices in this import. It preserves VM hosts and existing links and rejects cycles. Exact port references remain observations; an upstream client observation may traverse an unmanaged downstream device, so review it before enabling.

IPv4 uses the same RFC1918-only filter as Syncro/UniFi; public addresses and APIPA are excluded. IPv6 global and unique-local addresses are supported; link-local/scoped, multicast, loopback, unspecified and mapped IPv4 addresses are excluded. Management interfaces are labelled reported, not assumed physical ports.

Automatic refresh can update source-owned IP/OS/model fields when unchanged locally. Manual overrides stay protected. New devices, adapter/VLAN/port changes, missing records and VPN/topology changes go to the review queue; no automatic device deletion or wiring changes occur. Repeat reviewed imports fill eligible blanks, not conflicting documentation.

## Safety and limits

Setup/import/key changes are admin-only. Saved technical observations follow IT Area permissions; business workspaces cannot read them. Local import changes use the topology audit trail. Credential changes log metadata only.

Transport is fixed to `https://api.meraki.com/api/v1`, with TLS verification and redirects disabled. Pagination checks the exact host/path and extracts only the next cursor; it never forwards a key to a supplied Link URL. Reads are bounded to 8 MB/response, 10,000 rows/collection, 100 pages and 240 seconds per operation. Core inventory failure aborts; optional ports/VLAN/VPN/topology failures are warnings. HTTP 429 aborts for retry with the shared cooldown.

All clinic keys share a conservative application-wide pacing budget (one request every 0.7 seconds) and one background Meraki worker lease across processes. This also protects organizations shared between keys. Other tools still consume the same upstream budget; Retry-After and backoff can delay the 30-minute target. The database and pacing sidecar must be shared by application workers.

Verification uses synthetic API responses; no production Meraki connection is tested by the automated suite. Test each clinic's real key and review its first preview after deployment. This implementation targets the standard global Meraki API endpoint, not regional sovereign-cloud endpoints.

Official references: [Authentication](https://developer.cisco.com/meraki/api-v1/authorization/), [rate limits](https://developer.cisco.com/meraki/api-v1/rate-limit/), [pagination](https://developer.cisco.com/meraki/api-v1/pagination/), [clients](https://developer.cisco.com/meraki/api-v1/get-network-clients/), [devices](https://developer.cisco.com/meraki/api-v1/get-network-devices/), [switch ports](https://developer.cisco.com/meraki/api-v1/get-device-switch-ports/), [VLANs](https://developer.cisco.com/meraki/api-v1/get-network-appliance-vlans/), [VPN](https://developer.cisco.com/meraki/api-v1/get-network-appliance-vpn-site-to-site-vpn/), [LLDP/CDP topology](https://developer.cisco.com/meraki/api-v1/get-network-topology-link-layer/).
