{ inputs, system }:
let
  pkgs = import inputs.nixpkgs { inherit system; };
  normalize = import ./config.nix { inherit (pkgs) lib; };
  smoke = { major, python, revision, hash }:
    let
      config = normalize {
        projectName = "smoke-${major}";
        odooVersion = "${major}.0";
        inherit python;
        projectDirVar = "ODOO_PROJECT_DIR";
        useClaudeCode = false;
        serviceSuffix = "-smoke";
        backupS3Bucket = "unused-local-test";
        editor = "none";
      };
      project = import ./mk-odoo-project.nix {
        inherit inputs system config;
        projectRoot = ../../tests/fixtures/odoo-smoke + "/${major}";
      };
      source = pkgs.fetchzip {
        url = "https://github.com/odoo/odoo/archive/${revision}.tar.gz";
        inherit hash;
      };
    in pkgs.runCommand "odoo-${major}-runtime-smoke" {
      nativeBuildInputs = [ pkgs."postgresql_${toString config.postgres}" ];
      ODOO_SOURCE = source;
      ODOO_SERVER = project.packages.prod-server;
      DEV_SERVER = project.packages.dev-server;
      RESTORE_COMMAND = "${project.packages.download-backup}/bin/download-backup";
      DEBUG_COMMAND = "${project.packages.create-debug-venv}/bin/create-debug-venv";
      PROFILE_REL = config.derived.nixProfileRel;
    } ''
      ${pkgs.bash}/bin/bash ${../../tests/runtime-smoke.sh}
    '';
in {
  runtimeShellcheck = pkgs.runCommand "nixodoo-runtime-shellcheck" { } ''
    ${pkgs.shellcheck}/bin/shellcheck ${../../tests/runtime-smoke.sh}
    touch "$out"
  '';
  odoo17 = smoke {
    major = "17";
    python = "3.11";
    revision = "fc082fbfa4c70cf1bf5127cb207a9656218914f2";
    hash = "sha256-NBvje29SlEk4jkejE4gZOjoTZrcLg2OYFnCqDIJ4JK8=";
  };
  odoo18 = smoke {
    major = "18";
    python = "3.12";
    revision = "ec79381d98fd49fe8aeb4f417e3458f8d3210bb9";
    hash = "sha256-VjU88XatzBBpFrbXfcGArBAFK7pRBmpyXg5HC9AoOQA=";
  };
  odoo19 = smoke {
    major = "19";
    python = "3.14";
    revision = "1a13ceeaee12fe5cc50f287c31f217d4be2a2eaf";
    hash = "sha256-ji1pKkqoeOuR4J+xeYC/3Uc7KexOhGbw9HrPLN4eAjw=";
  };
}
