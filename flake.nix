{
  description = "Nix generator for Odoo development environments";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";
    pyproject-nix.url = "github:pyproject-nix/pyproject.nix";
    uv2nix.url = "github:pyproject-nix/uv2nix";
    pyproject-build-systems.url = "github:pyproject-nix/build-system-pkgs";
    pyproject-nix.inputs.nixpkgs.follows = "nixpkgs";
    uv2nix.inputs.nixpkgs.follows = "nixpkgs";
    pyproject-build-systems.inputs.nixpkgs.follows = "nixpkgs";
    uv2nix.inputs.pyproject-nix.follows = "pyproject-nix";
    pyproject-build-systems.inputs.pyproject-nix.follows = "pyproject-nix";
  };

  outputs = inputs@{ self, nixpkgs, ... }:
    let
      systems = import ./nix/lib/systems.nix;
      forSystems = f: builtins.listToAttrs (map (system: {
        name = system;
        value = f system;
      }) systems);
      normalizeConfig = import ./nix/lib/config.nix { lib = nixpkgs.lib; };
      fixtureNames = builtins.attrNames (builtins.readDir ./tests/fixtures/configs);
    in {
      lib = {
        inherit normalizeConfig;
        mkOdooProject = { projectRoot, config, system }: import ./nix/lib/mk-odoo-project.nix {
          inherit inputs projectRoot system;
          config = normalizeConfig config;
        };
      };
      checks = forSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          configs = map (name: normalizeConfig (import (./tests/fixtures/configs + "/${name}"))) fixtureNames;
        in {
          configuration = pkgs.runCommand "nixodoo-configuration" {
            configurations = builtins.toJSON configs;
          } ''
            printf '%s\n' "$configurations" > "$out"
          '';
          shellcheck = (self.lib.mkOdooProject {
            projectRoot = self;
            config = { projectName = "ci-scripts"; };
            inherit system;
          }).checks.shellcheck;
          bootstrap =
            let project = self.lib.mkOdooProject {
              projectRoot = self;
              config = import ./tests/fixtures/configs/full-16.nix;
              inherit system;
            }; in pkgs.linkFarm "nixodoo-bootstrap" (map (name: {
              inherit name;
              path = project.packages.${name};
            }) [ "create-env" "bootstrap-deps" "update-repos" "create-odoo-config"
              "create-nginx-config" "create-systemd-service" "setup-postgres"
              "create-aws-config" "setup-ssh-access" "create-vscode-settings" ]);
        });
      devShells = forSystems (system:
        let pkgs = import nixpkgs { inherit system; }; in {
          default = pkgs.mkShell {
            packages = [ pkgs.nix pkgs.python3 pkgs.uv pkgs.shellcheck pkgs.nixfmt-rfc-style ];
          };
        });
    };
}
