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
      if [ -n "''${PROJECT_DIR_VAR:-}" ]; then
          if [ -z "''${!PROJECT_DIR_VAR}" ]; then
              printf -v "$PROJECT_DIR_VAR" '%s' "$PWD"
          fi
          export "$PROJECT_DIR_VAR"
      fi
    ''
  + builtins.readFile (../scripts + "/${name}.sh")
)
