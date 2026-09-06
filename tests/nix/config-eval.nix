{ overridesJson ? "{}", fixture ? "" }:
let
  lock = builtins.fromJSON (builtins.readFile ../../flake.lock);
  nixpkgs = builtins.fetchTree lock.nodes.nixpkgs.locked;
  lib = import (nixpkgs + "/lib");
  overrides = if fixture == ""
    then builtins.fromJSON overridesJson
    else import (../fixtures/configs + "/${fixture}.nix");
in
import ../../nix/lib/config.nix { inherit lib; } overrides
