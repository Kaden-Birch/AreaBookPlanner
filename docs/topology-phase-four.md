# Phase 4: VPN IP path review and speed colours

## IP review

Open **VPN IP path review** in a clinic topology. Select the source site (Main
Site is explicitly selected when the topology shows all sites), enter source
and destination IPv4 or IPv6 host addresses, and click Review path.

This first routing-analysis implementation reviews documentation; it does not
test the network or claim that packets will pass. Results always say
**Reachability unverified**.

The review matches the IPs against site network ranges and VLAN subnets. It
shows matching local, direct VPN, or explicitly configured onward destinations,
the tunnel sequence and recorded statuses, and whether a reverse site path is
documented. Merely connecting A–B and B–C does not imply A can reach C: configure
onward access from A through B using the existing destination selection.

Warnings identify undocumented source addresses, no matching destination/path,
ambiguous overlapping destination address space, missing reverse onward access,
and tunnels manually marked down. Disabled links are excluded. Multiple matching
sites remain visible as ambiguous candidates; no arbitrary destination is chosen.
Network ranges and VLAN subnets are documentation, not VPN subnet allow-lists.

Buttons open the existing source-range and VPN/onward-access editors. The review
itself is read-only. IPs are not saved to browser preferences or new database
records; ordinary server request logs may contain the query parameters.

Only authorized IT/Area records participate. The general map is unchanged and
does not receive source-independent reachability colouring.

### Deliberate limits

Only direct or explicitly configured one-intermediate-site paths are reviewed.
Custom endpoints do not yet have destination subnet matching. Firewall policies,
per-tunnel subnet permissions, NAT, routing tables/metrics, arbitrary multi-hop
paths, and live probes remain future work. A documented return site path is not
proof of return subnet permission.

API: GET /api/clinics/{id}/connectivity/ip-review with site, source_ip and
destination_ip. Invalid or mixed-family addresses are rejected. Existing network
range and VLAN data are reused; no database migration is added.

## Link colours

Physical connection colours use the recorded Speed (Mbps) in Connection details:

| Recorded speed | Colour |
| --- | --- |
| Below 1000 Mbps | Red |
| 1000–2499 Mbps | Blue |
| 2500–9999 Mbps | Green |
| 10000 Mbps and above | Orange |
| Unknown | Neutral grey |

Thus 1 Gb is blue, 2.5/5 Gb green, and 10/25 Gb orange. These indicate documented
capacity, not measured throughput or health. Virtual VM-host links override
speed colouring and remain purple dots. Wireless remains dotted. Compressed
hidden-device paths stay neutral dashed lines because their component speeds
can differ. Inspect the individual segments to see their speeds.

Colours apply to logical/physical topology and the connection-editing diagram.
Device card colours remain unchanged. VPN map colours retain their existing
direct/onward meaning; rack elevations retain their existing cable styling.

## Verification

Run the Python API/access tests and node --test tests/topology-graph.test.mjs.
Coverage includes IPv4/IPv6, direct/onward/return paths, disabled/down links,
ambiguous destination networks, invalid inputs, role/Area restrictions, exact
speed boundaries, virtual precedence, and neutral compressed paths.
