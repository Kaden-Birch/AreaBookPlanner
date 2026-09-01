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
  general notes, and a dated **note log** for calls and conversations.
- **Contacts** – clinic managers, doctors, nurses, reception and other staff, with a
  primary-contact flag. Global contacts page plus per-clinic lists.
- **Calendar & appointments** – month and agenda views. Create appointments from the
  calendar or from a clinic profile, link them to a contact, and record planning notes
  before and outcome notes after. "Log a visit" records a drop-in visit in one click.
  Export an `.ics` feed for Outlook / Google Calendar.
- **Pipeline (Kanban)** – drag clinics across Prospect → Contacted → Demo → Proposal →
  Won / Lost. Winning a deal automatically makes the clinic a current client.
- **Deal tracking** – estimated annual value, win probability (with sensible stage
  defaults), expected close date, and a weighted forecast on the dashboard.
- **Won / lost reasons** – capture why each deal closed and see the breakdown on the
  pipeline page.
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
  servers, workstations, laptops, wireless devices, VoIP phones, printers and more.
  Names follow `{SHORTHAND}-{PREFIX}{NNN}` (COC-W005, COC-S001, COC-FW001…) with the
  next number suggested automatically, or type your own. Each device has an uplink
  (wired or wireless), IP/MAC, model and serial, OS, assigned user, status, warranty,
  notes, services (for servers) and linked tickets (title + link). A list view groups
  by type; a topology view draws the network from the WAN down, dashed for wireless.
  Active counts per type are summarised for billing later.
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
| `…/clinics/{id}/devices`, `…/devices/next-name`, `…/clinics/{id}/topology`, `/api/devices/{id}`, `…/tickets` | Equipment inventory |
| `POST /api/route` | Optimised driving order for a set of clinics |
| `GET /api/drivetime?lat=&lng=` | Drive time / distance from a point to every clinic |
| `GET/POST /api/clinics/{id}/notes` | Dated note log |
| `GET/POST /api/contacts`, `GET/PUT/DELETE /api/contacts/{id}` | Contacts |
| `GET/POST /api/appointments`, `GET/PUT/PATCH/DELETE /api/appointments/{id}` | Appointments |
| `GET /api/geocode?q=` | Address lookup (Nominatim) |
| `GET /api/dashboard` | Dashboard summary |
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
