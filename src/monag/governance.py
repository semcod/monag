"""Read-only workspace observations for Wellmanifest adoption metadata."""
from __future__ import annotations

import json
from pathlib import Path


_SKIP_DIRS = {'.git', '.worktrees', '.venv', 'node_modules', '__pycache__'}


def _read_object(path: Path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f'{path}: {type(exc).__name__}: {exc}'
    if not isinstance(value, dict):
        return None, f'{path}: expected a JSON object'
    return value, None


def _repositories(root: Path, depth: int):
    """Find checkout roots, excluding linked-worktree implementation copies."""
    root = Path(root)
    found = []
    for candidate in [root, *root.rglob('*')]:
        try:
            relative_depth = len(candidate.relative_to(root).parts)
        except ValueError:
            continue
        if relative_depth > depth or not candidate.is_dir():
            continue
        if candidate.name in _SKIP_DIRS or any(part in _SKIP_DIRS for part in candidate.relative_to(root).parts):
            continue
        if (candidate / '.git').exists():
            found.append(candidate)
    return found


def _standards(adoption, lock):
    standards = []
    for item in adoption.get('adoptions', []) if isinstance(adoption, dict) else []:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str):
            continue
        standards.append({key: item.get(key) for key in ('id', 'version', 'revision', 'level', 'model')})
    standard = lock.get('standard') if isinstance(lock, dict) else None
    if isinstance(standard, dict) and isinstance(standard.get('id'), str):
        lock_pack = {
            'id': standard['id'], 'version': standard.get('version'),
            'revision': standard.get('sourceRevision'), 'level': None, 'model': None,
        }
        if not any(pack['id'] == lock_pack['id'] for pack in standards):
            standards.append(lock_pack)
    return sorted(standards, key=lambda item: item['id'])


def scan(root, depth=2):
    """Collect local adoption declarations and compare only local immutable pins."""
    root = Path(root)
    repositories, errors, pins = [], [], {}
    for repo_root in _repositories(root, depth):
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
        standards = _standards(adoption, lock)
        for pack in standards:
            revision = pack.get('revision')
            if isinstance(revision, str) and revision:
                pins.setdefault(pack['id'], set()).add(revision)
        try:
            name = repo_root.relative_to(root).as_posix() or repo_root.name
        except ValueError:
            name = repo_root.name
        repositories.append({
            'name': name, 'path': str(repo_root),
            'mode': adoption.get('mode', 'missing') if adoption else 'missing',
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
