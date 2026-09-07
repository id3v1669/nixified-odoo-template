{
  description = "Nix generator for Odoo development environments";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
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
      generator = system: import ./nix/lib/project-apps.nix {
        inherit system;
        pkgs = import nixpkgs { inherit system; };
        frameworkRoot = self;
      };
    in {
      packages = forSystems (system: (generator system).packages);
      apps = forSystems (system: (generator system).apps);
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
          projectTrees = pkgs.linkFarm "nixodoo-project-trees" (map (config: {
            name = config.projectName;
            path = import ./nix/lib/project-tree.nix {
              inherit pkgs config;
              frameworkRoot = self;
              provenance = { kind = "local"; narHash = self.narHash; };
            };
          }) configs);
          projectHelpers =
            let candidate = import ./nix/lib/project-tree.nix {
              inherit pkgs;
              config = normalizeConfig (import ./tests/fixtures/configs/full-17.nix);
              frameworkRoot = self;
              provenance = { kind = "local"; narHash = self.narHash; };
            }; in pkgs.runCommand "nixodoo-project-helpers" { } ''
              find ${candidate}/tree/.claude -name '*.sh' -print0 | \
                xargs -0 ${pkgs.shellcheck}/bin/shellcheck --severity=warning -e SC1090,SC1091
              PYTHONPYCACHEPREFIX="$TMPDIR/pycache" ${pkgs.python3}/bin/python -m compileall -q ${candidate}/tree/.claude
              ${pkgs.python3}/bin/python ${./tests/test_nudge_find_code.py} ${candidate}/tree/.claude/hooks/nudge-find-code.py
              touch "$out"
            '';
          formats = pkgs.linkFarm "nixodoo-formats" (nixpkgs.lib.concatMap (config:
            nixpkgs.lib.mapAttrsToList (name: path: {
              name = "${config.projectName}/${name}";
              inherit path;
            }) (import ./nix/lib/formats.nix { inherit pkgs config; })
          ) configs);
          shellcheck = (self.lib.mkOdooProject {
            projectRoot = self;
            config = { projectName = "ci-scripts"; };
            inherit system;
          }).checks.shellcheck;
          bootstrap =
            let project = self.lib.mkOdooProject {
              projectRoot = self;
              config = import ./tests/fixtures/configs/full-17.nix;
              inherit system;
            }; in pkgs.linkFarm "nixodoo-bootstrap" (map (name: {
              inherit name;
              path = project.packages.${name};
            }) [ "create-env" "bootstrap-deps" "update-repos" "create-odoo-config"
              "create-nginx-config" "create-systemd-service" "setup-postgres"
              "create-aws-config" "setup-ssh-access" "create-vscode-settings" ]);
        } // import ./nix/lib/checks.nix { inherit inputs system; });
      devShells = forSystems (system:
        let pkgs = import nixpkgs { inherit system; }; in {
          default = pkgs.mkShell {
            packages = [ pkgs.nix
              (pkgs.python3.withPackages (python: [ python.tomlkit python.pyyaml python.packaging ]))
              pkgs.uv pkgs.shellcheck pkgs.nixfmt-rfc-style ];
          };
        });
    };
}
