{ frameworkRoot, configFile, provenanceJson, system, target ? "candidate" }:
let
  root = builtins.storePath frameworkRoot;
  inputs = (builtins.getFlake frameworkRoot).inputs;
  pkgs = import inputs.nixpkgs { inherit system; };
  config = import ../lib/config.nix { inherit (pkgs) lib; } (import (builtins.toPath configFile));
  python = pkgs."python${pkgs.lib.replaceStrings [ "." ] [ "" ] config.python}";
in if target == "tools" then pkgs.buildEnv {
  name = "nixodoo-dependency-tools";
  paths = [ pkgs.uv python ];
} else if target == "config" then config
else import ../lib/project-tree.nix {
  inherit pkgs config;
  frameworkRoot = root;
  configSource = builtins.path { path = configFile; name = "config.nix"; };
  provenance = builtins.fromJSON provenanceJson;
}
