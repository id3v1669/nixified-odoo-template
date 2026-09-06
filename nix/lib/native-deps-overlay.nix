# Overlay to add native build dependencies for Python packages
#
# Overlay args (final: prev:):
#     final - final set of packages with all overlays applied
#     prev  - set of packages before this overlay
#
# overrideAttrs arg (old:):
#     old - original attributes of the derivation being overridden
#
{ pkgs, postgresql }:
final: prev:
    let
        # Helper to add setuptools as build dependency for legacy sdist-only packages
        addSetuptoolsBuildDep = pkg: pkg.overrideAttrs (old: {
            nativeBuildInputs = (old.nativeBuildInputs or []) ++ [ final.setuptools final.wheel ];
        });

        # OpenLDAP 2.5+ merged libldap_r into libldap, but python-ldap 3.4.0
        # (pinned by Odoo <= 17) still links -lldap_r. Alias it so the linker
        # resolves; the resulting SONAME is libldap.so.2, satisfied at runtime
        # by openldap in buildInputs.
        openldapCompat = pkgs.runCommand "python-ldap-libldap_r-compat" { } ''
            mkdir -p $out/lib
            ln -s ${pkgs.openldap.out}/lib/libldap.so $out/lib/libldap_r.so
        '';

        # sitecustomize that activates setuptools' vendored distutils shim.
        # Legacy sdists (python-ldap) byte-compile at optimize level >= 1,
        # spawning a bare python subprocess that runs
        # `from distutils.util import byte_compile`; distutils is gone in
        # Python 3.12+ and the shim only auto-loads from a real site dir.
        # A sitecustomize on PYTHONPATH is imported at interpreter startup,
        # including in that inherited-env subprocess.
        distutilsShim = pkgs.writeTextDir "sitecustomize.py" ''
            try:
                import _distutils_hack
            except ImportError:
                pass
            else:
                _distutils_hack.add_shim()
        '';
    in {
        # Legacy python packages that only have sdist and need setuptools to build
        # (evaluated lazily; harmless when a package is absent from uv.lock)
        ofxparse = addSetuptoolsBuildDep prev.ofxparse;
        vobject = addSetuptoolsBuildDep prev.vobject;
        olefile = addSetuptoolsBuildDep prev.olefile;
        docopt = addSetuptoolsBuildDep prev.docopt;
        ebaysdk = addSetuptoolsBuildDep prev.ebaysdk;
        rjsmin = addSetuptoolsBuildDep prev.rjsmin;

        # psycopg2 compiles against libpq: setup.py needs pg_config on PATH
        # (a dedicated package after the nixpkgs postgresql output split)
        # plus setuptools; postgresql.lib provides libpq at link time.
        psycopg2 = prev.psycopg2.overrideAttrs (old: {
            nativeBuildInputs = (old.nativeBuildInputs or []) ++ [
                postgresql.pg_config
                final.setuptools
                final.wheel
            ];
            buildInputs = (old.buildInputs or []) ++ [
                postgresql.lib
                pkgs.openssl
            ];
        });

        # python-ldap needs native LDAP libraries
        python-ldap = prev.python-ldap.overrideAttrs (old: {
            # build time dependencies
            nativeBuildInputs = (old.nativeBuildInputs or []) ++ [
                pkgs.pkg-config
                final.setuptools
                final.wheel
            ];
            # run time dependencies
            buildInputs = (old.buildInputs or []) ++ [
                pkgs.openldap
                pkgs.openldap.dev
                pkgs.cyrus_sasl
                pkgs.cyrus_sasl.dev
            ];
            env = (old.env or {}) // {
                CFLAGS = "-I${pkgs.openldap.dev}/include -I${pkgs.cyrus_sasl.dev}/include";
                LDFLAGS = "-L${openldapCompat}/lib -L${pkgs.openldap.out}/lib -L${pkgs.cyrus_sasl.out}/lib";
                CPPFLAGS = "-I${pkgs.openldap.dev}/include -I${pkgs.cyrus_sasl.dev}/include";
            };
            # Provide distutils to the byte-compile subprocess (Python 3.12+)
            preBuild = (old.preBuild or "") + ''
                export PYTHONPATH="${distutilsShim}:$PYTHONPATH"
            '';
        });
    }
