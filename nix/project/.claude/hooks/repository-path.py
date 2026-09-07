"""Classify hook paths without losing repository ownership through symlinks."""

import json
import os
from pathlib import Path
import sys


def path_views(path):
    """Keep each symlink target before following the next link in the path."""
    views = set()
    for _ in range(41):
        views.add(Path(os.path.normpath(path)))
        # Expand the first link so aliases cannot hide a later protected checkout.
        for ancestor in reversed((path, *path.parents)):
            if ancestor.is_symlink():
                target = ancestor.readlink()
                target = target if target.is_absolute() else ancestor.parent / target
                path = target / path.relative_to(ancestor)
                break
        else:
            return views
    raise OSError("Too many symbolic links in repository path")


def main():
    value = json.load(sys.stdin).get("tool_input", {}).get("file_path", "")
    if not value:
        return 0
    root = Path(os.environ["NIXODOO_ROOT"]).absolute()
    custom = os.environ["CUSTOM_REPO_NAME"]
    given = Path(value)
    given = given if given.is_absolute() else root / given
    physical = given.resolve()
    # Keep lexical ownership even when a checkout points outside the project.
    views = path_views(given) | {physical}
    roots = {Path(os.path.normpath(root)), root.resolve()}
    readonly = any(
        path.is_relative_to(base / "src")
        and not (custom and path.is_relative_to(base / "src" / custom))
        for path in views for base in roots
    )
    if sys.argv[1] == "guard":
        if readonly:
            print(f"Blocked: {value} is read-only (OCA/core). Edit the configured custom addon repository.",
                  file=sys.stderr)
            return 2
    elif (custom and not readonly and given.suffix == ".py" and physical.is_file()
          and physical.is_relative_to((root / "src" / custom).resolve())):
        print(physical)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        print(f"Cannot classify repository path: {error}", file=sys.stderr)
        sys.exit(2)
