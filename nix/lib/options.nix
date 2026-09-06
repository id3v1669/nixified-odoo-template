{ config, lib, ... }:
let
  inherit (lib) mkOption types;
  option = type: default: description: mkOption { inherit type default description; };
  string = option types.str;
  boolean = option types.bool;
  major = lib.toInt (lib.removeSuffix ".0" config.odooVersion);
  prefix = builtins.head (lib.splitString "-" config.projectName);
  port = types.ints.between 1 65535;
  repoName = types.strMatching "[a-zA-Z0-9][a-zA-Z0-9_.-]*";
  revision = option (types.nullOr (types.strMatching "[a-fA-F0-9]{40}")) null
    "Full Git revision; null follows the configured branch.";
  baseRepo = types.submodule {
    options = {
      path = mkOption { type = types.strMatching "src/[a-zA-Z0-9][a-zA-Z0-9_.-]*"; };
      url = mkOption { type = types.nonEmptyStr; };
      branch = string config.odooVersion "Git branch to check out.";
      inherit revision;
    };
  };
  addonRepo = types.submodule {
    options = {
      name = mkOption { type = repoName; };
      url = mkOption { type = types.nonEmptyStr; };
      branch = string config.odooVersion "Git branch to check out.";
      modules = option (types.listOf types.nonEmptyStr) [ "*" ] "Addon modules to link.";
      inherit revision;
    };
  };
  profile = if config.serviceSuffix == "" then ".nix-profile"
    else ".local/state/nix/profiles/${config.projectName}";
