{ lib }:
overrides:
let
  evaluated = lib.evalModules {
    modules = [ ./options.nix { config = overrides; } ];
  };
  failed = builtins.filter (check: !check.assertion) evaluated.config.assertions;
  config = builtins.removeAttrs evaluated.config [ "assertions" ];
in
if failed != [ ] then
  throw ("Invalid project configuration:\n" + lib.concatMapStringsSep "\n"
    (check: "  ${check.message}") failed)
else builtins.deepSeq config config
