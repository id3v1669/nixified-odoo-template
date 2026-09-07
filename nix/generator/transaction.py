"""Plan managed file changes and journal writes for explicit crash recovery."""

import base64
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

MANIFEST = '.nixodoo/manifest.json'
JOURNAL = '.nixodoo/transaction'
RESERVED = ('.git', '.env', '.postgres', '.aws', '.ssh', '.venv', '.local', '.nginx',
            '.worktrees', 'backup', 'odoo.conf', 'odoo.log', '.logrotate.conf',
            '.logrotate.state', MANIFEST, JOURNAL, '.nixodoo/lock', '.nixodoo/migration-backup', '.nixodoo/secrets')


class ConflictError(Exception):
    def __init__(self, paths, reason='local files conflict with the update'):
        self.paths = sorted(set(paths))
        super().__init__(reason + ': ' + ', '.join(self.paths))


class RecoveryRequired(ConflictError):
    def __init__(self):
        super().__init__([JOURNAL], 'an interrupted update requires recovery')


@dataclass(frozen=True)
class FileOperation:
    path: str
    action: str
    previous_hash: str | None = None
    previous_mode: int | None = None


@dataclass(frozen=True)
class FileEdit:
    path: str
    data: bytes
    previous_hash: str | None
    previous_mode: int | None
    mode: int = 0o644


def validate_path(path):
    if (not isinstance(path, str) or not path or '\x00' in path or path == '.nixodoo'
            or any(part in ('', '.', '..') for part in path.split('/'))
            or any(path == item or path.startswith(item + '/') for item in RESERVED)
            or (path == 'src' or path.startswith('src/')) and path != 'src/.empty'):
        raise ValueError(f'unsafe managed path: {path!r}')
    return path


def resolve_root(root):
    """Resolve ancestor symlinks once, before an operation captures file state."""
    return Path(os.path.realpath(Path(root).absolute()))


def checked_path(root, relative):
    """Check a physical root and its children without following replacement symlinks."""
    root = Path(root).absolute()
    current = Path(root.anchor)
    parts = root.parts[1:] + Path(relative).parts
    for index, part in enumerate(parts):
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode) or (index < len(parts) - 1 and not stat.S_ISDIR(mode)):
            raise ConflictError([relative], 'unsafe file or parent')
    return current


def read_state(root, relative):
    path = checked_path(root, relative)
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(mode):
        raise ConflictError([relative], 'expected a regular file')
    data = path.read_bytes()
    return {'sha256': hashlib.sha256(data).hexdigest(), 'mode': stat.S_IMODE(mode)}


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'duplicate JSON key: {key}')
            result[key] = value
        return result
    return json.loads(path.read_text(), object_pairs_hook=unique)


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or manifest.get('schemaVersion') != 1:
        raise ValueError('unsupported manifest schema')
    if not isinstance(manifest.get('files'), dict):
        raise ValueError('manifest files must be an object')
    for path, declaration in manifest['files'].items():
        validate_path(path)
        if (not isinstance(declaration, dict)
                or not isinstance(declaration.get('sha256'), str)
                or not re.fullmatch('[0-9a-f]{64}', declaration['sha256'])
                or declaration.get('mode') not in (0o600, 0o644, 0o755)
                or declaration.get('ownership') not in ('seed', 'managed')):
            raise ValueError(f'invalid file declaration: {path}')
        parent = Path(path).parent
        while parent != Path('.'):
            if parent.as_posix() in manifest['files']:
                raise ValueError(f'file declared as a parent directory: {parent}')
            parent = parent.parent
    overrides = manifest.get('ownershipOverrides', {})
    if not isinstance(overrides, dict):
        raise ValueError('ownership overrides must be an object')
    for path, owner in overrides.items():
        validate_path(path)
        if owner != 'seed':
            raise ValueError(f'invalid ownership override: {path}')
    digest = manifest.get('configDigest')
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('invalid configuration digest')
    if not isinstance(manifest.get('provenance'), dict):
        raise ValueError('missing framework provenance')
    if not isinstance(manifest.get('config'), dict):
        raise ValueError('missing normalized configuration')
    return manifest


def load_manifest(root, relative, *, missing=False):
    state = read_state(root, relative)
    if state is None:
        if missing:
            return {'schemaVersion': 1, 'files': {}, 'ownershipOverrides': {}}
        raise ValueError(f'missing manifest: {root / relative}')
    return validate_manifest(read_json(root / relative))


def canonical_mode(actual):
    """Declare public files by the owner executable bit, as Git does."""
    if not 0 <= actual <= 0o777:
        raise ValueError(f'unsupported file mode: {actual:o}')
    return 0o755 if actual & 0o100 else 0o644


