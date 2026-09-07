{ config, lib }:
let
  orgMatch = builtins.match ".*[:/]([^/]+)/[{][}].*" config.customRepoPattern;
  repoOrg = if orgMatch == null then "my-org" else builtins.head orgMatch;
in ''
# Project context

## Project Overview

${config.projectName} — Odoo ${config.odooVersion} development environment powered by Nix flakes.

Module prefix: `${config.modulePrefix}`. Ticket prefix: `${config.ticketPrefix}`.

## Environment

- **Python**: ${config.python} (managed by Nix, no virtualenv/pip — use `uv` for dependency management)
- **Database**: PostgreSQL ${toString config.postgres} — `${config.dbName}` on `localhost:${toString config.ports.pg}`, user/pass `${config.dbUser}/${"<runtime password from .env or dbPasswordFile>"}`
- **Odoo HTTP**: `localhost:${toString config.ports.http}`, gevent `localhost:${toString config.ports.gevent}`, nginx proxy `localhost:${toString config.ports.nginx}`
- **Odoo credentials**: `admin` / `admin`
- **Config**: `odoo.conf` (generated) | **Logs**: `odoo.log` (rotated daily)

## Key Commands

```bash
# Services
systemctl --user {start|stop|restart|status} odoo${config.serviceSuffix}.service postgres${config.serviceSuffix}.service nginx${config.serviceSuffix}.service

# Update/install module (stop running odoo first)
${config.derived.odooCmd} -c "${config.derived.claudeProjectRoot}/odoo.conf" -u module_name --workers 0 --stop-after-init --logfile=/dev/stdout

# Interactive shell
${config.derived.odooCmd} shell -c "${config.derived.claudeProjectRoot}/odoo.conf" --workers 0 --stop-after-init

# Run a specific test class/method
${config.derived.odooCmd} -c "${config.derived.claudeProjectRoot}/odoo.conf" -u module_name --workers 0 --test-enable --test-tags module_name.test_file_name --stop-after-init --logfile=/dev/stdout

# Clone/update repos and regenerate addon symlinks
nix run .#update-repos
```

## Architecture

```
src/
├── odoo/                  # Odoo ${config.odooVersion} CE source (read-only, branch ${config.odooVersion})
${lib.optionalString (config.customRepoName != "") ''
├── ${config.customRepoName}/   # Custom modules — this is where we develop
''}
└── ...                    # Third-party repos from addons.yaml (read-only)
```

${lib.optionalString (config.customRepoName != "") ''
- **Custom modules** live in `src/${config.customRepoName}/` (prefix `${config.modulePrefix}_*`)
''}
- **Third-party repos** are pinned in `addons.yaml`
- **Addon symlinks** are managed at `.local/share/Odoo/addons/${config.odooVersion}/` by `nix run .#update-repos`
- **Before typing `grep -r` over `src/`**: if the pattern is an identifier — method, field, model name, XML id — that is a `find-code` question, not a grep (`python3 .claude/skills/find-code/lsp.py sym|def|refs|model`). It is MRO-aware and answers over the whole tree at once, while a hand-scoped grep silently misses the repos you did not list in the command. grep stays right for plain strings: comments, log lines, data files, message text
- **Never pipe a "who uses X" search into `head`/`tail`.** *Who consumes this identifier* is only useful answered in full: a truncated list reads as "these are the call sites", so the conclusion drawn from it is wrong rather than merely partial. Output too long to read is the signal to ask `lsp.py refs`, not to cut it. Field report: `grep -rn leave_rendered ... | head -20` hid the two references that decided the answer, and the wrong conclusion reached a ticket before being caught. The find-code nudge hook flags this case even when its session budget is spent
- Never edit OCA/core code under `src/` (enforced by the guard-readonly hook)${lib.optionalString (config.customRepoName != "") '' — extend via a `${config.modulePrefix}_*` module''}
''
