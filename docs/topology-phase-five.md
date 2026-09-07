# Phase 5 — Administration and reporting

Open **Administration & reports** in the clinic topology. IT permissions and
the current Area apply to imports, saved versions, comparisons, and audit reads.
No automatic discovery or destructive rollback is included.

## CSV imports

Choose one site, select Devices, VLANs, or Interfaces / addresses, and download
the corresponding template. Replace its example rows. Upload UTF-8 CSV or paste
text; Preview validates without saving anything. **Import reviewed rows** commits
the entire import in one transaction. Errors leave all rows unchanged.

Limits: 500 data rows and 1 MB UTF-8 text. Duplicate/unknown headers, malformed
rows, invalid fields, conflicts, and ambiguous device names are rejected.
Changing the CSV, import type/site, or underlying documentation requires another
preview. Successful imports produce one audit entry per affected clinic request.

Imports are additive:

- Devices require name and device_type. Optional columns include IP, MAC,
  serial, model, rack, room, rack position, notes, and uplink_name. Uplinks may
  reference existing or newly imported devices at the selected site, regardless
  of CSV ordering. Cycles and ambiguous/missing uplinks fail atomically. Existing
  names and serials at that site are rejected rather than overwritten. Imported
  IP/MAC values are validated and immediately stored on a Primary interface.
- VLANs require tag and name. Separate multiple IPv4/IPv6 subnets with semicolons.
  Description, colour, allocation mode, and notes are optional. Tags must be
  unique at the site. Existing VLANs are not updated.
- Interfaces identify an existing device by device_name, plus interface_name.
  Use one row per address; repeated interface rows may add multiple addresses or
  VLAN memberships. VLAN tags refer to existing VLANs at this site. Keep MAC
  values identical across rows for the same interface. Existing interfaces and
  addresses are retained, and existing interface names cannot be overwritten.

Create devices and VLANs before importing their interfaces. Interface import
supports IPv4, IPv6, prefixes, MACs, VLAN membership mode, hostname, and address
notes. Blank address rows can document interfaces/memberships alone. Secrets
must never be entered into CSV or notes.

## Filtered exports and printing

The report controls export the currently displayed graph, not a database backup.
Device-type filters, VLAN-only filtering, collapsed branches, site selection,
and logical/physical perspective apply. Pan and zoom do not crop the export:
it fits the complete filtered scene.

- JSON: visible device records, displayed links, hidden-hop counts, and view
  context. Hidden nodes are not inserted back into the exported node list.
- CSV: visible device inventory summary (ID, name, type, primary IP, site, status).
  Cells are quoted and formula-like values are neutralized for spreadsheets.
- SVG: scalable standalone diagram with the displayed colours and line styles.
- PNG: rendered image preview and download, capped at 16 megapixels / 8192 pixels
  per dimension to avoid excessive memory use on large networks.
- Print / PDF: in-page printable preview, then the browser's Print / Save as PDF
  dialog. Paper size, orientation and PDF destination are chosen in that dialog.

Visual exports include visible VPN annotations. Filtered shortcut links stay
derived/dashed, never become real cables, and do not change stored relationships.
JSON/CSV summaries are not a round-trip import format. Use the provided import
templates for import and saved-version JSON for complete documentation records.

## Saved versions and comparisons

Save a labelled version before substantial edits. A version captures the complete
authorized documentation for the selected site (or all sites), independent of
display filters. It includes devices, interfaces, addresses, VLAN memberships,
connection details, services, site records, network ranges, VPN links, and onward
access records. Attachment binaries and endpoint-directory contents are excluded.

Versions record timestamp and user identity and cannot be edited/restored/deleted
through these APIs. The list shows the latest 200 versions for the exact selected
site scope. Compare a version to current documentation or another version in the
same scope to see added, removed, and changed records with before/after fields.
Download a version as JSON. Versions are data snapshots, not saved canvas images.

## Audit tracking and privacy

Successful technical web writes automatically record timestamp, display name,
username/user ID, request path/method, entity, operation, and before/after field
values. Failed requests, previews, and display-filter changes produce no audit
changes. Audit writes commit with the corresponding technical changes.

Audit includes device/network/service/connection changes plus site, VPN-link,
network-range, and onward-access changes. It is request-based history, not
keystroke logging. Cosmetic timestamp-only updates are ignored. Paginated audit
reads respect the selected site, including movements into/out of it.

History involving other clinics is visible only while **every referenced clinic**
remains in the user's authorized Area. If a referenced clinic is reassigned, the
whole affected historical record is withheld rather than exposing old details.
Clinic deletion cascades its stored history. A deleted site's site-specific
versions are no longer selectable; all-sites versions remain useful for review.

Audit starts at deployment, not retroactively. Direct SQL edits, startup
migrations, attachment-file contents, endpoint-directory edits, and nontechnical
business edits are not covered. This is application audit history, not a
cryptographically tamper-proof compliance log: database administrators can still
alter the database. Retention/archival controls are future work; monitor database
growth and include history in filesystem/database backups.

## Deployment and verification

Back up the SQLite database and attachment directory before deployment. Startup
adds topology_versions and topology_audit with scope-reference metadata and
indexes; existing topology records are not replaced.

APIs under /api/clinics/{cid}/topology:

- POST import/preview and import/commit
- GET/POST versions
- GET versions/{id} and versions/{id}/compare
- GET audit (site, before cursor, limit)

Run the Python test suite and both Node suites:
node --test tests/topology-graph.test.mjs tests/topology-export.test.mjs

Checks cover additive imports, preview rollback, stale previews, cycles/invalid
inputs, preservation of existing interfaces, version immutability/comparison,
audit pagination, role/Area boundaries, historical VPN scope changes, CSV formula
neutralization, and immutable filtered exports.