in
{
  options = {
    projectName = mkOption {
      type = types.addCheck (types.strMatching "[a-z][a-z0-9-]+")
        (name: builtins.stringLength name <= 32);
      description = "Project name in lowercase kebab-case, at most 32 characters.";
    };
    odooVersion = option (types.enum [ "16.0" "17.0" "18.0" "19.0" ]) "19.0" "Odoo branch.";
    python = option (types.enum [ "3.10" "3.11" "3.12" "3.13" "3.14" ])
      (if major == 16 then "3.10" else if major == 17 then "3.11" else "3.12")
      "Python interpreter version.";
    postgres = option (types.enum [ 13 14 15 16 17 ])
      (if major <= 17 then 15 else 17) "PostgreSQL major version.";
    ports = option (types.submodule {
      options = {
        http = option port (major * 100 + 69) "Odoo HTTP port.";
        gevent = option port (major * 100 + 72) "Odoo gevent or longpolling port.";
        nginx = option port (major * 1000 + 69) "Nginx listen port.";
        pg = option port (major * 1000 + 432) "PostgreSQL port.";
      };
    }) { } "Project service ports.";
    projectDirVar = option (types.strMatching "[A-Z][A-Z0-9_]*")
      "ODOO${toString major}_PROJECT_DIR" "Environment variable containing the project root.";
    serviceSuffix = option (types.strMatching "(-?[a-z0-9][a-z0-9-]*)?") ""
      "Systemd service suffix; nonempty values select a separate project profile.";
    dbName = string "develop" "Development database name.";
    dbUser = string "odoo" "PostgreSQL role.";
    dbPasswordFile = option (types.nullOr types.str) null
      "Runtime password file; null uses the local development default.";
    editor = option (types.enum [ "none" "vscode" "zed" ]) "none" "Editor integration.";
    editorSettings = option (types.attrsOf types.anything) { } "Editor configuration overrides.";
    useQueueJob = boolean false "Enable the OCA queue_job integration.";
    useClaudeCode = boolean true "Include Claude Code tooling.";
    defaultRepoPattern = string "https://github.com/OCA/{}.git" "Default addon repository URL pattern.";
    customRepoPattern = string "" "Custom addon repository URL pattern.";
    customRepoName = string
      (if config.customRepoPattern == "" then "" else "${config.projectName}-addons")
      "Custom addon repository name.";
    modulePrefix = string (if builtins.elem prefix [ "odoo" "base" "web" ] then "custom" else prefix)
      "Prefix for custom module names.";
    ticketPrefix = string "TASK" "Ticket key prefix.";
    readmeGenSource = string "git+https://github.com/OCA/maintainer-tools@master"
      "Source of the addon README generator.";
    statusMcp = option (types.enum [ "none" "teams" ]) "none" "Team status integration.";
    ticketsMcp = option (types.enum [ "none" "odoo" ]) "none" "Ticket tracking integration.";
    odooProdUrl = string "" "Production Odoo URL for ticket tracking.";
    usePipeline = boolean (config.useClaudeCode && config.customRepoName != "")
      "Include the development pipeline skill.";
    backupS3Bucket = string "" "S3 backup bucket; empty disables backup tooling.";
    prodSshHost = string "" "Production SSH host.";
    prodSshUser = string "ubuntu" "Production SSH user.";
    prodWebUrl = string "" "Production web URL.";
    prodRemoteProjectDir = string "~/${config.projectName}" "Project checkout on the production host.";
    prodRemoteOdooConf = string "${config.prodRemoteProjectDir}/odoo.conf" "Production Odoo configuration path.";
    prodDbName = string "odoo" "Production database name.";
    prodLinkAddonsCmd = string "nix run .#update-repos" "Production addon linking command.";
    testSshHost = string "" "Test server SSH host.";
    testSshUser = string "ubuntu" "Test server SSH user.";
    testSshPort = option port 22 "Test server SSH port.";
    testLocalForward = string "" "Optional SSH LocalForward value.";
    testWebUrl = string "" "Test server web URL.";
    frameworkSource = string "github:okolovmark/nixodoo-copier-template" "Framework source for explicit updates.";
    repositories = option (types.submodule {
      options = {
        base = option (types.listOf baseRepo) [ {
          path = "src/odoo";
          url = "https://github.com/odoo/odoo.git";
        } ] "Base source checkouts.";
        addons = option (types.listOf addonRepo) (
          lib.optional config.useQueueJob {
            name = "queue";
            url = lib.replaceStrings [ "{}" ] [ "queue" ] config.defaultRepoPattern;
            modules = [ "queue_job" "queue_job_cron" ];
          }
          ++ lib.optional (config.customRepoName != "") {
            name = config.customRepoName;
            url = lib.replaceStrings [ "{}" ] [ config.customRepoName ] config.customRepoPattern;
          }
        ) "Addon source checkouts; explicit lists replace the defaults.";
      };
    }) { } "Source repository declarations.";
    derived = mkOption {
      type = types.attrsOf types.anything;
      readOnly = true;
      internal = true;
      description = "Values computed from project choices.";
    };
    assertions = mkOption { type = types.listOf types.attrs; internal = true; default = [ ]; };
  };

  config = {
    derived = {
      odooMajor = major;
      nixProfileRel = profile;
      nixProfileFlag = if config.serviceSuffix == "" then "" else "--profile ~/${profile} ";
      odooCmd = if config.serviceSuffix == "" then "odoo" else "~/${profile}/bin/odoo";
      odooService = "odoo${config.serviceSuffix}.service";
      withBackup = config.backupS3Bucket != "";
      withSsh = config.prodSshHost != "";
    };
    assertions = [
      {
        assertion = !config.useClaudeCode || builtins.match "[a-z][a-z0-9_]+" config.modulePrefix != null;
        message = "modulePrefix must be lowercase snake_case when useClaudeCode is enabled.";
      }
      {
        assertion = config.customRepoName == "" || config.customRepoPattern != "";
        message = "customRepoName requires customRepoPattern.";
      }
      {
        assertion = config.useClaudeCode || (config.statusMcp == "none" && config.ticketsMcp == "none");
        message = "statusMcp and ticketsMcp require useClaudeCode.";
      }
      {
        assertion = !config.usePipeline || (config.useClaudeCode && config.customRepoName != "");
        message = "usePipeline requires useClaudeCode and a customRepoName.";
      }
      {
        assertion = config.testSshHost == "" || config.prodSshHost != "";
        message = "testSshHost requires prodSshHost.";
      }
      {
        assertion = lib.length (lib.unique (map (repo: repo.name) config.repositories.addons))
          == lib.length config.repositories.addons;
        message = "repositories.addons must have unique names.";
      }
    ];
  };
}
