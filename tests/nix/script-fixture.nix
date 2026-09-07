{ name, overridesJson ? "{}", dev ? false }:
let
  lock = builtins.fromJSON (builtins.readFile ../../flake.lock);
  nixpkgs = builtins.fetchTree lock.nodes.nixpkgs.locked;
  pkgs = import nixpkgs { system = builtins.currentSystem; };
  lib = pkgs.lib;
  config = import ../../nix/lib/config.nix { inherit lib; }
    ({ projectName = "test-project"; } // builtins.fromJSON overridesJson);
  mkScript = import ../../nix/lib/mk-script.nix { inherit pkgs lib; };
in
mkScript name {
  deps = [ pkgs.coreutils pkgs.gnugrep pkgs.gnused ];
  vars = (import ../../nix/lib/script-env.nix config) // {
    ODOO_PYTHON = "${pkgs.python3}/bin/python";
    ODOO_DEV_FLAGS = if dev then "--dev=reload,qweb,werkzeug,xml" else "";
    NIXODOO_CONFIG_DIGEST = "test-digest";
    NIXODOO_CHECK_CONFIG = "${../../nix/generator/check-config.py}";
    PROJECT_PYTHON = "${pkgs.python3}/bin/python";
    NGINX_BIN = "/test/bin/nginx";
    LOGROTATE_BIN = "/test/bin/logrotate";
  };
}
