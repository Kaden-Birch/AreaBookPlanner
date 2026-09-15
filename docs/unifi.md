# UniFi Network integration

## Onboarding

- Discover managed gateways, switches and access points, including reported port inventory.
- Read currently connected wired/wireless clients and cross-reference their MAC addresses with existing AreaBook/Syncro machines.
- Review networks, VLANs and reported subnets without altering UniFi configuration.
- Inspect dated VPN descriptions and reported uplinks; unavailable endpoint/port details remain unknown.

Create a shared API key at [unifi.ui.com](https://unifi.ui.com). An organization key can access organization consoles; a personal key is limited by the owner's console access. Merely seeing a console as an invited administrator does not guarantee connector access. Follow least-privilege policy for the key. AreaBook's transport itself is strictly GET-only regardless of the key's permissions.

Cloud access requires compatible consoles on firmware 5.0.3+ with a supported Network integration API. A self-hosted/older Network server appearing in Site Manager may not support the connector. This version does not add a legacy-cookie or direct-controller fallback. There is one global key, not a key per clinic.

A minimal Network read (replace the two placeholders):

```sh
curl --fail --silent --show-error \
  -H 'X-API-Key: YOUR_API_KEY' \
  'https://api.ui.com/v1/connector/consoles/YOUR_CONSOLE_ID/proxy/network/integration/v1/sites'
```

The console ID is the host ID returned by Site Manager, not the Network site's UUID. AreaBook discovers these IDs for you. No curl command is required to use the UI.

1. Sign in as an administrator. Open **Global settings → UniFi**.
2. Save the key once and click **Test saved connection**. This tests console discovery, not every console's Network permissions.
3. Open **Clinics → Import from UniFi**, or use the button in Global settings.
4. Select a console, its Network site, an existing AreaBook clinic and Main Site or a secondary site. Create the clinic/site normally first if it does not exist. Each UniFi site has one saved local mapping, and each local site has one UniFi mapping.
5. Build the preview. Review matches and choose skip, create or a specific existing machine. Ambiguous/IP-only candidates default to skipped. New unidentified clients use **Other** rather than an invented workstation/phone classification.
6. Optionally add missing VLANs and fill missing reported uplinks. Confirm the import. Inspect **UniFi network observations** on the clinic page for timestamped source data and warnings. IT users can view their Area's observations; only admins can discover/import across the shared account.

For onboarding assistance, choose:

a) Walk me through my first authenticated call

b) Help me find endpoints for a specific capability (I'll name it)

c) Build a recipe for a specific goal (I'll describe it)

## Matching and preservation

Source identity is `(console, Network site, kind, source ID)`. Repeat imports reuse saved links. New observations match a unique normalized MAC on the device or one of its interfaces, strictly within the selected clinic/site. IP/name-only similarities and duplicate MACs require review. Deleted/moved source-linked devices are skipped rather than silently recreated. Source links cannot be reassigned during import.

Matched machines keep their name, type (including VM), OS, serial, services, tickets and manual documentation. Blank model/MAC fields may be filled. An eligible address can fill an empty uniquely MAC-matched interface with no VLAN assignment, or an interface can be created on a machine with none if its legacy MAC is compatible. Existing addresses are never replaced. Other conflicting details stay in the source snapshot. New managed devices also receive reported physical ports; manual port layouts on matched devices are not rewritten. Reported maximum/current speeds are notes, not a fabricated list of all supported negotiation speeds.

LAN address filtering is the same as Syncro: RFC1918 IPv4 only; no APIPA, public IPv4, loopback or multicast. IPv6 global and unique-local addresses remain supported, excluding scoped/link-local, loopback, multicast, unspecified and IPv4-mapped addresses. This does not delete manually documented addresses.

New VLAN tags and subnets can be added. Existing tags at the local site are preserved in full; controller and interface membership are not inferred from an IP range. VPN API records in this contract expose only ID/name/type, so they remain observations rather than invented AreaBook VPN links. Guest/VPN credentials, arbitrary raw properties and user details are not retained.

The optional uplink import uses explicit source device IDs only, fills empty relationships and leaves exact ports unknown. It preserves existing uplinks and VM hosts, and avoids introducing parent cycles. Wireless clients get wireless relationships, wired clients Ethernet; infrastructure media remains unknown when not reported. This is not a cable-discovery guarantee, real-time health monitor or complete inventory of offline clients.

## Safety and verification

Requests go only to `https://api.ui.com` using an allowlist of GET paths; redirects are refused, TLS verification remains enabled, and credentials stay out of URLs and response bodies. Collection limits: 100 pages, 10,000 records, 8 MB per response, 90-second operation budget and per-process throttling below 100 requests/minute. Rate-limit failures are explicit; no automatic mutations or retries against write endpoints exist. A failed device/client collection aborts the preview; optional network/VPN failures and device-detail fallbacks are visible warnings.

Previews expire after 30 minutes, belong to the requesting admin, and are single-use. Rotating/removing the key invalidates previews. A changed local topology requires a new preview before committing. Imports are transactional and topology changes enter the existing audit trail. No source deletion removes local devices.

The key is stored server-side in the existing settings database, not returned to the browser and not encrypted by a separate secret vault. Protect the Docker database volume and backups. Local JSON export/restore is not a substitute for a full database backup of integration mappings and settings.

Automated verification uses sanitized contract-shaped fixtures, including Syncro-style MAC matching, repeat imports, preservation, scope checks, pagination and GET-only transport. A real console connection must still be tested after deployment using the saved key.

Official references: [Network onboarding](https://developer.ui.com/network/v10.4.57/ai-gettingstarted.md), [Network contract](https://developer.ui.com/network/v10.4.57/openapi.json), [Site Manager connector contract](https://developer.ui.com/site-manager/v1.0.0/openapi.json). The connector GET path follows the Network contract's cloud server URL.
