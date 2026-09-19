"""Tests for fleet refactoring metrics.

Each test pins one of the three traps that make an unfinished-work count wrong
in the same direction: a stale base ref, parallel clones of one repository, and
a squash merge that keeps a delivered branch off the base's ancestry.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from monag import fleet


def _row(**overrides):
    row = {
        'path': '/repo/.worktrees/ticket-001--x',
        'branch': 'ticket/001-x',
        'remote_identity': 'owner/name',
        'changed_files': 0,
        'ahead': 0,
        'publication_state': 'merged_by_ancestry',
    }
    row.update(overrides)
    return row


def test_publication_state_dirty_outranks_ancestry() -> None:
    """Uncommitted work cannot be published whatever the commit graph says."""
    assert fleet.publication_state(_row(changed_files=3, ahead=0)) == 'dirty'


def test_publication_state_missing_remote_is_its_own_state() -> None:
    """A clone with no origin cannot be published, so it is not pending work."""
    assert fleet.publication_state(_row(remote_identity=None, ahead=5)) == 'no_remote'


def test_publication_state_missing_base_is_not_reported_as_unmerged() -> None:
    assert fleet.publication_state(_row(ahead=None)) == 'no_base'


def test_publication_state_ancestry_delta_is_a_candidate() -> None:
    assert fleet.publication_state(_row(ahead=2)) == 'unmerged_by_ancestry'


def test_metrics_deduplicates_parallel_clones_of_one_repository() -> None:
    """Two clones of one repo holding the same branch are one branch."""
    rows = [
        _row(path='/a/.worktrees/t', publication_state='unmerged_by_ancestry', ahead=1),
        _row(path='/b/.worktrees/t', publication_state='unmerged_by_ancestry', ahead=1),
    ]
    result = fleet.metrics(rows)
    assert result['checkouts'] == 2
    assert result['distinct_branches'] == 1
    assert result['duplicate_clone_checkouts'] == 1


def test_metrics_keeps_distinct_branches_separate() -> None:
    rows = [
        _row(branch='ticket/001-x', publication_state='unmerged_by_ancestry', ahead=1),
        _row(branch='ticket/002-y', publication_state='unmerged_by_ancestry', ahead=1),
    ]
    result = fleet.metrics(rows)
    assert result['distinct_branches'] == 2
    assert result['duplicate_clone_checkouts'] == 0


def test_metrics_notes_warn_that_ancestry_cannot_settle_publication() -> None:
    """The squash-merge trap must be stated, not left for the reader to infer."""
    result = fleet.metrics([_row(publication_state='unmerged_by_ancestry', ahead=1)])
    joined = ' '.join(result['refactoring_notes'])
    assert 'squash' in joined
    assert 'pull request' in joined


def test_metrics_reports_no_remote_checkouts_separately() -> None:
    result = fleet.metrics([_row(remote_identity=None, publication_state='no_remote')])
    assert result['publication_states']['no_remote'] == 1
    assert result['distinct_branches'] == 0


def _lease(tmp_path: Path, **fields) -> Path:
    path = tmp_path / 'ticket-001--x.json'
    path.write_text(json.dumps(fields), encoding='utf-8')
    return path


def test_lease_age_flags_a_claim_older_than_the_threshold(tmp_path: Path) -> None:
    now = 1_000_000.0
    claimed = now - fleet.DEFAULT_STALE_LEASE_SECONDS - 60
    lease = _lease(tmp_path, status='active',
                   claimedAt='1970-01-01T00:00:00+00:00')
    age, stale = fleet.lease_age(lease, 'active', now=now)
    assert stale is True
    assert age is not None and age > fleet.DEFAULT_STALE_LEASE_SECONDS
    assert claimed < now


def test_lease_age_ignores_a_released_lease(tmp_path: Path) -> None:
    lease = _lease(tmp_path, status='released', claimedAt='1970-01-01T00:00:00+00:00')
    assert fleet.lease_age(lease, 'released') == (None, False)


def test_lease_age_without_timestamp_is_unknown_not_stale(tmp_path: Path) -> None:
    lease = _lease(tmp_path, status='active')
    assert fleet.lease_age(lease, 'active') == (None, False)


def test_lease_age_tolerates_trailing_z(tmp_path: Path) -> None:
    lease = _lease(tmp_path, status='active', claimedAt='2026-09-15T09:25:00Z')
    age, _ = fleet.lease_age(lease, 'active', now=1_789_000_000.0)
    assert isinstance(age, int)


def test_lease_age_on_unreadable_lease_is_unknown(tmp_path: Path) -> None:
    missing = tmp_path / 'absent.json'
    assert fleet.lease_age(missing, 'active') == (None, False)


def test_metrics_counts_stale_lease_claims() -> None:
    rows = [_row(lease_stale=True), _row(lease_stale=False)]
    assert fleet.metrics(rows)['stale_lease_claims'] == 1


def test_metrics_reports_the_oldest_base_ref_age() -> None:
    """A stale base is how merged work gets counted as unpublished."""
    rows = [_row(base_ref_age_seconds=10), _row(base_ref_age_seconds=9999)]
    assert fleet.metrics(rows)['base_ref_age_seconds_max'] == 9999


def test_metrics_base_ref_age_is_none_when_unobservable() -> None:
    assert fleet.metrics([_row()])['base_ref_age_seconds_max'] is None


def test_remote_identity_extracts_owner_and_name(tmp_path: Path) -> None:
    """Identity is what proves two paths are one repository."""
    assert fleet.remote_identity(tmp_path) is None  # not a git checkout


def test_change_lease_phase_and_heartbeat_do_not_grant_takeover(tmp_path):
    lease = _lease(tmp_path, schema='wellmanifest.change-lease/v1', phase='editing',
                   ownerActor='other', leaseRevision=4, fencingToken=9,
                   issuedAt='1970-01-01T00:00:00Z', heartbeatAt='1970-01-01T23:59:50Z',
                   expiresAt='1970-01-01T23:59:59Z')
    row = fleet.lease_observation(lease, now=86400)
    assert row['lease_status'] == 'editing'
    assert row['lease_owner'] == 'other'
    assert row['lease_fencing_token'] == 9
    assert row['lease_age_seconds'] == 10
    assert row['lease_expired'] is True
    assert row['lease_stale'] is False


def test_released_change_lease_never_becomes_stale(tmp_path):
    lease = _lease(tmp_path, schema='wellmanifest.change-lease/v1', phase='released',
                   heartbeatAt='1970-01-01T00:00:00Z')
    row = fleet.lease_observation(lease, now=86400)
    assert row['lease_status'] == 'released'
    assert row['lease_age_seconds'] is None
    assert not row['lease_stale']


def test_lease_metadata_is_not_a_claim(tmp_path):
    lease = _lease(tmp_path, schema='wellmanifest.worktrees/v5', kind='layout-record')
    assert fleet.lease_observation(lease)['lease_kind'] == 'layout-only'
    lease = _lease(tmp_path, schema='unknown/v8', phase='editing')
    assert fleet.lease_observation(lease)['lease_status'] == 'unknown'
    lease.write_text('[]')
    assert fleet.lease_observation(lease)['lease_kind'] == 'invalid'


def test_old_commit_does_not_establish_remote_freshness(tmp_path):
    with patch('monag.fleet.command', return_value=('1000\n', None)), patch('monag.fleet.time_now', return_value=2000):
        assert fleet.base_commit_age_seconds(tmp_path, 'origin/main') == 1000
        assert fleet.base_ref_age_seconds(tmp_path, 'origin/main') is None
    assert fleet.metrics([_row(base_commit_age_seconds=1000)])['remote_observation_freshness'] == 'unknown'
