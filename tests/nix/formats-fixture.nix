{ fixtureName ? "default-19", overridesJson ? "{}" }:
let
  lock = builtins.fromJSON (builtins.readFile ../../flake.lock);
  pkgs = import (builtins.fetchTree lock.nodes.nixpkgs.locked) { system = builtins.currentSystem; };
  config = import ../../nix/lib/config.nix { inherit (pkgs) lib; }
    ((import (../fixtures/configs + "/${fixtureName}.nix")) // builtins.fromJSON overridesJson);
  files = import ../../nix/lib/formats.nix { inherit pkgs config; };
in pkgs.runCommand "config-fixture" { } (pkgs.lib.concatStringsSep "\n" (pkgs.lib.mapAttrsToList (path: file: ''
  mkdir -p "$out/$(dirname ${pkgs.lib.escapeShellArg path})"
  cp ${file} "$out/"${pkgs.lib.escapeShellArg path}
'') files))
