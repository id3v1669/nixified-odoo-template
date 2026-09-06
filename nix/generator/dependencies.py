"""Reconcile generated Python metadata with an editable pyproject.toml."""

import os
from pathlib import Path
import stat
import tempfile
import tomllib

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
import tomlkit


class MetadataConflict(ValueError):
    """A user override conflicts with a framework dependency."""


def requirement_name(value):
    return canonicalize_name(Requirement(value).name)


def validate(text):
    data = tomllib.loads(text)
    project = data.get("project", {})
    for field in ("name", "version", "description", "requires-python"):
        if not isinstance(project.get(field), str):
            raise ValueError(f"project.{field} must be a string")
    SpecifierSet(project["requires-python"])
    for value in project.get("dependencies", []):
        Requirement(value)
    for value in data.get("tool", {}).get("uv", {}).get("override-dependencies", []):
        Requirement(value)
    return data


def plan_metadata(current, generated, *, previous_overrides=()):
    """Return proposed TOML; reject conflicts before the caller writes anything."""
    validate(current)
    desired = validate(generated)
    document = tomlkit.parse(current)
    project = document["project"]
    for field in ("name", "version", "description", "requires-python"):
        project[field] = desired["project"][field]
    dependencies = project.setdefault("dependencies", tomlkit.array())
    names = {requirement_name(value) for value in dependencies}
    for value in desired["project"].get("dependencies", []):
        if requirement_name(value) not in names:
            dependencies.append(value)
            names.add(requirement_name(value))
    wanted = desired.get("tool", {}).get("uv", {}).get("override-dependencies", [])
    managed_names = {requirement_name(value) for value in [*wanted, *previous_overrides]}
    existing = document.get("tool", {}).get("uv", {}).get("override-dependencies", [])
    kept = []
    for value in existing:
        if requirement_name(value) in managed_names:
            if value not in previous_overrides and value not in wanted:
                raise MetadataConflict(f"User override conflicts with framework metadata: {requirement_name(value)}")
        else:
            kept.append(value)
    reconciled = kept + list(wanted)
    if list(existing) != reconciled:
        uv = document.setdefault("tool", tomlkit.table()).setdefault("uv", tomlkit.table())
        uv["override-dependencies"] = reconciled
    result = tomlkit.dumps(document)
    validate(result)
    return result


def refresh_metadata(path, generated, *, previous_overrides=(), check=False):
    """Validate first, then replace one metadata file on its own filesystem."""
    path = Path(path)
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("pyproject.toml must be a regular file")
    original = path.read_text()
    proposed = plan_metadata(original, generated, previous_overrides=previous_overrides)
    changed = original != proposed
    if changed and not check:
        descriptor, temporary = tempfile.mkstemp(prefix=".pyproject-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w") as output:
                output.write(proposed)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return changed
