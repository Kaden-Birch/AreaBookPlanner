# Authentication, role workspaces and Areas

## Global settings and personal preferences

Global settings (`#/application-settings`) are administrator-only and contain the shared OpenAI key/models, AI import options, quote price book for services/equipment, company quote defaults and templates. An admin has a direct **Global settings** link in the account menu. Other users can use these shared defaults in their permitted workflows, but cannot change the global price book or configuration. Existing quotes retain their saved values.

My settings (`#/settings`) contains personal appearance and browser-notification preferences. The default light/dark choice is saved per account and applied at sign-in; the top-bar toggle remains a temporary override. The preferences API rejects API-key/model fields.

This policy supersedes the earlier personal-AI-key behaviour described below. All AI requests now use shared settings only. Old personal-key records remain inactive in the database for non-destructive compatibility; they are not automatically promoted into shared settings or used by AI requests. Administrators should confirm the shared key in Global settings after upgrading, particularly if they previously configured only a personal key. Protect database backups, which may still contain historical credentials.

## Administrator access — updated September 9, 2026

Admin now grants full application access, superseding the original administration-only policy below. Existing admin accounts automatically receive all workspace choices and all active Areas without additional assignments. Area selection sets workspace context; it does not restrict an administrator's data access. Non-admin users retain their existing role and Area restrictions.

Use the top-right workspace selector to enter IT, Sales, Manager or Client Success. Administration remains a separate screen for managing accounts and Areas. Global application settings are available from Administration or My settings at `#/application-settings`; personal API-key preferences remain at `#/settings`. Global settings read and update the shared key, not the administrator's personal override. Password-change requirements, authentication and cross-origin protections still apply to admins.

Grant Admin only to fully trusted operators: it permits cross-Area records, global configuration, and the legacy backup/import/export functions. No production accounts or data need to be migrated manually for this policy change.

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

## IT dashboard

The IT landing page now shows current-client, documented-device, server/VM and overdue
task counts, an attention queue, work scheduled through the next seven days, and
searchable clinic cards with site/device/service totals and equipment/topology/rack
shortcuts. Summary cards filter the relevant section. Lists initially show five work
items and six clinics, with controls to expand them. Refresh reloads the overview.

The default is current clients in the selected Area; an explicit checkbox includes
other relationships without changing Area permissions. Unlinked Area tasks remain
included. These are Area tasks, not personal assignments. Attention includes overdue
tasks, current clients with no equipment, services with neither support URL nor email,
and visible VPN links manually marked down. No live health, uptime, or monitoring
claims are inferred from missing documentation. All equipment statuses count as
documented; scheduled appointments include today's entries. Technical activity history
is deferred until reliable change events are recorded.

`GET /api/it/dashboard?include_prospects=false` is IT-only and uses the centralized
scoped database connection for every source. Switching roles or Areas resets the
overview. This feature introduces no database migrations or monitoring integrations.

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

### Settings and workspace navigation

My settings stores account appearance, default workspace/Area, startup page and
an optional Ctrl+Alt+W or Ctrl+Alt+J workspace shortcut. Ctrl/Cmd+K also exposes
the workspace switcher and its previous-workspace action. Shortcuts ignore typing.
Saved defaults are checked against current assignments; they never grant access.
Last-page history is browser-local. Workspace switching preserves supported URLs
and their query parameters, not arbitrary in-memory filters or editor drafts.
IT-only clinic views fall back to the same clinic overview; unavailable clinics
fall back to the scoped clinic list. Edited form fields trigger a discard warning.

Global settings groups AI/integrations, quote pricing, templates, application
defaults and change history. Shared settings, price-book and template writes
require confirmation. History records actor, time, method and resource path,
never submitted values or secrets. It is not a general-purpose application audit.
The saved AI connection test checks authentication only, not generation, model
availability or billing; it sends no clinic data. Role assignment forms summarize
effective access before saving, including unrestricted administrator access.

Verification: 87 Python tests and 27 JavaScript tests pass. Local synthetic-data
browser checks cover personal/global settings, price-book visibility and staying
on the same clinic when switching from IT to Manager. No live AI key was tested.

Deferred: custom permission editors, MFA, email invitations/reset delivery, client
portals, territory polygons, multi-Area clinic ownership and cross-Area VPN disclosure.
