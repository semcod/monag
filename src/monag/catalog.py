"""Read-only catalog of local repositories: what each one is, from its own metadata.

No network calls and no LLM summarization: every field is either read verbatim
from a manifest or doc the project already ships (pyproject.toml, package.json,
README.md, ...) or a boolean/timestamp observed directly from the checkout. A
project with no declared description is reported as unknown, never guessed --
this is an index of what projects say about themselves, not an opinion.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import time

from .audit import targets as discover_targets
from .monitor import command, github_repo
from .presentation import table

SCHEMA = 'monag.catalog/v1'

STACK_MANIFESTS = {
    'python': ('pyproject.toml', 'setup.py', 'setup.cfg', 'requirements.txt'),
    'node': ('package.json',),
    'go': ('go.mod',),
    'rust': ('Cargo.toml',),
    'java': ('pom.xml', 'build.gradle', 'build.gradle.kts'),
    'docker': ('Dockerfile', 'docker-compose.yml', 'docker-compose.yaml'),
}


def detect_stacks(path):
    return sorted(name for name, files in STACK_MANIFESTS.items()
                 if any((path / name_file).is_file() for name_file in files))


def read_text(path, limit=200_000):
    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > limit:
            return None
        return path.read_text(errors='replace')
    except OSError:
        return None


def description_from_pyproject(path):
    text = read_text(path / 'pyproject.toml')
    if not text:
        return None
    match = re.search(r'(?m)^\s*description\s*=\s*"((?:[^"\\]|\\.)*)"', text)
    if not match:
        return None
    value = match.group(1).replace('\\"', '"').strip()
    return value or None


def description_from_package_json(path):
    text = read_text(path / 'package.json')
    if not text:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    value = data.get('description') if isinstance(data, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def description_from_readme(path):
    for name in ('README.md', 'README.rst', 'README.txt', 'README'):
        text = read_text(path / name)
        if not text:
            continue
        paragraph = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                if paragraph:
                    break
                continue
            if stripped.startswith(('#', '```', '![', '|', '<', '[!', '>')):
                continue
            paragraph.append(stripped)
        if paragraph:
            return ' '.join(paragraph)[:400]
    return None


DESCRIPTION_SOURCES = (
    (description_from_pyproject, 'pyproject.toml'),
    (description_from_package_json, 'package.json'),
    (description_from_readme, 'README.md'),
)


def entry_points(path):
    points = set()
    pyproject = read_text(path / 'pyproject.toml')
    if pyproject:
        section = re.search(r'(?ms)^\[project\.scripts\]\s*$(.*?)(?=^\[|\Z)', pyproject)
        if section:
            points.update(re.findall(r'(?m)^\s*([A-Za-z0-9_.-]+)\s*=', section.group(1)))
    package_json = read_text(path / 'package.json')
    if package_json:
        try:
            data = json.loads(package_json)
        except ValueError:
            data = None
        if isinstance(data, dict):
            bin_field = data.get('bin')
            if isinstance(bin_field, dict):
                points.update(k for k in bin_field if isinstance(k, str))
            elif isinstance(bin_field, str) and isinstance(data.get('name'), str):
                points.add(data['name'])
    return sorted(points)


def last_commit(path):
    out, error = command(['git', 'log', '-1', '--format=%ct%x00%s'], path)
    if error or not out.strip():
        return None, None
    stamp, _, subject = out.strip('\n').partition('\0')
    try:
        when = datetime.fromtimestamp(int(stamp), timezone.utc).isoformat()
    except (ValueError, OverflowError):
        return None, subject or None
    return when, subject or None


def describe_repo(path):
    """One repository's self-declared identity; never raises, errors are data."""
    path = Path(path)
    remote, _ = command(['git', 'config', '--get', 'remote.origin.url'], path)
    repo = github_repo(remote) if remote else None
    description, source = None, None
    for extractor, label in DESCRIPTION_SOURCES:
        description = extractor(path)
        if description:
            source = label
            break
    commit_at, commit_subject = last_commit(path)
    return {
        'path': str(path), 'name': path.name, 'repo': repo,
        'description': description, 'description_source': source,
        'stacks': detect_stacks(path), 'entry_points': entry_points(path),
        'has_docs': (path / 'docs').is_dir(),
        'has_tests': any((path / name).is_dir() for name in ('tests', 'test')),
        'has_changelog': (path / 'CHANGELOG.md').is_file(),
        'last_commit_at': commit_at, 'last_commit_subject': commit_subject,
    }


def scan(root, depth=2):
    started = time.monotonic()
    mode, paths, errors = discover_targets(root, depth)
    with ThreadPoolExecutor(max_workers=8) as pool:
        repositories = list(pool.map(describe_repo, paths))
    repositories.sort(key=lambda r: r['name'])
    return {
        'schema': SCHEMA, 'root': str(root), 'mode': mode,
        'observed_at': datetime.now(timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - started, 2),
        'repositories': repositories, 'repository_count': len(repositories),
        'described_count': sum(1 for r in repositories if r['description']),
        'undescribed_count': sum(1 for r in repositories if not r['description']),
        'errors': errors,
        'notice': 'Read-only, local-only catalog: every field is read verbatim from a '
                  "manifest or doc the project already ships, or observed directly from "
                  'the checkout. No network calls, no LLM summarization, no guessing -- '
                  'a project with no declared description is reported as unknown, not '
                  'invented.',
    }


def markdown(data, limit=40):
    lines = ['# MONAG — project catalog', '',
             f"Mode: **{data['mode']}** · repositories: **{data['repository_count']}** "
             f"({data['described_count']} with a declared description, "
             f"{data['undescribed_count']} unknown) · scan: {data['duration_seconds']} s.",
             '', '## Repositories', '']
    shown = data['repositories'][:limit]
    lines.append(table(['Name', 'Stacks', 'Description', 'Docs', 'Tests', 'Last commit'],
                       [[r['name'], ', '.join(r['stacks']) or '-',
                         r['description'] or '(undeclared)',
                         'yes' if r['has_docs'] else 'no', 'yes' if r['has_tests'] else 'no',
                         (r['last_commit_at'] or '-')[:10]] for r in shown]))
    undescribed = sorted(r['name'] for r in data['repositories'] if not r['description'])
    if undescribed:
        lines.extend(['', '## No declared description', '', ', '.join(undescribed[:limit])])
    lines.extend(['', f"Repositories shown: {min(limit, data['repository_count'])}/{data['repository_count']}.",
                 '', data['notice'], '', 'Full data and every row: `monag --json catalog`.'])
    return '\n'.join(lines) + '\n'
