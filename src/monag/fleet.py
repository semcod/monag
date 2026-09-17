"""Fleet refactoring metrics: publication truth, clone identity and lease age.

Counting unfinished work across a fleet of checkouts is easy to get wrong, and
every mistake inflates the same direction — more work looks unfinished than is.
Three traps produced an 18x overcount in a manual audit on 2026-09-17:

1. **Stale remote refs.** ``ahead > 0`` against a local ``origin/main`` that was
   never fetched reports merged work as unmerged. This module records
   ``base_ref_age_seconds`` so a reader can tell a real delta from a stale ref,
   and never claims publication state when the base is missing.
2. **Parallel clones.** The same repository is often cloned several times
   (``subactor/docs`` and ``subactor-lifecycle-v7/docs``). Summing per-checkout
   rows counts one branch many times, so aggregates here are keyed by
   ``(remote_identity, branch)``.
3. **Squash and rebase merges.** A squashed branch never becomes an ancestor of
   the base, so ancestry alone reports delivered work as unpublished forever.
   Ancestry therefore yields ``unmerged_by_ancestry``, which is explicitly a
   *candidate* state; only a pull-request lookup can settle it, and that needs
   network access this module does not take.

A clone with no ``origin`` remote cannot be published at all. That is reported
as its own state rather than counted as pending work.
"""
from datetime import datetime, timezone
import json
import re

from .monitor import command

#: Publication candidacy of one checkout. Only ``merged_by_ancestry`` is a fact;
#: ``unmerged_by_ancestry`` needs a pull-request lookup to become one.
PUBLICATION_STATES = (
    'dirty',
    'unmerged_by_ancestry',
    'merged_by_ancestry',
    'no_remote',
    'no_base',
)

#: A lease older than this while still claiming work is reported as stale.
DEFAULT_STALE_LEASE_SECONDS = 12 * 3600


def _timestamp(value):
    """Parse an ISO-8601 lease timestamp, tolerating a trailing ``Z``."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def remote_identity(path):
    """Return ``owner/name`` for the checkout's ``origin``, or ``None``.

    Two checkouts sharing this value are clones of one repository, however
    unrelated their paths look.
    """
    output, error = command(['git', 'remote', 'get-url', 'origin'], path)
    if error or not output.strip():
        return None
    url = output.strip()
    match = re.search(r'(?:github\.com[:/])([^/]+/[^/]+?)(?:\.git)?$', url)
    return match[1] if match else url


def base_ref_age_seconds(path, base):
    """Seconds since ``base`` last moved, or ``None`` when it cannot be read.

    A large age means a publication verdict from ancestry may be reporting a
    stale ref rather than real unpublished work.
    """
    if not base:
        return None
    output, error = command(
        ['git', 'log', '-1', '--format=%ct', base], path)
    if error or not output.strip():
        return None
    try:
        return max(0, int(time_now()) - int(output.strip()))
    except ValueError:
        return None


def time_now():
    """Current epoch seconds; separated so tests can pin it."""
    return datetime.now(timezone.utc).timestamp()


def lease_age(lease_path, status, now=None):
    """Return ``(age_seconds, stale)`` for a checkout's lease claim.

    ``stale`` is true only for a lease that still claims work while its own
    timestamp is old. A released lease is never stale, and an unreadable
    timestamp yields ``None`` instead of a guess.
    """
    if str(status or 'unknown') in {'released', 'unknown'}:
        return None, False
    try:
        data = json.loads(lease_path.read_text())
    except (OSError, ValueError, AttributeError):
        return None, False
    claimed = _timestamp(data.get('claimedAt'))
    if claimed is None:
        return None, False
    reference = now if now is not None else time_now()
    age = max(0, int(reference - claimed.timestamp()))
    return age, age > DEFAULT_STALE_LEASE_SECONDS


def publication_state(row):
    """Classify one checkout's publication candidacy.

    Dirty wins over ancestry: uncommitted work cannot be published as it stands,
    whatever the commit graph says.
    """
    if row.get('remote_identity') is None:
        return 'no_remote'
    if row.get('changed_files'):
        return 'dirty'
    ahead = row.get('ahead')
    if ahead is None:
        return 'no_base'
    return 'unmerged_by_ancestry' if ahead > 0 else 'merged_by_ancestry'


def metrics(rows, stale_lease_seconds=DEFAULT_STALE_LEASE_SECONDS):
    """Aggregate fleet metrics from inspected checkout rows.

    ``checkouts`` counts rows as observed. ``distinct_branches`` deduplicates by
    ``(remote_identity, branch)`` so parallel clones of one repository do not
    multiply the same pending branch. The two differ whenever the fleet holds
    duplicate clones, and that gap is reported rather than hidden.
    """
    states = dict.fromkeys(PUBLICATION_STATES, 0)
    seen, duplicated, stale_leases = set(), 0, 0
    base_ages = []
    for row in rows:
        states[row.get('publication_state', 'no_base')] = states.get(
            row.get('publication_state', 'no_base'), 0) + 1
        key = (row.get('remote_identity'), row.get('branch'))
        if key[0] is not None and key[1]:
            if key in seen:
                duplicated += 1
            seen.add(key)
        if row.get('lease_stale'):
            stale_leases += 1
        age = row.get('base_ref_age_seconds')
        if isinstance(age, int):
            base_ages.append(age)
    unmerged = states.get('unmerged_by_ancestry', 0)
    return {
        'schema': 'monag.fleet-metrics/v1',
        'checkouts': len(rows),
        'distinct_branches': len(seen),
        'duplicate_clone_checkouts': duplicated,
        'publication_states': states,
        'stale_lease_claims': stale_leases,
        'stale_lease_threshold_seconds': stale_lease_seconds,
        'base_ref_age_seconds_max': max(base_ages) if base_ages else None,
        'refactoring_notes': [
            f'{unmerged} checkout(s) look unpublished by ancestry; a squash or '
            'rebase merge produces the same signal, so confirm each against its '
            'pull request before treating it as pending work.',
            f'{states.get("no_remote", 0)} checkout(s) have no origin remote and '
            'cannot be published at all.',
            f'{duplicated} checkout(s) repeat a branch already counted from '
            'another clone of the same repository.',
            f'{stale_leases} lease(s) still claim work while their own claim '
            'timestamp is older than the staleness threshold; a stale claim is '
            'not permission to take the work over.',
        ],
    }
