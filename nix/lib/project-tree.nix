{ pkgs, config, provenance, frameworkRoot ? ../..
, configSource ? pkgs.writeText "config.nix" (pkgs.lib.generators.toPretty { } (removeAttrs config [ "derived" ]))
, extraFiles ? [ ] }:
let
  inherit (pkgs) lib;
  files = (import ./files.nix { inherit pkgs config frameworkRoot configSource; }) ++ extraFiles;
  paths = map (file: file.path) files;
  runtimePaths = [ ".git" ".env" ".postgres" ".aws" ".ssh" ".venv" ".local" ".nginx" ".worktrees"
    "backup" "odoo.conf" "odoo.log" ".logrotate.conf" ".logrotate.state" ".nixodoo/manifest.json"
    ".nixodoo/transaction" ".nixodoo/lock" ];
  safe = path: path != "" && !(lib.hasPrefix "/" path)
    && builtins.all (part: part != ".." && part != "." && part != "") (lib.splitString "/" path)
    && builtins.all (reserved: path != reserved && !(lib.hasPrefix "${reserved}/" path)) runtimePaths
    && (!(lib.hasPrefix "src/" path) || path == "src/.empty");
  checked = if lib.length (lib.unique paths) != lib.length paths then throw "Duplicate project output path"
    else if !builtins.all safe paths then throw "Unsafe project output path"
    else if !builtins.all (file: builtins.elem file.mode [ 420 493 ] && builtins.elem file.ownership [ "seed" "managed" ]) files
    then throw "Invalid project file mode or ownership"
    else files;
  specification = pkgs.writeText "project-files.json" (builtins.toJSON {
    schemaVersion = 1;
    inherit provenance config;
    configDigest = builtins.hashString "sha256" (builtins.toJSON config);
    files = map (file: file // { source = "${file.source}"; }) checked;
  });
in pkgs.runCommand "${config.projectName}-candidate" { } ''
  ${pkgs.python3}/bin/python ${../generator/prepare-tree.py} ${specification} "$out"
''
