# Topology Phase 1

The topology now has a bounded canvas with background dragging, scroll/button
zoom, fit-to-screen, and 100% view. Keyboard users can focus the canvas and use
arrow keys to pan and plus/minus to zoom. Device, service, branch, and link
controls support Enter and Space. A compact outline layout places siblings down
the canvas instead of spreading them across a wide horizontal row.

## Visibility and search

Open **Device types** to show or hide any network device type represented in the
selected clinic/site. The menu has a type search, Show all, and Hide all. Passive
rack fixtures continue to appear in the existing rack view. Reset filters restores
all types, expands branches, and clears the topology search.

Search matches device names, recorded IP addresses, services, serial numbers,
models, designations, users, and locations. Results include filtered and collapsed
devices. Selecting a result centers it at readable size; Reveal enables its type
and expands its ancestors as necessary. Search does not claim to search future
VLAN/interface records.

Device-type selections and collapsed branches are saved in browser local storage,
keyed by user ID, clinic ID, and site selection. They survive page reloads and are
independent between users/sites on that browser. They do not sync between browsers.
Only type names and device IDs are stored, not copies of clinic records. Clearing
browser storage clears these preferences.

## Hidden paths and collapsed branches

For `switch → phone → workstation`, hiding phones produces a dashed shortcut
from switch to workstation. Its label reports the hidden-device count; selecting
it displays the documented chain. Primary and additional connections participate
in compression. Direct and derived connections remain distinguishable. When
several equivalent hidden paths reach the same visible endpoint, the view retains
a representative shortest chain for each primary/additional connection category.
This is documentation visualization, not routing or reachability analysis.

Branch controls on devices with downstream equipment collapse or expand their
primary descendants and display a descendant count. This provides groups such as
a server and its VMs or a switch and its attached devices. Collapse branches folds
all branches; expanding an outer branch leaves its inner branches folded until
expanded. Expand all opens the full graph. Hiding a folded branch header disables
that header's collapse effect, so its visible children remain discoverable.
Custom named groups and manual positioning are future enhancements.

Collapsed descendants are omitted rather than compressed into misleading shortcuts
through the group. Filters never change device records, uplinks, services, or
connections. Paths only use the nodes/edges returned by the authorized clinic/site
API; filtering cannot introduce connections to a site outside that response.

VPN endpoints remain available in the diagram and a links list. If their local
device is filtered out, the endpoint indicates that its local device is hidden.
The dedicated VPN map continues to provide the broader connectivity view.

**Edit connections** opens the existing complete connection editor. View filters
resume after Done editing. Derived shortcut links are never editable records.

## Verification

Run `node --test tests/topology-graph.test.mjs` for the display-graph checks and
`python -m pytest tests -q` in the project's Python environment for API/access
regressions. Graph checks cover hidden paths, extra links, cycles, collapse,
disconnected devices, and a 500-device wide branch. Browser checks cover filter
persistence, shortcut inspection, search reveal, collapse, and camera controls.

This phase adds no database migration. VLANs, interfaces, and multiple IPv4/IPv6
addresses remain Phase 2.
