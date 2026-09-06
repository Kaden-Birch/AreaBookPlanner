# Structured running services

IT users can select **+ Add running service** on physical servers and VMs. Each
record includes a name, description, IP addresses, ports, protocols, internal URL,
public URL, vendor/service website, support URL/email, and notes. IDs, device
ownership, and creation/update timestamps are maintained by the application.

Device details show clickable cards with the service name, primary address/URL,
and ports. Topology nodes show up to two clickable service names, followed by
`+N more`; selecting a service opens it directly, while selecting the device or
overflow opens device details. Host servers retain their service list when they
have child VMs. Layout spacing accommodates these lists.

Service details include dated notes, image/document uploads, and related support
ticket links. Linking a ticket records its title, URL, date, and context; removing
the link does not delete the ticket in an external support system. Service links
also appear in the clinic's technical tickets. Deleting a service removes its
associated ticket-link records. Existing role and Area restrictions apply.

Create, edit, and detail screens display:

> Do not store passwords, credentials, API keys, private keys, recovery codes, or other secrets here. Store them in the approved password manager.

## Upgrade and compatibility

Back up the application database and uploads before upgrading. Startup adds the
new columns automatically. Existing service records and public URLs are retained;
the separate vendor/service website field starts empty. Ports and protocols are
documentation fields, not routing configuration or live monitoring.

Legacy newline text, JSON arrays of names, and JSON-encoded newline strings on
servers/VMs become individual service records. Blank names are skipped and exact
duplicate names on a device are not inserted again. Successfully converted text
is cleared, making repeat startup safe. Malformed JSON and unexpected JSON shapes
are retained and shown in device details for manual review. Ordinary device edits
do not erase that text. Add the appropriate services manually after reviewing it;
this release intentionally retains the original rather than offering a destructive
clear action.