def mode_compatible(actual, declared):
    """Allow checkout permissions while retaining execution and privacy rules."""
    return (0 <= actual <= 0o777
            and bool(actual & 0o100) == bool(declared & 0o100)
            and (declared != 0o600 or actual & 0o077 == 0))


def matches(state, declaration):
    return (state is not None and declaration is not None
            and state['sha256'] == declaration['sha256']
            and mode_compatible(state['mode'], declaration['mode']))


def prepare_update(project, candidate, *, edits=()):
    return prepare_resolved_update(resolve_root(project), resolve_root(candidate), edits=edits)


def prepare_resolved_update(project, candidate, *, edits=()):
    """Plan using roots already resolved before capturing any edit expectations."""
    project, candidate = Path(project).absolute(), Path(candidate).absolute()
    pending = checked_path(project, JOURNAL)
    if pending.exists():
        raise RecoveryRequired()
    previous = load_manifest(project, MANIFEST, missing=True)
    proposed = load_manifest(candidate, 'manifest.json')
    for path, declaration in proposed['files'].items():
        actual = read_state(candidate / 'tree', path)
        # The Nix store clears write bits. Installed modes come from the declaration.
        if actual is None or actual['sha256'] != declaration['sha256'] or (
                actual['mode'] & 0o111) != (declaration['mode'] & 0o111):
            raise ValueError(f'candidate bytes or executable mode do not match: {path}')
    overrides = previous.get('ownershipOverrides', {})
    result = dict(proposed, files=dict(proposed['files']), ownershipOverrides=dict(overrides))
    operations, conflicts = [], []
    for path in sorted(previous['files'].keys() | proposed['files'].keys() | overrides.keys()):
        old, new = previous['files'].get(path), proposed['files'].get(path)
        seed = overrides.get(path) == 'seed' or (old and old['ownership'] == 'seed')
        if seed:
            declaration = old or new
            if declaration:
                result['files'][path] = dict(declaration, ownership='seed')
            continue
        try:
            actual = read_state(project, path)
        except ConflictError:
            conflicts.append(path)
            continue
        if new and new['ownership'] == 'seed' and old is None:
            if actual is None:
                operations.append(FileOperation(path, 'create'))
            continue
        if new and matches(actual, new):
            continue
        if old:
            if not matches(actual, old):
                conflicts.append(path)
                continue
            action = 'replace' if new else 'delete'
        elif actual is not None:
            conflicts.append(path)
            continue
        else:
            action = 'create'
        operations.append(FileOperation(path, action,
                                        actual['sha256'] if actual else None,
                                        actual['mode'] if actual else None))
    edited = set()
    for edit in edits:
        validate_path(edit.path)
        if edit.path in edited or edit.mode not in (0o600, 0o644, 0o755):
            raise ValueError(f'invalid explicit edit: {edit.path}')
        edited.add(edit.path)
        declaration = result['files'].get(edit.path)
        if declaration and declaration['ownership'] != 'seed':
            raise ValueError(f'explicit metadata edits require seed ownership: {edit.path}')
        actual = read_state(project, edit.path)
        expected = None if edit.previous_hash is None else {'sha256': edit.previous_hash, 'mode': edit.previous_mode}
        # This is a captured filesystem state, not a manifest declaration.
        if actual != expected or (actual is not None and actual['mode'] > 0o777):
            conflicts.append(edit.path)
            continue
        operations = [operation for operation in operations if operation.path != edit.path]
        updated = {'sha256': hashlib.sha256(edit.data).hexdigest(), 'mode': edit.mode, 'ownership': 'seed'}
        result['files'][edit.path] = updated
        if not matches(actual, updated):
            operations.append(FileOperation(edit.path, 'replace' if actual else 'create',
                                            edit.previous_hash, edit.previous_mode))
    if conflicts:
        raise ConflictError(conflicts)
    validate_manifest(result)
    return operations, result


