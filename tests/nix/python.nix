let
  lock = builtins.fromJSON (builtins.readFile ../../flake.lock);
  pkgs = import (builtins.fetchTree lock.nodes.nixpkgs.locked) { system = builtins.currentSystem; };
in pkgs.python3.withPackages (python: [ python.tomlkit python.pyyaml python.packaging ])
