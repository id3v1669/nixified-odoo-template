{ fixtureName ? "default-19", overridesJson ? "{}", extraPath ? "" }:
let
  lock = builtins.fromJSON (builtins.readFile ../../flake.lock);
  pkgs = import (builtins.fetchTree lock.nodes.nixpkgs.locked) { system = builtins.currentSystem; };
  config = import ../../nix/lib/config.nix { inherit (pkgs) lib; }
    ((import (../fixtures/configs + "/${fixtureName}.nix")) // builtins.fromJSON overridesJson);
in import ../../nix/lib/project-tree.nix {
  inherit pkgs config;
  provenance = { kind = "local"; narHash = "test-source"; };
  extraFiles = pkgs.lib.optional (extraPath != "") {
    path = extraPath;
    source = pkgs.writeText "extra" "test\n";
    mode = 420;
    ownership = "managed";
  };
}
