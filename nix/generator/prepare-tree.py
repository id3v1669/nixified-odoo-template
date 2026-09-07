"""Materialize declared project files and hash the installed bytes at build time."""

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tomllib

specification = json.loads(Path(sys.argv[1]).read_text())
output = Path(sys.argv[2])
tree = output / "tree"
tree.mkdir(parents=True)
files = {}
for declaration in specification.pop("files"):
    destination = tree / declaration["path"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(declaration["source"], destination)
    destination.chmod(declaration["mode"])
    files[declaration["path"]] = {
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "mode": declaration["mode"],
        "ownership": declaration["ownership"],
    }
specification["files"] = files
specification["configSourceDigest"] = files["config.nix"]["sha256"]
metadata = tomllib.loads((tree / "pyproject.toml").read_text())
specification["pythonOverrides"] = metadata.get("tool", {}).get("uv", {}).get("override-dependencies", [])
(output / "manifest.json").write_text(json.dumps(specification, indent=2, sort_keys=True) + "\n")
