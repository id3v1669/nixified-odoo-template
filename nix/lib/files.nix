{ pkgs, config, frameworkRoot, configSource }:
let
  inherit (pkgs) lib;
  readContent = import ./content.nix { inherit lib config; };
  walk = root: prefix: lib.concatMap (name:
    let
      relative = prefix + name;
      source = root + "/${relative}";
      type = (builtins.readDir (root + "/${prefix}")).${name};
    in if name == "__pycache__" || lib.hasSuffix ".pyc" name then [ ]
       else if type == "directory" then walk root (relative + "/")
       else if type == "regular" then [ { path = relative; inherit source; } ]
       else throw "Unsupported framework source: ${relative}"
  ) (builtins.attrNames (builtins.readDir (root + "/${prefix}")));
  enabled = path:
    let under = prefix: lib.hasPrefix prefix path; in
    (!(under ".claude/") || config.useClaudeCode)
    && (path != "CLAUDE.md" || config.useClaudeCode)
    && (!(under ".claude/skills/deploy/") || (config.prodSshHost != "" && config.customRepoName != ""))
    && (!(under ".claude/skills/prod-ops/") || (config.prodSshHost != "" && config.customRepoName != ""))
    && (!(under ".claude/skills/deploy-checks/") || config.customRepoName != "")
    && (!(under ".claude/skills/worktree-env/") || config.customRepoName != "")
    && (!(under ".claude/skills/pipeline/") || config.usePipeline)
    && (!(under ".claude/skills/teams-message/") || config.statusMcp == "teams")
    && (!(under ".claude/skills/my-status/") || config.statusMcp == "teams")
    && (!(under ".claude/skills/odoo-tickets/") || config.ticketsMcp == "odoo")
    && (!(lib.hasSuffix "/prod-requeue-jobs.sh" path) || config.useQueueJob);
  seed = path: builtins.elem path [ "config.nix" "CLAUDE.md" "README.md" "pyproject.toml" "src/.empty"
      ".claude/skills/estimate/references/calibration.md"
      ".claude/skills/deploy-checks/scripts/invariant_local.py" ]
    || (lib.hasPrefix ".claude/memory-template/" path && !(lib.hasPrefix ".claude/memory-template/scripts/" path));
  static = map (entry:
    let path = lib.removeSuffix ".nix" entry.path;
        output = if lib.hasSuffix ".md.nix" entry.path then path else entry.path;
    in {
      path = output;
      source = if lib.hasSuffix ".md.nix" entry.path
        then pkgs.writeText (builtins.baseNameOf output) (readContent entry.source)
        else entry.source;
      mode = if lib.hasSuffix ".sh" output || lib.hasSuffix ".py" output then 493 else 420;
      ownership = if seed output then "seed" else "managed";
    }
  ) (builtins.filter (entry: enabled (lib.removeSuffix ".nix" entry.path)) (walk (frameworkRoot + "/nix/project") ""));
  vendored = map (entry: entry // {
    path = "nix/${entry.path}";
    mode = if lib.hasSuffix ".sh" entry.path || lib.hasSuffix ".py" entry.path then 493 else 420;
    ownership = "managed";
  }) (walk (frameworkRoot + "/nix") "");
  formats = lib.mapAttrsToList (path: source: {
    inherit path source;
    mode = 420;
    ownership = if seed path then "seed" else "managed";
  }) (import ./formats.nix { inherit pkgs config; });
in static ++ vendored ++ formats ++ [
  { path = "config.nix"; source = configSource; mode = 420; ownership = "seed"; }
  { path = "flake.lock"; source = frameworkRoot + "/flake.lock"; mode = 420; ownership = "managed"; }
]
