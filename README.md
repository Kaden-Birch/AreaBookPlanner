# Area Book Planner

A self-hosted, map-first planner for keeping track of the clinics ChinookIT has visited,
wants to visit, or is currently serving. Everything runs locally in one Docker container
and is stored in a single SQLite file.

## Features

- **Map hub (defaults to Calgary)** – every clinic is a coloured pin. Place pins by
  address lookup (OpenStreetMap geocoding), by clicking the map, or by dragging a pin.
  Filter by colour and search from the sidebar; click a pin for a quick summary,
  directions, or to book an appointment.
- **Colour coding by relationship to ChinookIT**

  | Colour | Meaning |
  |--------|---------|
  | 🟢 Green | Current client |
  | 🔵 Dark blue | Interested |
  | 🩵 Very pale blue | Prospect, visited recently (last 3 months) |
  | ⚪ Grey | Prospect, visited before, but not in the last 3 months |
  | ⚪ White | Prospect, not yet visited |
  | 🔴 Red | Do not contact |
  | 🟠 Orange ring | Follow-up date has passed (any colour) |

  Green, dark blue and red are set on the clinic. Pale blue / grey / white are worked
  out automatically from logged visits (in‑person appointments that were not cancelled).
- **Clinic profiles** – address, phone, fax, email, website, clinic type, EMR system,
  current IT provider, number of providers, priority, tags, next follow-up date,
  general notes, and a dated **note log** for calls and conversations. A separate
  **displayed address** can be shown on the profile when the real address needs a unit /
  suite that would otherwise break the map lookup (the map keeps using the plain address).
- **Opening hours** – set each weekday's hours with an interactive per-day editor (with a
  "copy Monday to all" shortcut); the profile shows the week at a glance with today
  highlighted.
- **Rich notes** – notes can be attached to an appointment or task (an "attach to"
  picker in the note composer), and they link back both ways in the activity feed. Type
  **@** to mention a contact — the picker only offers this clinic's own contacts plus any
  shared across its group, so two people with the same name at different clinics stay
  distinct; mentions render as clickable chips.
- **Photos tied to notes** – attach a photo to a note and it also lands in the clinic's
  **Photos** section. Clicking a photo opens it with a link back to the appointment / task /
  note it came from, and photos added straight to the Photos section can have their own
  notes added in place.
- **Activity feed** – notes, appointments, tasks and status changes in one feed. It's
  collapsed by default (the quick-note composer stays visible); open "Show history" for the
  full timeline. Equipment/topology changes are kept out of the feed — they live in the
  Equipment section.
- **Tickets** – link support tickets (e.g. SyncroMSP) to a clinic: title, link, and a
  date/time (defaults to now, editable). Optionally point a ticket at a machine — pick one
  from the topology, or type a new name and it's added as a workstation you can refine later.
- **Contacts** – clinic managers, doctors, nurses, reception and other staff, with a
  primary-contact flag. Global contacts page plus per-clinic lists.
- **Calendar & appointments** – month and agenda views. Create appointments from the
  calendar or from a clinic profile, link them to a contact, and record planning notes
  before and outcome notes after. "Log a visit" records a drop-in visit in one click.
  Export an `.ics` feed for Outlook / Google Calendar.
