# Topology usability review — September 9, 2026

## Changes

- Removed fit-to-screen's dependency on the height of preceding controls.
- Replaced the always-expanded toolbar with search and five named tool categories.
- Tool content scrolls independently of the diagram. On narrow screens it overlays the diagram instead of consuming its height; Close tools and Escape dismiss it.
- Added expanded view with search, tools and an explicit exit control retained above the diagram.
- Shortened local trace instructions and opened its source/destination controls by default inside Trace.
- Restored a single account-menu Settings link. Personal AI keys are account-scoped, override the legacy shared key for permitted AI requests, and never appear in settings responses. Removing a personal key restores shared-configuration fallback. Existing role restrictions remain enforced.

## Task walkthrough results

These are developer-led task/heuristic checks using a synthetic local clinic, not a user study or measured novice completion times.

| Task | Route | Observed result |
| --- | --- | --- |
| Find a VM | Type in the visible search field, select the result | One match; diagram focused on the VM at 100% with an overview breadcrumb. |
| Limit to servers/VMs | Filters → Quick filter → Servers and VMs | Two of six devices remained; virtual relationship retained. |
| Trace a connection | Trace → choose destination → Trace path | Server-to-VM chain displayed with an explicit reachability disclaimer. |
| Open advanced tools | Trace, then expand local trace details | Canvas height remained 526px before and after opening/expanding on the test viewport. |
| Use more screen space | Expand diagram | Diagram filled the viewport; found and fixed header overlap with the exit button. Tools remain available while expanded. |
| Configure a personal AI key | Account-menu Settings | Settings page opened in one click with labelled key/model fields and storage/security explanation. No real key or external AI request was used for this check. |

## Remaining validation limits

- Browser walkthrough used the narrow in-app browser viewport. Desktop two-column behaviour is specified in CSS; broader device/browser coverage and real-user testing remain advisable.
- Automated tests verify account isolation, secret non-disclosure, key preservation/removal and unchanged operational permissions, alongside the existing topology suite.
- This release does not reopen the old unrestricted global settings/import/export administration page. Shared configuration remains a fallback, not a personal editable setting.
