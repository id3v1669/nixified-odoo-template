#!/usr/bin/env python3
"""Quote configured paths and arguments for the named remote Odoo helpers."""

import argparse
import json
from pathlib import Path
import re
from shlex import quote


def remote_path(value):
    if value == "~":
        return '"$HOME"'
    if value.startswith("~/"):
        return '"$HOME"/' + quote(value[2:])
    return quote(value)


parser = argparse.ArgumentParser()
parser.add_argument("action", choices=("deploy", "shell"))
parser.add_argument("arguments", nargs=argparse.REMAINDER)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
config = json.loads((root / ".nixodoo/config.json").read_text())
project = config["prodRemoteProjectDir"]
profile = config["derived"]["nixProfileRel"]
base = (f"python {remote_path(project + '/src/odoo/odoo-bin')} "
        f"{'shell ' if args.action == 'shell' else ''}"
        f"-c {remote_path(config['prodRemoteOdooConf'])} -d {quote(config['prodDbName'])}")
lines = ["set -euo pipefail", f'export PATH="$HOME/{profile}/bin:$PATH"']
if args.action == "deploy":
    if not 2 <= len(args.arguments) <= 3:
        parser.error("deploy requires -u|-i modules [--link-addons]")
    flag, modules, *link = args.arguments
    if flag not in ("-u", "-i") or not re.fullmatch(r"[a-z0-9_]+(?:,[a-z0-9_]+)*", modules):
        parser.error("invalid module update arguments")
    if link and link != ["--link-addons"]:
        parser.error("unknown deploy option")
    lines += [f"cd {remote_path(project + '/src/' + config['customRepoName'])}",
              f"git pull origin {quote(config['odooVersion'])}"]
    if link:
        lines += [f"cd {remote_path(project)}", config["prodLinkAddonsCmd"]]
    lines += [f"{base} --workers 0 {flag} {quote(modules)} --stop-after-init --logfile=/dev/stdout",
              f"systemctl --user restart {quote(config['derived']['odooService'])}"]
else:
    if args.arguments:
        parser.error("shell takes no extra arguments")
    lines += [base + " --no-http"]
print("\n".join(lines))