- **Leads vs. the pipeline** – new clinics start as a **Lead**: on your map and in your
  book, but *not* on the pipeline board, and deliberately kept quiet so the board only
  ever shows deals you're actually working. Add as many clinics to visit as you like
  without cluttering the pipeline. Once one is genuinely **Interested**, promote it (from
  the clinic page's "Add to pipeline →" button, or by dragging it onto the board) and it
  joins the pipeline. Leads are still findable via the Clinics page stage filter.
- **Pipeline (Kanban)** – a deliberately lean board: drag clinics across Interested → In
  negotiations → Quote sent → Won / Lost. Winning a deal automatically makes the clinic a
  current client.
- **Self-clearing Won / Lost** – Won and Lost cards stay on the board until the end of the
  month they closed in, then drop off automatically so the columns stay tidy (negotiations
  and everything earlier stay put). A "Include earlier months" toggle brings them back.
- **Deal tracking** – estimated annual value, win probability (with sensible stage
  defaults), expected close date, and a weighted forecast on the dashboard.
- **Won / lost reasons** – capture why each deal closed and see the breakdown on the
  pipeline page.
- **Recurring revenue & renewals** – the **Clients** page tracks MRR / ARR, average revenue
  per client, new vs. churned clients this year, and an MRR-movement chart. Record each
  client's contract (start, end, term, auto-renew) and Area Book surfaces renewals that are
  coming up or overdue — on the Clients page and the dashboard — plus a data-hygiene list of
  clients missing an MRR or renewal date.
- **Onboarding checklist** – winning a deal auto-creates a templated set of onboarding tasks
  (welcome email, credentials, RMM, backups, security review, documentation, 30-day check-in)
  so nothing slips. The checklist and whether it runs are editable under Settings.
- **Churn tracking** – moving a Won client to Lost records the churn, drops them off the map
  as a client and stops their MRR; churned revenue this year shows on the Clients page.
  Re-winning them clears the churn.
- **Competitor / displacement intelligence** – record a prospect's current IT provider and
  when *their* contract ends. Area Book auto-sets a follow-up ahead of that date and shows a
  **displacement radar** (prospects whose contracts are ending soon) plus a "who we're up
  against" breakdown of open prospects by provider — all on the Pipeline page, with the
  hottest opportunities on the dashboard.
- **Activity timeline** – every note, appointment, task and status change for a clinic
  in one chronological feed, with filters.
- **Tasks & reminders** – "Call Sarah Friday" with due dates, priorities and a done
  checkbox; grouped by Overdue / Today / This week on the Tasks page and surfaced on
  the dashboard and clinic profiles.
- **Route planner** – tick clinics on the map, pick a start (your location, a map
  click, or the first stop), and get an optimised driving order with distances and
  times, drawn on the map and openable in Google Maps.
- **Near me** – filter clinics within a radius or a drive time of any point, optionally
  only those not visited in 3+ months. Drive times come from OpenStreetMap routing
  (OSRM) with a straight-line estimate as fallback.
- **Clustering & heat map** – pins group into colour-proportioned clusters when zoomed
  out; an optional heat layer shows clinic density (weighted by deal value).
- **Client-specific profiles** – current clients show a **shorthand code** (e.g. `COC`)
  instead of a priority, a "client since" date that can be back-dated to when they
  signed on, and no "log a visit" button. Won clients can be **dismissed from the
  pipeline board** so the Won column doesn't fill up with long-standing customers.
- **Sister locations** – add secondary sites to a clinic. They appear on the map as
  dashed pins that clearly say "secondary location of …" and link back to the main
  profile, which lists every site.
- **Groups / chains and connections** – put multi-location clinics in a group with
  contacts shared across it, and link clinics that share an owner, a building, or a
  manager who moved (referral / network links).
- **Contacts with extensions** – "Use the clinic's main line with an extension" fills
  the phone from the clinic and only asks for the extension; it stays in sync when the
  clinic's number changes.
- **Desktop notifications** – the app asks once whether it may send browser
  notifications, then reminds you when an appointment or task is starting and, if you
  choose 15 / 30 / 45 / 60 minutes, ahead of time. Reminders fire while a tab is open
  and need a secure page (`localhost` or https).
- **Quick-log buttons** – one tap adds a dated note ("Left a business card", "Spoke to
  the clinic manager", "Not interested right now"…), from the profile or a map pin.
- **Email templates** – pick a template on a contact to open a prefilled email in your
  mail app (placeholders for names, clinic, shorthand, your name); the email is logged.
- **Documents & photos** – attach proposals, contracts, storefront or business-card
  photos to a clinic (phones can shoot straight into it). Stored on disk next to the
  database, up to 25 MB each.
- **Global search** – `⌘K` / `Ctrl+K` (or `/`) searches clinics, shorthand codes,
  contacts, locations, tasks and notes.
- **Saved map views** – save a filter combination ("NW prospects due for a visit") and
  reopen it from the map or Settings.
- **Duplicate detection** – warns while you type if a similar clinic name or the same
  address already exists; CSV import skips likely duplicates.
- **CSV import & bulk geocoding** – load a prospect list from a spreadsheet with
  column matching and a preview, then geocode every unmapped clinic in one go.
- **Analytics** – visits per week and month, deals won vs lost, new clinics per month,
  conversion rate, average time in each stage, and activity by rep (set your name under
  Settings).
- **Call sheet** – print (or save as PDF) a day's stops with addresses, phone numbers,
  contacts, recent notes and space to scribble: from the route planner, a calendar
  day, or the filtered clinics list.
- **Business card scanner** – snap a card and a contact form is prefilled (name, title,
  phone/extension, mobile, email) and matched to a clinic. Uses OpenAI vision; enter
  your API key under Settings → AI. The card image is attached to the clinic.
- **Equipment inventory** – per clinic: firewalls, routers, switches, access points,
  servers, workstations, laptops, wireless devices, VoIP phones, printers, patch
  panels, shelves, network video recorders, security cameras and other security
  devices, and more.
  Names follow `{SHORTHAND}-{PREFIX}{NNN}` (COC-W005, COC-S001, COC-FW001…) with the
  next number suggested automatically, or type your own. Each device has an uplink
  (wired or wireless), IP/MAC, model and serial, OS, assigned user, status, warranty,
  notes and linked tickets (title + link). A list view groups
  by type; a topology view draws the network from the WAN down, dashed for wireless.
  Active counts per type are summarised for billing later.
- **Running services** – servers and VMs document the individual services they run as
  structured records rather than a free-text list. Each service has a name, description,
  IP address(es), ports/protocols, an internal service URL, a public/service website,
  a support portal/docs link, a support email, notes, and can carry attached photos,
  files and dated notes (with @mentions) exactly like a clinic. Services are searchable
  and there is no limit per device. On a server/VM detail they appear as clickable cards
  showing the primary address/URL and ports; in the topology, a leaf server/VM lists its
  service names inline (with a `+N more` indicator) and clicking a name opens that
  service record directly. Legacy free-text service entries are migrated automatically.
  Every service form and detail states prominently that **passwords, credentials, API
  keys, private keys, recovery codes and other secrets must never be stored here** — keep
  those in the approved password manager.
- **Multi-site clients** – a clinic is its own **Main Site**, and each secondary location
  is another site with its own address, displayed address, map pin and notes. Equipment
  belongs to a site (via the device's Site field), and the Equipment page has a **site
  switcher** (🏢 Main Site · 📍 each location · All sites, each with a live device count)
  that scopes the list, topology and rack views to the selected site — so each site gets
  its own network diagram and rack elevation. Existing clinics keep all current equipment
  on their Main Site, so nothing needs migrating. Adding equipment while a site is selected
  files it under that site automatically.
- **VPN links** – document the VPN tunnels between a client's sites and other clinics or
  external endpoints. A VPN link is **one canonical, two-sided record**: create it from a
  router or firewall on one site and it immediately appears on the other clinic too, with
  the local/remote perspective flipped. Editing or deleting the link updates both sides at
  once. Each link records a name, VPN type/vendor, status (unknown/up/down/disabled),
  terminating router/firewall at each end, and notes. Reach it from the **🔒 VPN links**
  button on the Equipment page; the list is scoped to the selected site. A prominent notice
  keeps secrets (pre-shared keys, configs, recovery codes) out — they belong in the
  password manager.
- **VPN endpoints** – a reusable directory of external endpoints (e.g. an AHS gateway) with
  a name, vendor, description, optional address/coordinates and support info. Endpoints are
  **shared** with every clinic by default, or can be marked **private** to the clinic that
  created one. A VPN link's far side can be another clinic site or one of these endpoints.
- **VPN visualisation** – VPN links appear in two places. In the **site topology**, each link
  draws as a distinct dashed indigo connection from its terminating router/firewall to a node
  for the remote clinic site or endpoint (colour-coded by status); clicking it opens the link.
  A dedicated **🔒 VPN map** view draws a focused connectivity graph for the clinic — its
  sites, their direct VPN links, and the directly-connected remote sites/endpoints. Remote
  clinic sites carry an **expand (+)** control that pulls in *their* VPN links, so you can
  deliberately build out a connected spiderweb (and collapse it again); clicking a remote site
  jumps to that site's topology, and clicking a link opens it. The full company-wide graph is
  never shown unprompted.
- **Onward access (VPN routing)** – on a site-to-site VPN link, each direction has a routing
  section answering "can this site reach sites *beyond* the far end through this VPN?" Choosing
  **Yes** reveals a checklist of the sites directly VPN-connected to the intermediate site; the
  ones you tick are recorded as explicit two-hop routes (e.g. SDI → COC → ABC). Routes are
  **directional** (SDI reaching ABC through COC does not let ABC reach SDI) and never inferred —
  onward access is always a deliberate choice. A **connectivity resolver** (`GET
  …/clinics/{id}/connectivity?site=`) answers "which sites can this site reach?", returning
  directly-linked sites/endpoints and the transit-reachable sites with their full path. A
  tunnel marked **disabled** drops out of the calculation; up/down/unknown stay as documented
  paths with their recorded status shown — the app documents intent, never live reachability.
- **Map VPN overlay** – a **🔒 VPN** toggle on the map (off by default) draws a dashed indigo
  line for each VPN link between sites with known coordinates, connecting the actual **site**
  pins (not just the primary clinic pin). Multiple tunnels between the same two sites collapse
  to one line with a count badge; a 🔒 midpoint marker opens a summary of each tunnel — name,
  status, both sites, terminating devices, and a link to each site's topology. External
  endpoints appear only if they were given a map position. The overlay respects the map's
  filters: a line whose clinic endpoint is filtered out fades and goes non-interactive, so
  hidden clinics are never exposed.
- **Virtual machines** are a first-class device type: a VM's uplink is the host server
  it runs on, and it draws as a smaller, distinct box in the topology (dotted virtual
  link). Devices can be marked **off-site** (a laptop at home, say) and appear in a
  separate "Off-site devices" section instead of the network tree. In the topology you
  can switch on **Edit connections** to draw or remove links between any two devices,
  so a device with more than one uplink can be represented accurately; the primary
  uplink still comes from the device form.
- **Server racks** – rack-mountable devices can record a room, rack name, bottom rack
  unit (U#) and height in Us. The Equipment page's **Racks** view lists racks by room
  and draws each rack to scale: devices sit at their real U positions and heights,
  empty units show, and every connection is drawn — links to other devices in the rack
  route as cables down a side rail, while links to devices outside the rack end in a
  labeled chip (naming the device and its rack). Wired, wireless and VM links are
  styled distinctly. Empty rack units are click-to-add: clicking a slot opens the
  device form with the rack, room and U# pre-filled, and a rack device can be
  dragged from one slot to another empty slot to reposition it. Shelves can be any
  height and hold loose (non-rack-form-factor) devices, which render as chips on the
  tray. The elevation puts upstream (uplink) devices on the left and downstream
  devices on the right; hovering a device highlights just its cables.
- **Quoting** – a price book under Settings (managed IT tiers priced per device or per
  user, VM / physical server / firewall / switch / AP / site management, basic and BDR
  backup, M365 backup, PrimeEMR flat or per user, hourly support rates, onboarding fee,
  plus your own custom items; blank = $0). "Generate quote" on a clinic's Equipment card
  pre-fills quantities from the topology; the rep picks the plan, toggles per-device or
  per-user pricing, sets the number of supported users, tweaks any quantity or price,
  adds discount and tax, and gets live totals. The quote document prints or saves as
  PDF, exports CSV, tracks status (sending it moves the clinic to Proposal; accepting
  offers to mark it Won), and can set the clinic's deal value. All quotes are listed
  under Quotes.
- **Billing hub** (Inventory · Orders · Invoices) – the **Billing** page ties parts and
  billing together:
  - **Inventory** – track items you stock or resell (toner, cabling, hardware, licences):
    name, SKU, category, storage location, our cost, sell price, on-hand quantity,
    supplier and a reorder level. Margin is shown per item and anything at or below its
    reorder level is flagged **Low** (with a low-stock-only filter).
  - **Orders** – when something isn't in stock, raise an order against an existing item or
    a brand-new custom one, with supplier, quantity, cost, expected date and a ticket link.
    When it arrives, **Receive** it and choose what happens: *add to inventory* (stock it,
    creating the item if it's new) or *bill it to a client* (drop a line onto a new or
    existing draft invoice).
  - **Invoices** – bill a clinic for items and work: lines pulled from inventory or typed
    as ad-hoc custom items, discount and tax, a **ticket link**, and a printable /
    PDF-able document plus CSV export. Status runs draft → sent → paid → void; marking an
    invoice sent or paid **deducts its inventory lines from stock**, and voiding restores
    them (drafts never touch stock). Invoices are created from the Billing tab or straight
    from a clinic's profile, where they're also listed.
- **Dark mode** – toggle in the top bar; remembers your choice and respects the OS
  setting by default.
- **Dashboard** – totals, forecast, pipeline summary, colour breakdown, tasks due,
  next 7 days, deals closing soon, follow-ups due, past appointments that still need
  an outcome, clinics due for a visit, and unmapped clinics.
- **Data tools** – CSV export of clinics and contacts, JSON backup and restore.

## Running with Docker

```bash
docker compose up -d --build
```

Then open <http://localhost:8080>.

Data lives in the `areabook-data` Docker volume (`/data/areabook.db` inside the
container; uploaded documents and photos go to `/data/attachments`). Set `TZ` in `docker-compose.yml` to your local timezone (default
`America/Edmonton`) so "today" and "last 3 months" line up with your clock.

Map tiles, address lookup and drive-time routing use public OpenStreetMap services
(tiles, Nominatim, OSRM), so the browser and server need internet access for those;
all clinic data stays on your machine. "My location" buttons need a secure context
(localhost or HTTPS); over plain HTTP on a LAN IP use "Click map" instead.

To stop: `docker compose down` (data is kept). To remove everything including data:
`docker compose down -v`.

## Running without Docker (development)

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

The database is created at `./data/areabook.db` (override with `DATABASE_PATH`).

Optional demo data for a first look:

```bash
python scripts/seed_demo.py            # adds a handful of Calgary clinics
python scripts/seed_demo.py --url http://localhost:8080   # against a running server
```

## Tests

```bash
pip install pytest httpx
python -m pytest tests -q
```

## API

The web UI talks to a JSON API that you can use directly; interactive docs are at
<http://localhost:8080/docs>.

| Endpoint | Purpose |
|----------|---------|
| `GET/POST /api/clinics`, `GET/PUT/DELETE /api/clinics/{id}` | Clinics (detail includes contacts, appointments, note log) |
| `PATCH /api/clinics/{id}/location` | Move a pin |
| `PATCH /api/clinics/{id}/stage` | Move along the pipeline (with won/lost reason) |
| `GET /api/clinics/{id}/timeline` | Merged activity feed |
| `GET/POST /api/tasks`, `GET/PUT/PATCH/DELETE /api/tasks/{id}` | Tasks / reminders |
| `PATCH /api/clinics/{id}/archive` | Dismiss / restore a won client on the pipeline board |
| `GET /api/clinics/duplicates?name=&address=` | Similar existing clinics |
| `…/clinics/{id}/locations`, `…/clinics/{id}/links`, `/api/groups` | Sister sites, connections, groups |
| `POST /api/clinics/{id}/quick-log` | One-tap dated note |
| `…/clinics/{id}/attachments`, `/api/attachments/{id}/file` | Documents and photos |
| `GET /api/search?q=` | Global search |
| `GET /api/call-sheet?ids=` / `?date=` | Printable day plan data |
| `POST /api/contacts/scan-card` | Business card → contact fields (OpenAI) |
| `GET/PUT /api/settings` | OpenAI key (masked on read) and model |
| `GET /api/reminders` | Upcoming appointments/tasks for browser notifications |
| `GET /api/analytics` | Analytics figures |
| `/api/views`, `/api/templates` | Saved map views, email templates |
| `POST /api/import/clinics`, `POST /api/geocode/bulk` | CSV import, bulk geocoding job |
| `…/clinics/{id}/devices`, `…/devices/next-name`, `…/clinics/{id}/topology`, `/api/devices/{id}`, `…/tickets` | Equipment inventory (`?site=main\|<id>\|all` scopes devices/topology/racks) |
| `GET …/clinics/{id}/sites`, `…/clinics/{id}/locations` | Sites (Main Site + secondary locations) |
| `…/clinics/{id}/vpn/links`, `/api/vpn/links/{id}`, `/api/vpn/map`, `…/clinics/{id}/vpn/endpoints`, `/api/vpn/endpoints/{id}` | Canonical VPN links, map overlay + reusable endpoint directory |
| `GET/PUT /api/vpn/links/{id}/transit`, `GET …/clinics/{id}/connectivity` | Onward-access routes + connectivity resolver |
| `POST …/devices/{id}/services`, `GET/PUT/DELETE /api/services/{id}` | Running services on servers/VMs |
| `GET/PUT /api/pricebook`, `GET …/clinics/{id}/quote-defaults`, `…/quotes` | Price book and quotes |
| `GET/POST/PUT/DELETE /api/inventory`, `…/inventory/{id}/adjust` | Inventory items and stock |
| `GET/POST/PUT/DELETE /api/orders`, `POST …/orders/{id}/receive` | Purchase orders and receiving |
| `GET/POST …/clinics/{id}/invoices`, `GET/PUT/DELETE /api/invoices/{id}`, `…/status`, `…/export.csv` | Client invoices |
| `POST /api/route` | Optimised driving order for a set of clinics |
| `GET /api/drivetime?lat=&lng=` | Drive time / distance from a point to every clinic |
| `GET/POST /api/clinics/{id}/notes` | Dated note log (with @mentions + appointment/task/photo context) |
| `GET /api/clinics/{id}/attachments/{aid}/notes` | Notes attached to one photo |
| `GET/POST /api/clinics/{id}/tickets`, `DELETE …/tickets/{tid}` | Linked support tickets |
| `GET/POST /api/contacts`, `GET/PUT/DELETE /api/contacts/{id}` | Contacts |
| `GET/POST /api/appointments`, `GET/PUT/PATCH/DELETE /api/appointments/{id}` | Appointments |
| `GET /api/geocode?q=` | Address lookup (Nominatim) |
| `GET /api/dashboard` | Dashboard summary |
| `GET /api/revenue` | Recurring revenue, renewals and churn |
| `GET /api/competitors` | Competitor breakdown and displacement radar |
| `GET /api/export/{clinics.csv,contacts.csv,appointments.ics,backup.json}` | Exports |
| `POST /api/import/backup?replace=true` | Restore a backup |

## Project layout

```
app/
  main.py          FastAPI app, serves API + static UI
  database.py      SQLite schema and connections
  logic.py         Colour rules and derived clinic stats
  routers/         clinics, contacts, appointments, misc (geocode/dashboard/export)
  static/          Single-page web UI (vanilla JS modules + Leaflet)
tests/             API tests (pytest)
scripts/           Demo data seeder
```
