# Odoo project

The project configuration is in `config.nix`. The `nix/` directory contains
the vendored generator and build definitions. Source checkouts live in `src/`.

## Development setup

```bash
nix run .#update-repos
nix run .#bootstrap-deps
nix profile add .#dev-server
nix run .#setup-dev
```

When `serviceSuffix` is set, install the profile with
`nix profile add --profile ~/.local/state/nix/profiles/PROJECT_NAME .#dev-server`.
Use the `projectName` from `config.nix` in place of `PROJECT_NAME`.
Production and test profiles are available as `.#prod-server` and `.#test-server`.

Setup creates `.env`, `odoo.conf`, nginx configuration, and systemd user units.
Those commands run explicitly and keep existing runtime configuration files.
Inspect the instructions they print before enabling services.

## Configuration and updates

Edit `config.nix`, then run `nix run .#refresh-config`. Use `-- --check` to
preview a refresh. Run `nix run .#refresh-deps` when changing Python metadata
or dependency requirements. Framework updates use `nix run .#update`.

The file inventory distinguishes managed files from seeds. Updates replace
unchanged managed files and report conflicts when you edit them locally.
They preserve seeds such as this README, `CLAUDE.md`, Python dependencies,
and memory state. Credentials, databases, source checkouts, and runtime
configuration remain outside the managed inventory.

Editor settings can be declared under `editorSettings.vscode`,
`editorSettings.zed`, and `editorSettings.odools`. Repository declarations
under `repositories.base` and `repositories.addons` generate `repos.yaml`
and `addons.yaml`. Run `nix run .#update-repos` to apply checkout changes.

Use Conventional Commits for project and addon changes.
