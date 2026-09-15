"""Read-only, single-repository code quality gate via semcod/regix.

Deliberately single-repository, never workspace-wide: `regix gates` runs
coverage across the whole test suite plus several static-analysis backends
and commonly takes on the order of a minute per repository (measured here:
~78s on monag itself, with its own default caching enabled). Scanning a
workspace of many repositories the way `catalog`/`audit`/`export` do would
take tens of minutes, so this module refuses workspace mode outright
instead of silently taking that long.

Only `regix gates` is ever invoked -- a read-only check against configured
quality thresholds, never a write/fix command.
"""
from datetime import datetime, timezone
from pathlib import Path
import json
import shutil
import subprocess
import time

SCHEMA = 'monag.quality/v1'
REGIX_BIN = 'regix'


def regix_available():
    return shutil.which(REGIX_BIN) is not None


def run_regix(args, timeout=180):
    """Mockable subprocess boundary; `regix gates` commonly takes ~60-90s."""
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, f'{args[0]}: {type(error).__name__}'
    # `regix gates` exits 1 by design when gates fail (--fail-on error default);
    # that is data to report, not a failure to read. Any other code is a real error.
    if proc.returncode not in (0, 1):
        return None, f'{args[0]} failed (exit {proc.returncode}): {proc.stderr.strip()[:200]}'
    return proc.stdout, None


def unavailable(root, error, started):
    return {'schema': SCHEMA, 'root': str(root), 'available': False, 'error': error,
            'duration_seconds': round(time.monotonic() - started, 2)}


def scan(root, timeout=180):
    root = Path(root)
    started = time.monotonic()
    if not (root / '.git').exists():
        return unavailable(root,
            'monag quality only supports a single repository checkout (--root must be a Git '
            'repository); regix gates costs roughly a minute per repository, so scanning a '
            'workspace of many repositories is refused, not attempted at that cost.', started)
    if not regix_available():
        return unavailable(root, f'{REGIX_BIN} not found on PATH.', started)
    out, error = run_regix([REGIX_BIN, 'gates', '--workdir', str(root), '--format', 'json'], timeout)
    if error:
        return unavailable(root, error, started)
    try:
        gates = json.loads(out)
    except ValueError:
        return unavailable(root, f'{REGIX_BIN}: invalid output', started)
    violations = gates.get('violations') if isinstance(gates.get('violations'), list) else []
    return {
        'schema': SCHEMA, 'root': str(root), 'available': True, 'error': None,
        'observed_at': datetime.now(timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - started, 2),
        'ref': gates.get('ref'), 'all_passed': gates.get('all_passed'),
        'error_count': gates.get('errors'), 'warning_count': gates.get('warnings'),
        'violations': violations, 'violation_count': len(violations),
        'notice': 'Read-only: only `regix gates` is invoked, never a write/fix command. '
                  'Single-repository only -- regix gates costs roughly a minute per repository.',
    }


def markdown(data, limit=30):
    from .presentation import table
    if not data['available']:
        return f"# MONAG — quality gate\n\n{data['error']}\n"
    lines = [f"# MONAG — quality gate ({data['root']})", '',
             f"ref: **{data['ref']}** · all passed: **{data['all_passed']}** · "
             f"errors: **{data['error_count']}** · warnings: **{data['warning_count']}** · "
             f"scan: {data['duration_seconds']} s.", '']
    shown = data['violations'][:limit]
    lines.append(table(['Severity', 'Metric', 'File', 'Symbol', 'Value', 'Threshold'],
                       [[v.get('severity'), v.get('metric'), v.get('file'), v.get('symbol') or '-',
                         v.get('value'), v.get('threshold')] for v in shown]))
    if len(data['violations']) > limit:
        lines.append(f"\n{len(data['violations']) - limit} more violations; use `--json`.\n")
    lines.extend(['', data['notice']])
    return '\n'.join(lines) + '\n'
