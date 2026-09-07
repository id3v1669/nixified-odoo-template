# Nix Odoo project generator

Generate Odoo projects from a typed `config.nix`. Nix expressions define the
project files, defaults, packages, and Linux service scripts. A small Python CLI
handles Git initialization, dependency locks, and filesystem updates.
The generator does not use Jinja, Copier, flake-utils, or flake-parts.

Projects use nixpkgs 26.05 and support Odoo 17 through 19, Python 3.11 through
3.14, and PostgreSQL 14 through 17. Version combinations still depend on
upstream Python packages. Runtime checks cover Odoo 17/Python 3.11,
Odoo 18/Python 3.12, and Odoo 19/Python 3.14.

## Create a project

You need Git and Nix with `nix-command` and `flakes` enabled. Runtime setup uses
Linux systemd user services. Run this from a checkout of this repository:

```bash
nix run .#init -- ../my-odoo-project --project-name my-odoo-project --odoo 19.0
cd ../my-odoo-project
nix run .#update-repos
nix run .#refresh-deps
nix profile add .#dev-server
nix run .#setup-dev
```

Initialization creates a Git repository, locks the initial Python metadata,
and stages generated files. It does not commit them. Review and commit those
files using Conventional Commits, for example `feat: initialize Odoo project`.
Git initialization is required because Nix uses Git's tracked files to prepare
a flake source. Keep `.env`, database files, credentials, and other runtime
state untracked.

For more settings, write a self-contained Nix attribute set and pass it with
`nix run .#init -- ../acme --config /path/to/config.nix`:

```nix
{
  projectName = "acme";
  odooVersion = "19.0";
  python = "3.14";
  postgres = 17;
  serviceSuffix = "-acme";
  ports = { http = 29069; gevent = 29072; nginx = 29080; pg = 29432; };
  dbPasswordFile = ".nixodoo/secrets/db-password";
  editor = "vscode";
  useClaudeCode = true;
  useQueueJob = true;
}
```

Create the credential file locally before runtime setup. The configuration
contains its path, never its contents. See [the option definitions](nix/lib/options.nix)
for all settings and defaults. The nine [configuration fixtures](tests/fixtures/configs)
cover editors, service suffixes, repository wiring, backup settings, and optional
Claude tooling.

## Work with a generated project

`dev-server`, `test-server`, and `prod-server` provide the Odoo interpreter and
runtime tools. Development adds repository, lint, and PostgreSQL helpers.
When `serviceSuffix` is nonempty, install with
`nix profile add --profile ~/.local/state/nix/profiles/PROJECT_NAME .#dev-server`.
Use the configured `projectName` in the profile path. Setup also prepares the
editor debugger environment and prints service activation instructions.

`setup-dev` creates runtime configuration, a local PostgreSQL cluster, and user
units. Existing `.env`, `odoo.conf`, and nginx configuration are retained;
systemd units and logrotate configuration are regenerated. Production and test setup
commands are `setup-prod` and `setup-test`; review their output before enabling
services. Optional helpers handle S3 restores, SSH, repository updates, and
isolated worktrees. Claude integration includes current project hooks, skills,
agents, navigation tools, and editable project memory.

### Optional development shell

Generated projects also provide a development shell on NixOS and other Linux
distributions with Nix. After the setup above, enter it from the project root:

```bash
nix develop
```

The shell uses the same `dev-server` package as the profile, including the
project's Python dependencies, Odoo launcher, and development tools. It sets
the configured `projectDirVar` to the current directory, so its commands still
find the project after you change into a subdirectory. Use `exit` to leave.
For a single command, run `nix develop --command python --version`.

Entering the shell does not run setup, load `.env` into the shell, install a
profile, or start services. The documented profile and setup commands remain
supported; keep the profile installed for the existing Odoo user service and
editor debugger. The shell itself works without an installed profile, but
running Odoo still requires its source checkout, runtime configuration, and a
running database. Avoid starting a second Odoo process on the service's port.

After refreshing configuration or dependencies, exit and re-enter the shell
to use the new environment. Existing projects receive the shell through
`nix run .#update`; their README is a seed and is preserved during updates.
The development shell in this generator repository is for generator maintenance.

## Configuration and updates

Run these commands inside a generated project:

| Command | Effect |
| --- | --- |
| `nix run .#refresh-config` | Apply settings from `config.nix` using the vendored generator |
| `nix run .#refresh-deps` | Import checked-out Odoo requirements and refresh `uv.lock` |
| `nix run .#update` | Update from `frameworkSource` in the current configuration |
| `nix run .#update -- --from SOURCE` | Select another framework source explicitly |
| `nix run .#recover` | Restore files after an interrupted transaction |

Add `-- --check` to an update or refresh command to preview changes. Exit status
0 means no changes, 1 means changes can be applied, and 2 means a conflict or
error. Checks may fetch/build candidates and resolve dependency metadata, but
do not apply project file changes.

Keep `config.nix` self-contained. Refresh after every edit, including formatting.
The launcher checks the configuration against the generated manifest and the
installed profile; rebuild and reinstall the profile when settings change.
Changing Python also requires `refresh-deps`. Changes to PostgreSQL versions,
ports, or runtime paths require a separate review of existing databases,
configuration, and services. A generator refresh does not migrate a database.

The manifest records the framework revision or local source hash, normalized
configuration, file hashes, modes, and ownership. Updates replace unchanged
managed files and remove obsolete unchanged managed files. Local edits to those
files cause a conflict before changes are applied. Resolve a conflict by
reviewing and saving the local change, restoring the recorded file, and moving
the customization into configuration or project-owned content as appropriate.

Seeds belong to the project: `config.nix`, this README, `CLAUDE.md`, local
invariant checks, and memory content survive updates. The dependency refresh
preserves extra Python dependencies and TOML comments while reconciling fields
owned by the generator; conflicting overrides require review. Runtime files and
`src/` checkouts are outside the inventory. An interrupted update keeps a local
journal; retain it and run `recover` before retrying.

Declare editor overrides in `editorSettings.vscode`, `.zed`, and `.odools`.
Declare repositories in `repositories.base` and `repositories.addons`, then run
`update-repos` to update their checkouts and addon links. `repositories.base`
must contain exactly one Odoo core checkout at `src/odoo`; its URL may point
to a fork. Additional base entries only clone or update checkouts. Declare
repositories whose addon modules should be linked and indexed in
`repositories.addons`.

## Credentials

An existing `.env` takes precedence because `create-env` leaves it intact. When
creating one, the password entered at the prompt overrides `dbPasswordFile`;
without either, the development default is `odoo`. Store credentials locally
with owner-only permissions. Never put a password in `config.nix`: Nix copies
configuration into its store. `.nixodoo/secrets/` is ignored by Git and excluded
from generated manifests.

## Check the generator

```bash
nix develop --command python3 -m unittest discover -s tests
nix flake check -L
```

Checks generate all nine configuration fixtures, validate structured files and
helper scripts, and build the three locked Odoo environments. Runtime checks
initialize `base` in disposable PostgreSQL clusters using separate Unix sockets,
then restore local dumps. They do not connect to existing databases or services.
The flake declares x86_64-linux and aarch64-linux outputs; evaluating an output
on another architecture is separate from building or running it.

Odoo source revisions and hashes are in [checks.nix](nix/lib/checks.nix).
The [runtime fixtures](tests/fixtures/odoo-smoke) contain committed dependency
locks. Refresh source pins and locks outside the sandboxed checks, then rerun
the runtime tests. Odoo itself may require Jinja2 as a Python dependency; the
generator does not use it.

## License

[MIT](LICENSE).
