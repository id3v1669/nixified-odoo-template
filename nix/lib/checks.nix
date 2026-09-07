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
  odoo16 = smoke {
    major = "16";
    python = "3.10";
    revision = "6a571a38b2a99175fa08dcb82f9405256a992a6c";
    hash = "sha256-7BJMTxOCiRQ5I1X852r9w/g9OIx5mhsm9zzdds57CxY=";
  };
  odoo19 = smoke {
    major = "19";
    python = "3.14";
    revision = "1a13ceeaee12fe5cc50f287c31f217d4be2a2eaf";
    hash = "sha256-ji1pKkqoeOuR4J+xeYC/3Uc7KexOhGbw9HrPLN4eAjw=";
  };
}
