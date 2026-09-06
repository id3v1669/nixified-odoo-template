{ config, lib }:
let
  orgMatch = builtins.match ".*[:/]([^/]+)/[{][}].*" config.customRepoPattern;
  repoOrg = if orgMatch == null then "my-org" else builtins.head orgMatch;
in ''
---
name: user_identity
description: Machine identity for automations — whose name this setup acts under in Teams and Odoo (fill on bootstrap; placeholders disable the integrations)
metadata:
  node_type: memory
  type: user
---
# User identity (automation)

Stable, machine-parseable identity used by the automations${lib.optionalString (config.statusMcp == "teams") '' (`/my-status`)''}${lib.optionalString (config.ticketsMcp == "odoo") '' (the
state↔Odoo ticket sync and the standup Odoo section)''}. Keep the `**Key:**`
labels exactly as-is — scripts grep them. While placeholders remain, the
integrations stay silently disabled${lib.optionalString (config.ticketsMcp == "odoo") '' (the standup checks for `<ODOO LOGIN>`)''}.

- **Full name:** `<FULL NAME>`
${lib.optionalString (config.ticketsMcp == "odoo") ''
- **Odoo login (prod):** `<ODOO LOGIN>`
- **Odoo prod uid:** `<UID>` (cache only — always re-resolve by login if anything mismatches)
- **Odoo prod partner id:** `<PARTNER ID>` — the author for chatter notes posted
  by the tooling (resolve via `res.users read [uid] ["partner_id"]`)
- **Default project (prod):** `<PROJECT NAME>` — project.project id `<ID>`
- **"Current ticket" stage:** `<STAGE NAME, e.g. Development>`
''}
${lib.optionalString (config.statusMcp == "teams") ''
- **Teams status chat:** `<CHAT TOPIC, e.g. IT team>` — chatId `<CHAT ID>`
  (resolve by topic via `mcp__teams__list_chats`)
- **Teams auth must be:** `<FULL NAME>` (`<EMAIL>`) — check `mcp__teams__auth_status`
''}

${lib.optionalString (config.ticketsMcp == "odoo") ''
Optionally add the project's stage map here once known (names + ids, which
ones are fold/closed, any stage-move constraints — e.g. a `pr_uri` required
before the done stage).
''}

Related: [[user_role]], [[conventions_behavior_protocol]] (State ↔ Odoo
tickets section).
''
