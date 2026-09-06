{ lib, config }:
source:
if lib.hasSuffix ".md.nix" (toString source)
then import source { inherit lib config; }
else builtins.readFile source
