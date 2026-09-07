{ pkgs, config }:
let
  inherit (pkgs) lib;
  json = pkgs.formats.json { };
  toml = pkgs.formats.toml { };
  yaml = pkgs.formats.yaml { };
  workspace = "\${workspaceFolder}";
  userHome = "\${userHome}";
  envHome = "\${env:HOME}";
  projectDir = config.derived.claudeProjectRoot;
  profile = "${userHome}/${config.derived.nixProfileRel}";
  vscodeProfile = "${envHome}/${config.derived.nixProfileRel}";
  editorConfig = name: defaults: lib.recursiveUpdate defaults (config.editorSettings.${name} or { });
  baseRepos = builtins.listToAttrs (map (repo: {
    name = "./${repo.path}";
    value = {
      remotes.github = repo.url;
      target = "github ${repo.branch}";
    } // lib.optionalAttrs (repo.revision != null) { inherit (repo) revision; };
  }) config.repositories.base);
  addonDocs = map (repo: {
    ENV = {
      DEFAULT_REPO_PATTERN = repo.url;
      ODOO_VERSION = repo.branch;
    };
    ${repo.name} = if repo.revision == null then repo.modules else {
      inherit (repo) modules revision;
    };
  }) config.repositories.addons;
  addonFiles = lib.imap0 (index: doc: yaml.generate "addons-${toString index}.yaml" doc)
    (if addonDocs == [ ] then [ {
      ENV = { DEFAULT_REPO_PATTERN = config.defaultRepoPattern; ODOO_VERSION = config.odooVersion; };
    } ] else addonDocs);
  pythonMinor = lib.toInt (builtins.elemAt (lib.splitString "." config.python) 1);
  legacyRuntime = lib.optional (config.derived.odooMajor == 17) "setuptools<81";
  overrides = legacyRuntime ++ lib.optional (pythonMinor >= 13)
    "markupsafe==3.0.3 ; python_full_version >= '3.13'"
    ++ lib.optional (pythonMinor >= 14)
    "gevent==26.8.0 ; python_full_version >= '3.14' and sys_platform != 'win32'";
  pythonMetadata = {
    project = {
      name = config.projectName;
      version = "${config.odooVersion}.0";
      description = "Odoo ${config.odooVersion} Development Environment";
      readme = "README.md";
      requires-python = ">=${config.python},<3.${toString (pythonMinor + 1)}";
      dependencies = [ "websocket-client" ] ++ legacyRuntime;
    };
  } // lib.optionalAttrs (overrides != [ ]) { tool.uv.override-dependencies = overrides; };
  hook = interpreter: file: {
    type = "command";
    command = "${interpreter} \"${projectDir}/.claude/${file}\"";
  };
  mcp = command: {
    type = "stdio";
    command = "bash";
    args = [ "-c" "set -a; source .env && { set +a; exec ${command}; }" ];
  };
in {
  ".nixodoo/env.sh" = pkgs.writeText "project-env.sh" (lib.concatStrings (lib.mapAttrsToList
    (name: value: "export ${name}=${lib.escapeShellArg (toString value)}\n")
    (import ./script-env.nix config)));
  "repos.yaml" = yaml.generate "repos.yaml" baseRepos;
  "addons.yaml" = pkgs.runCommand "addons.yaml" { } (
    lib.concatStringsSep "\nprintf '\\n---\\n' >> \"$out\"\n"
      (map (file: "cat ${file} >> \"$out\"") addonFiles)
  );
  "pyproject.toml" = toml.generate "pyproject.toml" pythonMetadata;
  ".nixodoo/config.json" = json.generate "project-config.json" config;
} // lib.optionalAttrs (config.useClaudeCode || config.editor == "zed") {
  "odools.toml" = toml.generate "odools.toml" (editorConfig "odools" {
    config = [ ({
      name = config.projectName;
      odoo_path = "${workspace}/src/odoo";
      python_path = "${profile}/bin/python3";
      addons_paths = map (repo: "${workspace}/src/${repo.name}") config.repositories.addons;
    } // lib.optionalAttrs (config.customRepoName != "") {
      diagnostic_filters = [ {
        codes = [ "OLS.*" ];
        paths = [ "**/${config.customRepoName}/**" ];
        path_type = "notin";
      } ];
    }) ];
  });
} // lib.optionalAttrs (config.editor == "vscode") {
  ".vscode/settings.json" = json.generate "vscode-settings.json" (editorConfig "vscode" {
    "python.defaultInterpreterPath" = "${vscodeProfile}/bin/python";
    "ty.importStrategy" = "useBundled";
    "files.exclude" = {
      "**/*.egg-info" = true;
      ".ruff_cache" = true;
      ".playwright-mcp" = true;
      result = true;
    };
  });
} // lib.optionalAttrs (config.editor == "zed") {
  ".zed/debug.json" = json.generate "zed-debug.json" [ {
    label = "Odoo: Debug Server";
    adapter = "Debugpy";
    request = "launch";
    program = "$ZED_WORKTREE_ROOT/src/odoo/odoo-bin";
    args = [ "--config=$ZED_WORKTREE_ROOT/odoo.conf" "--dev=qweb,werkzeug,xml"
      "--workers=0" "--logfile=/dev/stdout" ];
    python = "$ZED_WORKTREE_ROOT/.venv/bin/dev-python";
    cwd = "$ZED_WORKTREE_ROOT";
    redirectOutput = true;
    justMyCode = false;
    env.PYTHONUNBUFFERED = "1";
  } ];
} // lib.optionalAttrs (config.editor == "zed" && config.editorSettings ? zed) {
  ".zed/settings.json" = json.generate "zed-settings.json" config.editorSettings.zed;
} // lib.optionalAttrs config.useClaudeCode {
  ".mcp.json" = json.generate "mcp.json" {
    mcpServers = {
      odoo = mcp "uvx --from 'git+https://github.com/okolovmark/odoo-fast-mcp@cb85a99' odoo-fast-mcp";
      postgres-mcp = mcp "uvx --with 'mcp<2' postgres-mcp --access-mode=unrestricted \"$DATABASE_URI\"";
    } // lib.optionalAttrs (config.statusMcp == "teams") {
      teams = { type = "stdio"; command = "npx";
        args = [ "-y" "git+https://github.com/okolovmark/teams-mcp.git#stable" ]; };
    };
  };
  ".claude/settings.json" = json.generate "claude-settings.json" {
    hooks = {
      SessionStart = [ { hooks = [ (hook "bash" "hooks/session-env.sh") ]; } ];
      PreToolUse = [
        { matcher = "Edit|Write"; hooks = [ (hook "bash" "hooks/guard-readonly.sh") ]; }
        { matcher = "Bash"; hooks = [ (hook "bash" "hooks/guard-bash.sh") (hook "python3" "hooks/nudge-find-code.py") ]; }
        { matcher = "Grep"; hooks = [ (hook "python3" "hooks/nudge-find-code.py") ]; }
      ];
      PostToolUse = [ { matcher = "Edit|Write"; hooks = [ (hook "bash" "hooks/ruff-post-edit.sh") ]; } ];
    };
    statusLine = hook "bash" "statusline-command.sh";
  };
}
