# Background integration synchronization

## Enable and use

Open **Global settings → AI & integrations → Automatic integration sync** as an administrator. It starts **disabled** on upgrade: enable it after reviewing your linked clinics. Existing Syncro customer links and UniFi site mappings become persistent jobs automatically. New reviewed imports register jobs as well.

Each linked site defaults to a roughly **30-minute** interval; admins can select 15–1440 minutes, pause/resume individual sites, pause globally, or queue **Sync now**. Global enable spreads the first runs across an interval, and later runs have a small jitter. Sync now uses the same queue and requires the site and global scheduler to be enabled. Refresh status shows queued/delayed, running, paused, retry/error, last successful refresh and next attempt. Status refresh is manual; it does not itself call the upstream API.

On a clinic's page, IT users can open **Integration freshness → Changes to review**. Administrators can open the existing reviewed import workflows or mark an observation reviewed. Acknowledgement does not apply, delete or rewire anything. Invoice observations are administrator-only here and remain excluded from IT's review feed.

## What updates automatically

Existing source snapshots refresh for successfully read categories. For source-owned local fields, compare-and-set ownership tracks the last written value and preserves a different local value as a sticky manual override. One source owns each local field; a second provider cannot overwrite that ownership.

The initial conservative ownership check requires an imported device/interface source note and a local value equal to the prior source snapshot. Eligible local changes are OS, model, manufacturer, an existing single IPv4/IPv6 address per family on a uniquely MAC-matched interface, its prefix, the corresponding primary device IP, and imported clinic-ticket status. VLAN subnet conflicts block automatic address changes. Fields without sufficiently clear ownership remain local documentation; conflicting/unsupported address changes appear for review. Existing MAC identities, names, device types, services, notes, VLAN definitions/memberships and wiring are not overwritten.

New machines/adapters, new tickets or invoices, changed uplinks/port observations/network definitions and records no longer reported become deduplicated review observations. New source records are **not** automatically created in the topology. Missing records are **not** deleted or marked offline: UniFi's connected-client inventory in particular is not a complete inventory of offline equipment. After an item is imported normally its “new record” notice resolves on the next successful refresh. A previously missing item returning resolves its missing notice.

Automated imports retain Syncro's private-IPv4/APIPA filtering and IPv6 support. No writes are sent to either provider. Source snapshots and last-success timestamps are preserved on inventory failure. Optional category failures are warnings; their previous snapshots remain intact. A successful job can therefore have warnings for unavailable optional categories.

## Queue and rate-limit behavior

The application starts one lightweight worker per provider. SQLite job leases serialize that provider's automatic jobs across application processes sharing the database; an abandoned lease expires after 15 minutes. There is no catch-up storm after restart. Clinic intervals are targets, not guarantees: high inventory counts or provider limits can lengthen the queue.

All actual Syncro/UniFi reads, including interactive preview/import reads, share persistent per-provider request pacing (at least 0.7 seconds between reserved request starts). Rate-limit state lives beside the application database in `<database>.rate.sqlite3`, contains no credentials, and coordinates processes using the same volume. HTTP 429 responses honor numeric or HTTP-date `Retry-After` values across subsequent requests. Failed jobs use exponential backoff with jitter; manual Sync now cannot bypass provider cooldown. Deployments using separate copies of the database do not coordinate their quotas.

Collection uses bounded existing read-only clients. Syncro asset detail collection has a 240-second budget checked between calls; UniFi uses its 90-second client budget. The overall job lease exceeds these bounds. Failed/incomplete core inventory reads are not applied as partial inventories. Key rotation, a reviewed import or mapping change during collection discards the in-flight result for a later retry. Application shutdown stops scheduling and discards collected-but-unapplied results.

SQLite updates and source snapshots commit together. Local topology changes are recorded under the background integration actor in the existing topology audit. Admin controls retain the application's role and Area boundaries. Back up the complete database volume, not only JSON exports, to preserve ownership, leases and review state.

Future providers can reuse the job schema, lease/queue controls, ownership comparisons and pacing helper; they must supply an allowlisted read-only collector and source-specific normalization/mapping rules.
