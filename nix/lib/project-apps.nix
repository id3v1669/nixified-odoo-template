{ pkgs, frameworkRoot, system }:
let
  python = pkgs.python3.withPackages (p: [ p.tomlkit p.pyyaml p.packaging ]);
  provenance = if frameworkRoot ? rev then {
    kind = "git";
    revision = frameworkRoot.rev;
    narHash = frameworkRoot.narHash;
  } else {
    kind = "local";
    narHash = frameworkRoot.narHash;
  };
  commands = [ "init" "update" "refresh-config" "refresh-deps" "recover" "migrate" ];
  packages = builtins.listToAttrs (map (name: {
    inherit name;
    value = pkgs.writeShellApplication {
      inherit name;
      runtimeInputs = [ pkgs.nix pkgs.git pkgs.coreutils ];
      text = ''
        export NIXODOO_FRAMEWORK_ROOT=${pkgs.lib.escapeShellArg (toString frameworkRoot)}
        export NIXODOO_SYSTEM=${pkgs.lib.escapeShellArg system}
        export NIXODOO_PROVENANCE=${pkgs.lib.escapeShellArg (builtins.toJSON provenance)}
        exec ${python}/bin/python ${../generator}/cli.py ${name} "$@"
      '';
    };
  }) commands);
in {
  inherit packages;
  apps = builtins.mapAttrs (name: package: {
    type = "app";
    program = "${package}/bin/${name}";
  }) packages;
}
