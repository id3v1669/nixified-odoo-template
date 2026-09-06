"""Build test artifacts with the repository's pinned Nix inputs."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_fixture(name, **arguments):
    command = ["nix", "build", "--no-link", "--print-out-paths", "--file",
               str(ROOT / "tests/nix" / name)]
    for key, value in arguments.items():
        command.extend(["--argstr", key, value])
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stderr)
    return Path(result.stdout.strip().splitlines()[-1])
