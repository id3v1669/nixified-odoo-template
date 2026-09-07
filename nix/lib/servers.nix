{ pkgs, lib, config, appPythonEnv, productionTools, odoo, odooDev, postgresql
, welcome, prodHelper, testHelper }:
let
  mkServer = { suffix, tools, wrapper, extraInstall ? "" }:
    pkgs.runCommand "${config.projectName}-${suffix}-${config.odooVersion}" {
      nativeBuildInputs = [ pkgs.makeWrapper ];
    } (''
      mkdir -p "$out/bin"
      makeWrapper ${appPythonEnv}/bin/python "$out/bin/python" \
        --prefix PATH : ${lib.makeBinPath tools}
      makeWrapper ${appPythonEnv}/bin/python3 "$out/bin/python3" \
        --prefix PATH : ${lib.makeBinPath tools}
      makeWrapper ${pkgs.awscli2}/bin/aws "$out/bin/aws"
      ln -s ${wrapper}/bin/odoo "$out/bin/odoo"
    '' + extraInstall);
  devTools = [ pkgs.ruff pkgs.uv pkgs.git pkgs.ccze pkgs.nodejs pkgs.bash pkgs.curl ];
  devExtras = ''
    makeWrapper ${pkgs.ccze}/bin/ccze "$out/bin/ccze"
    makeWrapper ${pkgs.ruff}/bin/ruff "$out/bin/ruff"
    makeWrapper ${pkgs.uv}/bin/uv "$out/bin/uv"
    makeWrapper ${pkgs.git}/bin/git "$out/bin/git"
    makeWrapper ${pkgs.nodejs}/bin/node "$out/bin/node"
    makeWrapper ${pkgs.bash}/bin/bash "$out/bin/bash"
    makeWrapper ${pkgs.curl}/bin/curl "$out/bin/curl"
    for tool in psql pg_dump pg_restore createdb dropdb; do
      makeWrapper ${postgresql}/bin/$tool "$out/bin/$tool" \
        --run ${lib.escapeShellArg "PROJECT_DIR_VAR=${lib.escapeShellArg config.projectDirVar}; source ${./project-root.sh}"} \
        --run 'nixodoo_selected_root="''${${config.projectDirVar}}"; if [ -f "$nixodoo_selected_root/.env" ]; then set -a; source "$nixodoo_selected_root/.env"; set +a; fi' \
        --run '${config.projectDirVar}="$nixodoo_selected_root"; unset nixodoo_selected_root' \
        --run 'export PGDATA="''${${config.projectDirVar}}/.postgres"' \
        --run 'export PGHOST="''${${config.projectDirVar}}/.postgres"'
    done
    ln -s ${welcome}/bin/welcome-message "$out/bin/welcome-message"
  '' + lib.optionalString (prodHelper != null) ''
    ln -s ${prodHelper}/bin/prod-server "$out/bin/prod-server"
  '' + lib.optionalString (testHelper != null) ''
    ln -s ${testHelper}/bin/test-server "$out/bin/test-server"
  '';
in {
  prod-server = mkServer { suffix = "prod-server"; tools = productionTools; wrapper = odoo; };
  test-server = mkServer { suffix = "test-server"; tools = productionTools; wrapper = odoo; };
  dev-server = mkServer {
    suffix = "dev-server";
    tools = productionTools ++ devTools;
    wrapper = odooDev;
    extraInstall = devExtras;
  };
}
