"""Single-source-of-truth drift: every fact has one owner, every copy must match.

A drift specification (``monag.ssot-drift/v1``) lists facts. Each fact names
one *owner* source and any number of *copies*. ``monag drift`` reads all of
them read-only and reports, per copy, ``match``, ``mismatch`` or
``unavailable``. A mismatch means somebody changed a copy (or the owner)
without the other: the case that repeatedly broke a hardware rig when the
same pin, profile or address lived in several files and devices.

Sources (all read-only):

- ``{"oql": PATH, "key": K}``: value of ``SET 'K' 'V'`` in an OQL file;
- ``{"env": PATH, "key": K}``: ``K=V`` in a dotenv file;
- ``{"quadlet": PATH, "key": K}``: ``Environment=K=V`` in a systemd/quadlet unit;
- ``{"text": PATH, "key": K}``: alias of ``env`` for plain ``K=V`` files;
- ``{"http": URL, "json": "a.b.c"}``: GET, then a dotted path into the JSON.

File sources accept ``"ssh": "user@host"``; the file is read with ``cat``
over SSH (BatchMode, no command other than ``cat``). ``"expect"`` on a copy
replaces equality with the owner by a fixed expected value, for copies that
derive a different representation (for example a status string).
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
import urllib.request
from pathlib import Path

SCHEMA = 'monag.ssot-drift/v1'
FILE_KINDS = ('oql', 'env', 'quadlet', 'text')
HTTP_TIMEOUT = 8
SSH_TIMEOUT = 15


class SourceError(Exception):
    """A source could not be read; the copy is reported unavailable."""


def _read_file(source: dict, kind: str, reader=None) -> str:
    path = source[kind]
    host = source.get('ssh')
    if reader is not None:
        return reader(host, path)
    if host:
        if not re.fullmatch(r'[A-Za-z0-9_.@-]+', host):
            raise SourceError(f'invalid ssh target {host!r}')
        result = subprocess.run(
            ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', host, 'cat', '--', shlex.quote(path)],
            capture_output=True, text=True, timeout=SSH_TIMEOUT, check=False)
        if result.returncode != 0:
            raise SourceError((result.stderr.strip() or f'ssh cat failed ({result.returncode})')[:200])
        return result.stdout
    local = Path(path).expanduser()
    if not local.is_absolute() and source.get('_base'):
        local = Path(source['_base']) / local
    try:
        return local.read_text(encoding='utf-8')
    except OSError as exc:
        raise SourceError(str(exc)) from exc


def _oql_value(text: str, key: str):
    for line in text.splitlines():
        try:
            tokens = shlex.split(line, comments=True)
        except ValueError:
            continue
        if len(tokens) == 3 and tokens[0] == 'SET' and tokens[1] == key:
            return tokens[2]
    raise SourceError(f'SET {key!r} not found')


def _env_value(text: str, key: str):
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('#') or '=' not in line:
            continue
        name, value = line.split('=', 1)
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    raise SourceError(f'{key} not set')


def _quadlet_value(text: str, key: str):
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith('Environment='):
            continue
        for item in shlex.split(line[len('Environment='):]):
            if '=' in item and item.split('=', 1)[0] == key:
                return item.split('=', 1)[1]
    raise SourceError(f'Environment={key} not set')


def _http_value(source: dict, fetch=None):
    url = source['http']
    if fetch is not None:
        payload = fetch(url)
    else:
        try:
            with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as response:  # noqa: S310 - spec-declared GET
                payload = json.loads(response.read())
        except (OSError, ValueError) as exc:
            raise SourceError(str(exc)[:200]) from exc
    value = payload
    for part in source.get('json', '').split('.') if source.get('json') else []:
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            raise SourceError(f'json path {source["json"]!r} not found')
    return value


def read_source(source: dict, *, reader=None, fetch=None):
    """Return the normalised string value of one source or raise SourceError."""
    if 'http' in source:
        value = _http_value(source, fetch)
    else:
        kind = next((k for k in FILE_KINDS if k in source), None)
        if kind is None or 'key' not in source:
            raise SourceError('source needs oql/env/quadlet/text + key, or http')
        text = _read_file(source, kind, reader)
        parse = {'oql': _oql_value, 'quadlet': _quadlet_value}.get(kind, _env_value)
        value = parse(text, source['key'])
    return normalise(value)


def normalise(value) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def describe(source: dict) -> str:
    kind = 'http' if 'http' in source else next((k for k in FILE_KINDS if k in source), '?')
    where = source.get(kind, '')
    host = f"{source['ssh']}:" if source.get('ssh') else ''
    detail = source.get('json') or source.get('key') or ''
    return f'{kind} {host}{where} [{detail}]'


def load_spec(path: Path) -> dict:
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    if spec.get('schema') != SCHEMA or not isinstance(spec.get('facts'), list) or not spec['facts']:
        raise ValueError(f'drift spec must be {SCHEMA} with a non-empty facts list')
    ids = [fact.get('id') for fact in spec['facts']]
    if any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
        raise ValueError('every fact needs a unique id')
    base = str(Path(path).expanduser().resolve().parent)
    for fact in spec['facts']:
        if not isinstance(fact.get('owner'), dict) or not isinstance(fact.get('copies'), list):
            raise ValueError(f'fact {fact["id"]}: owner object and copies list are required')
        # Relative local paths resolve against the specification's directory.
        for source in [fact['owner'], *fact['copies']]:
            if not source.get('ssh'):
                source.setdefault('_base', base)
    return spec


def check(spec: dict, *, reader=None, fetch=None) -> dict:
    """Compare every copy with its owner; never writes anything."""
    facts = []
    counts = {'match': 0, 'mismatch': 0, 'unavailable': 0}
    for fact in spec['facts']:
        try:
            owner_value, owner_error = read_source(fact['owner'], reader=reader, fetch=fetch), None
        except SourceError as exc:
            owner_value, owner_error = None, str(exc)
        copies = []
        for copy in fact['copies']:
            name = copy.get('name') or describe(copy)
            expected = normalise(copy['expect']) if 'expect' in copy else owner_value
            try:
                observed = read_source(copy, reader=reader, fetch=fetch)
            except SourceError as exc:
                state, observed, error = 'unavailable', None, str(exc)
            else:
                error = None
                if expected is None:
                    state, error = 'unavailable', f'owner unreadable: {owner_error}'
                else:
                    state = 'match' if observed == expected else 'mismatch'
            counts[state] += 1
            copies.append({'name': name, 'source': describe(copy), 'expected': expected,
                           'observed': observed, 'state': state, 'error': error})
        facts.append({'id': fact['id'], 'description': fact.get('description', ''),
                      'owner': describe(fact['owner']), 'owner_value': owner_value,
                      'owner_error': owner_error, 'copies': copies})
    return {'schema': 'monag.ssot-drift-report/v1', 'spec': spec.get('name', ''),
            'summary': counts, 'drift': counts['mismatch'] > 0, 'facts': facts}


def markdown(report: dict) -> str:
    s = report['summary']
    lines = [f"# SSOT drift: {report.get('spec') or 'specification'}", '',
             f"match **{s['match']}** · mismatch **{s['mismatch']}** · unavailable **{s['unavailable']}**", '']
    for fact in report['facts']:
        owner = fact['owner_value'] if fact['owner_error'] is None else f"unreadable ({fact['owner_error']})"
        lines.append(f"## {fact['id']} = `{owner}`")
        lines.append(f"Owner: {fact['owner']}" + (f" — {fact['description']}" if fact['description'] else ''))
        lines.append('')
        lines.append('| Copy | State | Observed | Expected |')
        lines.append('| --- | --- | --- | --- |')
        for copy in fact['copies']:
            observed = copy['observed'] if copy['error'] is None else copy['error']
            mark = {'match': 'match', 'mismatch': '**MISMATCH**', 'unavailable': 'unavailable'}[copy['state']]
            lines.append(f"| {copy['name']} | {mark} | `{observed}` | `{copy['expected']}` |")
        lines.append('')
    return '\n'.join(lines)
