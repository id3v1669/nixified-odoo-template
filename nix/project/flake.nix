{
  description = "Odoo project with a vendored Nix generator";
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
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
      generator = system: import ./nix/lib/project-apps.nix {
        inherit system;
        pkgs = import nixpkgs { inherit system; };
        frameworkRoot = self;
      };
      # Keep output names independent of config.nix: Nix inspects packages even
      # when selecting an app, and recovery must work with an invalid config.
      runtimeCommands = [
        "create-env" "update-repos" "bootstrap-deps" "create-odoo-config"
        "create-nginx-config" "create-systemd-service" "setup-postgres"
        "create-debug-venv" "setup-prod" "setup-test" "setup-dev"
        "create-aws-config" "download-backup" "setup-ssh-access" "create-vscode-settings"
      ];
      runtimePackage = system: name:
        (perSystem system).packages.${name} or
        ((import nixpkgs { inherit system; }).writeShellApplication {
          inherit name;
          text = ''
            echo 'Project configuration disables ${name}.' >&2
            exit 2
          '';
        });
      named = names: f: builtins.listToAttrs (map (name: { inherit name; value = f name; }) names);
      forSystems = f: builtins.listToAttrs (map (system: { name = system; value = f system; }) systems);
    in {
      packages = forSystems (system:
        named (runtimeCommands ++ [ "dev-server" "test-server" "prod-server" ])
          (runtimePackage system) // (generator system).packages);
      apps = forSystems (system: named runtimeCommands (name: {
        type = "app";
        program = "${runtimePackage system name}/bin/${name}";
      }) // (generator system).apps);
      devShells = forSystems (system: (perSystem system).devShells);
      checks = forSystems (system: (perSystem system).checks);
    };
}