def plan_update(project: Path, candidate: Path, *, edits=()) -> list[FileOperation]:
    return prepare_update(project, candidate, edits=edits)[0]


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write(path, data, mode, *, staging=None):
    descriptor, temporary = tempfile.mkstemp(prefix='.nixodoo-write-', dir=staging or path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def project_lock(project):
    directory = checked_path(project, '.nixodoo')
    directory.mkdir(exist_ok=True)
    lock = checked_path(project, '.nixodoo/lock')
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ConflictError(['.nixodoo/lock'], 'invalid lock file')
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ConflictError(['.nixodoo/lock'], 'another update holds the project lock') from error
        yield
    finally:
        os.close(descriptor)


def clear_journal(project):
    directory = checked_path(project, JOURNAL)
    shutil.rmtree(directory)
    sync_directory(directory.parent)


def restore(project, journal):
    """Validate the entire recovery record before restoring any original file."""
    if not isinstance(journal, dict) or journal.get('schemaVersion') != 1:
        raise ValueError('invalid recovery journal')
    originals, directories = journal['originals'], journal['directories']
    if not isinstance(originals, dict) or not isinstance(directories, list):
        raise ValueError('invalid recovery entries')
    decoded = {}
    for relative, original in originals.items():
        if relative != MANIFEST:
            validate_path(relative)
        read_state(project, relative)
        if original is None:
            decoded[relative] = None
        else:
            if (not isinstance(original, dict) or type(original.get('mode')) is not int
                    or not 0 <= original['mode'] <= 0o777):
                raise ValueError(f'invalid recovery mode: {relative}')
            decoded[relative] = (base64.b64decode(original['data'], validate=True), original['mode'])
    for relative in directories:
        if relative != 'src':
            validate_path(relative)
        checked_path(project, relative)
    for relative, original in decoded.items():
        path = checked_path(project, relative)
        if original is None:
            path.unlink(missing_ok=True)
            if path.parent.exists():
                sync_directory(path.parent)
        else:
            atomic_write(path, *original, staging=project / JOURNAL)
    for relative in sorted(directories, key=lambda path: len(Path(path).parts), reverse=True):
        directory = project / relative
        if directory.exists():
            directory.rmdir()
            sync_directory(directory.parent)
    clear_journal(project)


def recover(project: Path):
    project = resolve_root(project)
    with project_lock(project):
        directory = checked_path(project, JOURNAL)
        if not directory.exists():
            return
        record = checked_path(project, JOURNAL + '/state.json')
        if read_state(project, JOURNAL + '/state.json') is None:
            # No writes begin until the journal has been replaced and synced.
            clear_journal(project)
            return
        restore(project, read_json(record))


def apply_update(project: Path, candidate: Path, *, edits=()) -> None:
    apply_resolved_update(resolve_root(project), resolve_root(candidate), edits=edits)


def apply_resolved_update(project: Path, candidate: Path, *, edits=()) -> None:
    """Apply using fixed physical roots throughout locking, planning, and rollback."""
    project, candidate = Path(project).absolute(), Path(candidate).absolute()
    with project_lock(project):
        edits = list(edits)
        operations, manifest = prepare_resolved_update(project, candidate, edits=edits)
        edit_data = {edit.path: edit.data for edit in edits}
        edit_modes = {edit.path: edit.mode for edit in edits}
        manifest_data = (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode()
        current_manifest = project / MANIFEST
        if not operations and current_manifest.exists() and read_json(current_manifest) == manifest:
            return
        originals, directories = {}, set()
        paths = [operation.path for operation in operations] + [MANIFEST]
        for relative in paths:
            path = checked_path(project, relative)
            current = read_state(project, relative)
            if current is not None and current['mode'] > 0o777:
                raise ConflictError([relative], 'unsupported file mode')
            originals[relative] = None if current is None else {
                'data': base64.b64encode(path.read_bytes()).decode(), 'mode': current['mode']}
            parent = path.parent
            while not parent.exists():
                directories.add(parent.relative_to(project).as_posix())
                parent = parent.parent
        journal = {'schemaVersion': 1, 'originals': originals, 'directories': sorted(directories)}
        directory = checked_path(project, JOURNAL)
        directory.mkdir(mode=0o700)
        atomic_write(directory / 'state.json', (json.dumps(journal) + '\n').encode(), 0o600)
        sync_directory(directory.parent)
        try:
            for relative in sorted(directories, key=lambda path: len(Path(path).parts)):
                parent = checked_path(project, relative)
                parent.mkdir(mode=0o755)
                sync_directory(parent.parent)
            for operation in operations:
                path = checked_path(project, operation.path)
                if operation.action == 'delete':
                    path.unlink()
                    sync_directory(path.parent)
                else:
                    data = edit_data.get(operation.path)
                    if data is None:
                        data = checked_path(candidate / 'tree', operation.path).read_bytes()
                    mode = edit_modes[operation.path] if operation.path in edit_modes else manifest['files'][operation.path]['mode']
                    atomic_write(path, data, mode, staging=directory)
            atomic_write(current_manifest, manifest_data, 0o644, staging=directory)
        except BaseException:
            restore(project, journal)
            raise
        clear_journal(project)
