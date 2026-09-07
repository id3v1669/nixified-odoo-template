{ pkgs, lib }:
name: { deps ? [ ], vars ? { } }:
pkgs.writeShellScriptBin name (
  lib.optionalString (deps != [ ]) ''
    export PATH="${lib.makeBinPath deps}:$PATH"
  ''
  + lib.concatStrings (lib.mapAttrsToList
      (varName: value: "export ${varName}=${lib.escapeShellArg (toString value)}\n")
      vars)
  + ''
      export NIXODOO_PYTHON=${pkgs.python3}/bin/python
    ''
  + builtins.readFile ./project-root.sh
  # Setup state and configured relative files belong to the selected project.
  # Explicit output directories retain their usual caller-relative semantics.
  + lib.optionalString (name == "create-systemd-service") ''
      if [ "$#" -eq 2 ] && [ "$1" = --output-dir ]; then
        case "$2" in
          /*) ;;
          *) set -- "$1" "$PWD/$2" ;;
        esac
      fi
    ''
  + lib.optionalString (builtins.elem name [
      "create-env" "update-repos" "bootstrap-deps" "create-odoo-config"
      "create-nginx-config" "create-systemd-service" "setup-postgres"
      "create-debug-venv" "setup-prod" "setup-test" "setup-dev"
      "create-aws-config" "download-backup" "setup-ssh-access" "create-vscode-settings"
    ]) ''
      cd "''${!PROJECT_DIR_VAR}" || exit 1
    ''
  + builtins.readFile (../scripts + "/${name}.sh")
)
