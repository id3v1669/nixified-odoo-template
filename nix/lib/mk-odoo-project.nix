{ inputs, projectRoot, config, system }:
let
  inherit (inputs) nixpkgs uv2nix pyproject-nix pyproject-build-systems;
  pkgs = import nixpkgs { inherit system; };
  lib = pkgs.lib;
  python = pkgs."python${lib.replaceStrings [ "." ] [ "" ] config.python}";
  postgresql = pkgs."postgresql_${toString config.postgres}";
  workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = projectRoot; };
  pythonSet = (pkgs.callPackage pyproject-nix.build.packages { inherit python; }).overrideScope
    (lib.composeManyExtensions [
      pyproject-build-systems.overlays.default
      (workspace.mkPyprojectOverlay { sourcePreference = "wheel"; })
      (import ./native-deps-overlay.nix { inherit pkgs postgresql; })
    ]);
  appPythonEnv = pythonSet.mkVirtualEnv "${config.projectName}-env" workspace.deps.default;
  wrap = import ./mk-script.nix { inherit pkgs lib; };
  commonVars = import ./script-env.nix config;
  mkScript = name: { deps ? [ ], vars ? { } }: wrap name {
    deps = [ pkgs.coreutils pkgs.gnugrep pkgs.gnused pkgs.findutils pkgs.bash ] ++ deps;
    vars = commonVars // vars;
  };
  productionTools = [ appPythonEnv pkgs.wkhtmltopdf postgresql pkgs.awscli2 pkgs.sassc pkgs.nginx pkgs.yq-go ];
  mkOdoo = flags: mkScript "odoo" {
    deps = productionTools;
    vars = {
      ODOO_PYTHON = "${appPythonEnv}/bin/python";
      ODOO_DEV_FLAGS = flags;
      NIXODOO_CONFIG_DIGEST = builtins.hashString "sha256" (builtins.toJSON config);
      NIXODOO_CHECK_CONFIG = "${../generator/check-config.py}";
    };
  };
  odoo = mkOdoo "";
  odooDev = mkOdoo "--dev=reload,qweb,werkzeug,xml";
  scripts = lib.fix (commands: {
    create-env = mkScript "create-env" { };
    update-repos = mkScript "update-repos" { deps = [ pkgs.git pkgs.yq-go pkgs.openssh ]; };
    bootstrap-deps = mkScript "bootstrap-deps" { deps = [ pkgs.uv python pkgs.git ]; };
    create-odoo-config = mkScript "create-odoo-config" { };
    create-nginx-config = mkScript "create-nginx-config" { };
    create-systemd-service = mkScript "create-systemd-service" {
      deps = [ pkgs.systemd ];
      vars = {
        NGINX_BIN = "${pkgs.nginx}/bin/nginx";
        LOGROTATE_BIN = "${pkgs.logrotate}/sbin/logrotate";
      };
    };
    setup-postgres = mkScript "setup-postgres" {
      deps = [ postgresql pkgs.systemd ];
      vars.POSTGRES_BIN = "${postgresql}/bin/postgres";
    };
    create-debug-venv = mkScript "create-debug-venv" {
      vars.PROJECT_PYTHON = "${appPythonEnv}/bin/python";
    };
    setup-prod = mkScript "setup-prod" {
      deps = [ commands.create-env commands.update-repos commands.create-odoo-config
        commands.create-nginx-config commands.create-systemd-service ];
    };
    setup-test = mkScript "setup-test" {
      deps = [ commands.setup-prod ] ++ lib.optional config.derived.withBackup commands.create-aws-config;
    };
    setup-dev = mkScript "setup-dev" {
      deps = [ commands.setup-test commands.setup-postgres commands.create-debug-venv ]
        ++ lib.optional config.derived.withSsh commands.setup-ssh-access
        ++ lib.optional (config.editor == "vscode") commands.create-vscode-settings;
    };
  } // lib.optionalAttrs config.derived.withBackup {
    create-aws-config = mkScript "create-aws-config" { };
    download-backup = mkScript "download-backup" {
      deps = [ postgresql pkgs.awscli2 odoo ];
      vars.DEV_FIXUP_SQL = "${../scripts/dev-fixup.sql}";
    };
  } // lib.optionalAttrs config.derived.withSsh {
    setup-ssh-access = mkScript "setup-ssh-access" { deps = [ pkgs.openssh ]; };
  } // lib.optionalAttrs (config.editor == "vscode") {
    create-vscode-settings = mkScript "create-vscode-settings" { };
  });
  welcome = mkScript "welcome-message" {
    vars = {
      POSTGRESQL_VERSION = postgresql.version;
      PYTHON_VERSION = python.version;
      WKHTMLTOPDF_VERSION = pkgs.wkhtmltopdf.version;
      NGINX_VERSION = pkgs.nginx.version;
    };
  };
  prodHelper = if config.derived.withSsh then mkScript "prod-server" { deps = [ pkgs.openssh ]; } else null;
  testHelper = if config.derived.withSsh && config.testSshHost != ""
    then mkScript "test-server" { deps = [ pkgs.openssh ]; } else null;
  servers = import ./servers.nix {
    inherit pkgs lib config appPythonEnv productionTools odoo odooDev postgresql welcome prodHelper testHelper;
  };
  manifestPath = projectRoot + "/.nixodoo/manifest.json";
  configCurrent = !(builtins.pathExists manifestPath)
    || (builtins.fromJSON (builtins.readFile manifestPath)).configDigest
      == builtins.hashString "sha256" (builtins.toJSON config);
in rec {
  packages = scripts // lib.mapAttrs (_: server:
    if configCurrent then server else throw "Generated configuration is stale. Run nix run .#refresh-config, then nix run .#refresh-deps if Python changed."
  ) servers;
  devShells.default = pkgs.mkShell {
    packages = [ packages.dev-server ];
    shellHook = ''
      export ${config.projectDirVar}="$PWD"
    '';
  };
  apps = builtins.mapAttrs (name: script: {
    type = "app";
    program = "${script}/bin/${name}";
  }) scripts;
  checks.shellcheck = pkgs.runCommand "nixodoo-shellcheck" { } ''
    ${pkgs.shellcheck}/bin/shellcheck --severity=warning -e SC1090,SC1091 ${../scripts}/*.sh
    touch "$out"
  '';
}
