# Authentication, role workspaces and Areas

## Deployment / migration checklist

1. Back up the database and attachment directory before upgrading. For a consistent
   SQLite file copy, stop the old app first (or use SQLite's online backup facility).
2. Deploy the new code. Startup adds account tables, explicit clinic `area_id`, and
   visibility/ownership columns without deleting existing records. Keep first-run
   setup on a trusted network until the initial administrator has been created.
3. Open the app and create the first administrator with a unique password of at
   least 12 characters. There is no `admin/admin` account. Setup locks permanently
   once any user exists.
4. In Administration, create Areas with latitude, longitude and default zoom.
5. Use **Clinic Area assignments** to assign every existing clinic explicitly.
   City/address text never grants access. Unassigned clinics remain in the database
   but are invisible to operational users. Admin sees only provisioning metadata here.
6. Create staff accounts. For each operational role, select permitted active Areas
   and one default. Supply a temporary password and require a change on next login.
7. Validate a staff account in each role before opening access to the team.

HTTPS is required outside localhost. Behind a reverse proxy, preserve the public
Host. Nginx Proxy Manager's standard HTTPS-to-HTTP forwarding is supported without
extra proxy headers or `FORWARDED_ALLOW_IPS` configuration for authentication. The
origin check accepts HTTPS for the exact forwarded Host/port even if the upstream
connection uses HTTP; unrelated hosts, different ports and malformed origins remain
blocked. This does not turn off CSRF checks or make session cookies insecure.
If you separately configure trusted forwarded headers for accurate client-IP logging
and login throttling, trust only the actual proxy; do not use a wildcard. Otherwise
clients behind the proxy share its IP for the per-username login throttle.
Sessions last eight hours, use random tokens stored hashed in SQLite, and use
HttpOnly/SameSite=Strict/Secure cookies. Localhost HTTP is a development exception.
Login is throttled after ten failed attempts per client/normalized username in a
15-minute window. Sign-out revokes the session. Password changes and account edits
invalidate old sessions. The last active administrator cannot be removed/deactivated.

To roll back, stop the app and restore the pre-upgrade database AND attachments with
the previous release. Do not expose an old unauthenticated release to staff against
the newly secured data. No production data is bundled in this commit.

## Daily use

- Select a daily workspace from the account menu. Its permissions are the ceiling;
  an IT assignment does not give technical access while working in Sales.
- Administration is a separate account-menu action. Admin grants no automatic
  operational access; assign an operational role separately if needed.
- Select an Area to filter all clinic-derived data. The map opens at that Area's
  configured centre/zoom. A single assigned Area is shown without a dropdown.
- Sales and Manager can create clinics in the currently selected Area. A Manager
  can reassign a clinic from its profile to another Area assigned to that Manager.
  Admin can provision any clinic's Area. Child records follow the clinic automatically.
- Client Success only sees current clients, including map pins, search and exports.
- Sales, Client Success and Manager see equipment counts/site summaries, never
  device configuration, services, IPs, serial numbers, racks or VPN configuration.
- IT maintains devices/sites/services/topology/racks/tickets and technical tasks,
  notes and attachments. Quotes are read-only; billing and pipeline edits are denied.
- Client Success quotes are read-only; Sales and Manager can edit quotes. Billing
  and inventory are available to the three business roles. Renewals remain on Clients.

## Notes and existing shared data

General notes are visible to all four operational roles. Sales notes are visible
to business roles; Technical notes only to IT. Select the classification in the
clinic's note composer. Service-linked notes are always technical. IT's standalone
uploads and new tasks default to technical; business uploads default to general.
Attachments linked to notes also inherit the note's read restriction.

Legacy notes without a classification remain General, except service-linked notes
which are excluded from business reads. Review legacy free-text notes/documents for
technical or sensitive content before assigning clinics to business staff. Passwords
must remain in your secure password manager.

Unlinked tasks, contacts and stock orders created in a workspace receive that Area's
ownership. Client Success requires a current-client association. Legacy unlinked
records without an Area remain preserved but hidden; a database maintainer must
explicitly associate them with the appropriate clinic or Area after review. Inventory
catalogue/stock items and price-book entries are still shared business reference data;
clinic-linked orders/invoices are scoped through the clinic. Do not place client
secrets in the shared inventory catalogue or email templates.

Legacy global Settings, backup/import, bulk geocoding, saved views and group/template
editing are not exposed to operational roles in this release: they have no safe
role/Area ownership. Existing settings (including configured integrations) are
preserved. Use deployment-level backups, not the former unauthenticated backup API.
Read-only templates and clinic-scoped group metadata remain available. No new AI or
VPN behaviour is introduced.

## Implementation and maintenance

- `app/auth.py`: authentication, sessions, account administration, Areas and defaults.
- `app/access.py`: deny-by-default route policy and request-scoped SQL adapter.
  SELECTs use scoped CTEs before joins/aggregates/LIMIT; temporary write guards check
  both existing ownership and new references. Scope snapshots and writes share a
  transaction. Only trusted application SQL may use this adapter.
- `app/database.py`: idempotent additive migrations. Nullable legacy clinic Areas
  are a migration quarantine, not permission to expose unassigned records.
- `app/static/js/auth.js`: sign-in, password changes, account menu, Admin screens and
  workspace UI restrictions. Backend policy remains authoritative.
- `tests/test_access.py`: real HTTP-session tests for the production application.
  `tests/test_api.py` separately exercises legacy business logic with a test-only
  dependency override; it is not an authentication bypass in the shipped app.

When adding a route, classify it in `permission_for`. When adding a clinic-owned
table or foreign-key relationship, extend `scope_rules` and the write-reference
guards. Do not open an unscoped database connection from an operational endpoint.
Area transfer and minimal map-centre metadata are explicit, reviewed exceptions.

API account operations use `/api/auth/{status,setup,login,logout,me,password,workspace}`.
Admin uses `/api/admin/users`, `/api/admin/users/{id}`, `/api/admin/areas`,
`/api/admin/areas/{id}` and `/api/admin/clinic-areas[/{clinic_id}]`.
User PUT includes the full role/Area assignments; it also handles reset-password,
require-change and activation flags. Manager transfers use
`PATCH /api/clinics/{id}/area` with `{"area_id": ...}`.

Deferred: custom permission editors, MFA, email invitations/reset delivery, client
portals, territory polygons, multi-Area clinic ownership and cross-Area VPN disclosure.
