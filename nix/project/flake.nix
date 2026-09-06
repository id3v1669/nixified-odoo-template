{
  description = "Odoo project with a vendored Nix generator";
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";
    pyproject-nix.url = "github:pyproject-nix/pyproject.nix";
    pyproject-nix.inputs.nixpkgs.follows = "nixpkgs";
    uv2nix.url = "github:pyproject-nix/uv2nix";
    uv2nix.inputs.nixpkgs.follows = "nixpkgs";
    uv2nix.inputs.pyproject-nix.follows = "pyproject-nix";
    pyproject-build-systems.url = "github:pyproject-nix/build-system-pkgs";
    pyproject-build-systems.inputs.nixpkgs.follows = "nixpkgs";
    pyproject-build-systems.inputs.pyproject-nix.follows = "pyproject-nix";
  };
  outputs = inputs@{ self, nixpkgs, ... }:
    let
      systems = import ./nix/lib/systems.nix;
      config = import ./nix/lib/config.nix { lib = nixpkgs.lib; } (import ./config.nix);
      perSystem = system: import ./nix/lib/mk-odoo-project.nix {
        inherit inputs system config;
        projectRoot = self;
      };
      forSystems = f: builtins.listToAttrs (map (system: { name = system; value = f system; }) systems);
    in {
      packages = forSystems (system: (perSystem system).packages);
      apps = forSystems (system: (perSystem system).apps);
      checks = forSystems (system: (perSystem system).checks);
    };
}
