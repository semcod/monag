"""Read-only workspace observations for Wellmanifest adoption metadata."""
from __future__ import annotations

import json
from pathlib import Path


_SKIP_DIRS = {'.git', '.worktrees', '.venv', 'node_modules', '__pycache__'}


def _read_object(path: Path):
    try:
        if path.is_symlink():
            return None, f'{path}: symlink metadata is not allowed'
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, f'{path}: {type(exc).__name__}: {exc}'
    if not isinstance(value, dict):
        return None, f'{path}: expected a JSON object'
    return value, None


def _repositories(root: Path, depth: int, errors=None):
    """Find checkout roots, excluding linked-worktree implementation copies."""
    root = Path(root)
    if isinstance(depth, bool) or not isinstance(depth, int) or depth < 0:
        raise ValueError('depth must be a non-negative integer')
    found, pending = [], [(root, 0)]
    while pending:
        candidate, level = pending.pop()
        try:
            if candidate.is_symlink():
                continue
            if (candidate / '.git').exists():
                found.append(candidate)
            if level < depth:
                children = sorted(candidate.iterdir())
                pending.extend((child, level + 1) for child in children
                               if child.name not in _SKIP_DIRS
                               and not child.is_symlink() and child.is_dir())
        except OSError as exc:
            if errors is not None:
                errors.append(f'{candidate}: {type(exc).__name__}: {exc}')
    return sorted(found)


def _standards(adoption, lock, errors=None, source='manifest'):
    errors = errors if errors is not None else []
    standards = []
    items = adoption.get('adoptions', []) if isinstance(adoption, dict) else []
    if not isinstance(items, list):
        errors.append(f'{source}: adoptions must be an array')
        items = []
    for index, item in enumerate(items):
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id'].strip():
            errors.append(f'{source}: adoptions[{index}] requires a non-empty string id')
            continue
        if any(item.get(key) is not None and not isinstance(item[key], str)
               for key in ('version', 'revision', 'level', 'model')):
            errors.append(f'{source}: adoptions[{index}] metadata must be strings or null')
            continue
        standards.append({**{key: item.get(key) for key in ('id', 'version', 'revision', 'level', 'model')},
                          'source': 'adoption'})
    standard = lock.get('standard') if isinstance(lock, dict) else None
    if isinstance(lock, dict) and (not isinstance(standard, dict)
            or not isinstance(standard.get('id'), str) or not standard['id'].strip()
            or any(standard.get(key) is not None and not isinstance(standard[key], str)
                   for key in ('version', 'sourceRevision'))):
        errors.append(f'{source}: lock standard requires a string id and string metadata')
    elif isinstance(standard, dict):
        lock_pack = {
            'id': standard['id'], 'version': standard.get('version'),
            'revision': standard.get('sourceRevision'), 'level': None, 'model': None,
            'source': 'lock',
        }
        matching = [pack for pack in standards if pack['id'] == lock_pack['id']]
        if matching and any(pack[key] is not None and lock_pack[key] is not None
                            and pack[key] != lock_pack[key]
                            for pack in matching for key in ('version', 'revision')):
            errors.append(f"{source}: adoption/lock disagreement for {lock_pack['id']}")
        if not any(all(pack[key] == lock_pack[key] for key in ('id', 'version', 'revision'))
                   for pack in standards):
            standards.append(lock_pack)
    return sorted(standards, key=lambda item: item['id'])


def scan(root, depth=2):
    """Collect local adoption declarations and compare only local immutable pins."""
    root = Path(root)
    repositories, errors, pins = [], [], {}
    for repo_root in _repositories(root, depth, errors):
        adoption_path = repo_root / '.governance' / 'standard-adoption.json'
        lock_path = repo_root / '.governance' / 'manifest.lock.json'
        adoption = lock = None
        if adoption_path.is_file():
            adoption, error = _read_object(adoption_path)
            if error:
                errors.append(error)
        if lock_path.is_file():
            lock, error = _read_object(lock_path)
            if error:
                errors.append(error)
        standards = _standards(adoption, lock, errors, str(repo_root))
        for pack in standards:
            revision = pack.get('revision')
            if isinstance(revision, str) and revision:
                pins.setdefault(pack['id'], set()).add(revision)
        try:
            relative = repo_root.relative_to(root)
            name = relative.as_posix() if relative.parts else repo_root.name
        except ValueError:
            name = repo_root.name
        repositories.append({
            'name': name, 'path': str(repo_root),
            'mode': adoption.get('mode', 'unspecified') if adoption is not None
                    else ('invalid' if adoption_path.exists() else 'missing'),
            'profile': adoption.get('profile', '—') if adoption else '—',
            'repository_role': adoption.get('repositoryRole') if adoption else None,
            'has_adoption_manifest': adoption is not None,
            'has_lock_manifest': lock is not None,
            'standards': standards,
        })
    drift = [
        {'id': pack, 'revisions': sorted(revisions)}
        for pack, revisions in sorted(pins.items()) if len(revisions) > 1
    ]
    return {
        'schema': 'monag.governance-observation/v1', 'root': str(root),
        'repository_count': len(repositories),
        'adoption_manifest_count': sum(repo['has_adoption_manifest'] for repo in repositories),
        'repositories': repositories, 'drift': drift, 'errors': errors,
        'freshness': 'unobserved: local scan compares only declared workspace pins',
    }
