# Odoo project

The project configuration is in `config.nix`. The `nix/` directory contains
the vendored generator and build definitions. Source checkouts live in `src/`.
The generator uses nixpkgs 26.05 and supports Odoo 17–19, Python 3.11–3.14,
and PostgreSQL 14–17.

Initialization creates a Git repository and stages the generated files without
committing them. Keep runtime files such as `.env` untracked: Nix uses Git's
tracked files when preparing the project source. Git initialization is required.

## Development setup

```bash
nix run .#update-repos
nix run .#refresh-deps
nix profile add .#dev-server
nix run .#setup-dev
```

When `serviceSuffix` is nonempty, create the profile directory before installing:

```bash
mkdir -p ~/.local/state/nix/profiles
nix profile add --profile ~/.local/state/nix/profiles/PROJECT_NAME .#dev-server
```

Use the `projectName` from `config.nix` in place of `PROJECT_NAME`.
Production and test profiles are available as `.#prod-server` and `.#test-server`.

Setup creates `.env`, `odoo.conf`, nginx configuration, and systemd user units.
Those commands run explicitly. They keep existing `.env`, `odoo.conf`, and
nginx configuration, and regenerate systemd units and logrotate configuration.
Inspect the instructions they print before enabling services.

### Optional development shell

After setup, run `nix develop` from the project root to use the project's
Python dependencies, Odoo launcher, and development tools. This works on NixOS
and other Linux distributions with Nix. The shell sets the configured
`projectDirVar` to that directory, so commands still find the project after you
change into a subdirectory. Use `exit` to leave, or run a single command with
`nix develop --command python --version`.

Shell entry does not run setup, load `.env` into the shell, install a profile,
or start services. Keep using the profile and setup commands above for the
existing Odoo user service and editor debugger. The shell itself needs no
installed profile; running Odoo still needs its source checkout, runtime
configuration, and a running database. Avoid starting a second Odoo process
on the service's port.

Exit and re-enter the shell after refreshing configuration or dependencies.

## Configuration and updates

Edit `config.nix`, then run `nix run .#refresh-config`. Use `-- --check` to
preview a refresh. Run `nix run .#refresh-deps` when changing Python metadata
or dependency requirements. Framework updates use `nix run .#update`.

Keep `config.nix` self-contained. Run a configuration refresh after editing it,
including formatting changes. Existing server profiles check the configuration
before starting; rebuild and reinstall the profile when its settings change.

For `update --check` and `refresh-config --check`, exit status 0 means no
changes, 1 means changes are ready to apply, and 2 means a conflict or error.
Use `nix run .#update -- --from SOURCE` to select a framework explicitly;
otherwise updates use `frameworkSource` from the current `config.nix`.

If an update is interrupted, run `nix run .#recover` to restore its original
files before retrying. Recovery uses the local transaction journal. Keep that
journal until recovery finishes.

The file inventory distinguishes managed files from seeds. Updates replace
unchanged managed files and report conflicts when you edit them locally.
They preserve seeds such as this README, `CLAUDE.md`, Python dependencies,
and memory state. Credentials, databases, source checkouts, and runtime
configuration remain outside the managed inventory.

Editor settings can be declared under `editorSettings.vscode`,
`editorSettings.zed`, and `editorSettings.odools`. Repository declarations
under `repositories.base` and `repositories.addons` generate `repos.yaml`
and `addons.yaml`. `repositories.base` must contain exactly one Odoo core
checkout at `src/odoo`; its URL may point to a fork. Additional base entries
only clone or update checkouts. Declare repositories whose addon modules
should be linked and indexed in `repositories.addons`. Run
`nix run .#update-repos` to apply checkout changes.

Use Conventional Commits for project and addon changes.

## Credentials

Keep credentials in ignored local files. An existing `.env` remains unchanged.
When creating it, a password entered at the prompt overrides `dbPasswordFile`;
without either, the development default is `odoo`. Configuration stores only
credential paths because Nix copies `config.nix` into its store.

If a configured `dbPasswordFile` is missing or unreadable, `create-env` requires
a nonempty password at the prompt. `setup-postgres` and worktree commands fail
unless a nonempty `PGPASSWORD` is available from `.env` or the environment.
Relative password-file paths are resolved from the project root.

Odoo 16, Python 3.10, and PostgreSQL 13 are no longer supported. Projects
using those versions need a separate application, interpreter, or database migration before
updating their generator; changing the version in configuration alone does not
migrate a database.
