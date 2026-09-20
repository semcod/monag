"""Regression coverage for untrusted workspace adoption observations."""
import json
from pathlib import Path

import pytest

from monag import governance


def repository(root, adoption=None, lock=None):
    (root / '.git').mkdir(parents=True)
    metadata = root / '.governance'
    metadata.mkdir()
    for name, value in [('standard-adoption.json', adoption), ('manifest.lock.json', lock)]:
        if value is not None:
            (metadata / name).write_text(json.dumps(value))
    return root


@pytest.mark.parametrize('value', [None, 1, 'invalid', {}])
def test_malformed_adoptions_are_reported_without_aborting(tmp_path, value):
    repository(tmp_path / 'bad', {'adoptions': value})
    repository(tmp_path / 'good', {'adoptions': [{'id': 'wellmanifest/worktrees'}]})
    result = governance.scan(tmp_path)
    assert result['repository_count'] == 2
    assert any('adoptions must be an array' in error for error in result['errors'])
    assert result['repositories'][1]['standards'][0]['id'] == 'wellmanifest/worktrees'


def test_depth_and_exclusions_prune_traversal(tmp_path, monkeypatch):
    repository(tmp_path / 'repo')
    repository(tmp_path / '.worktrees' / 'hidden')
    repository(tmp_path / 'repo' / 'too-deep')
    original = Path.iterdir
    visited = []

    def observed(path):
        visited.append(path)
        return original(path)

    monkeypatch.setattr(Path, 'iterdir', observed)
    assert len(governance.scan(tmp_path, depth=1)['repositories']) == 1
    assert visited == [tmp_path]
    visited.clear()
    governance.scan(tmp_path, depth=0)
    assert visited == []


def test_symlink_is_not_followed(tmp_path):
    repository(tmp_path / 'real')
    (tmp_path / 'alias').symlink_to(tmp_path / 'real', target_is_directory=True)
    (tmp_path / 'real' / 'loop').symlink_to(tmp_path, target_is_directory=True)
    assert governance.scan(tmp_path, depth=5)['repository_count'] == 1


@pytest.mark.parametrize('name, payload', [
    ('standard-adoption.json', {'adoptions': [{'id': 'external-pack'}]}),
    ('manifest.lock.json', {'standard': {'id': 'external-pack', 'sourceRevision': 'a' * 40}}),
])
def test_symlinked_metadata_is_not_trusted(tmp_path, name, payload):
    root = repository(tmp_path / 'repo')
    target = tmp_path / 'outside.json'
    target.write_text(json.dumps(payload))
    (root / '.governance' / name).symlink_to(target)

    result = governance.scan(tmp_path, depth=1)

    assert result['repositories'][0]['standards'] == []
    assert any('symlink metadata is not allowed' in error for error in result['errors'])


def test_conflicting_lock_pin_is_preserved(tmp_path):
    repository(tmp_path, {'adoptions': [{'id': 'pack', 'revision': 'a' * 40}]},
               {'standard': {'id': 'pack', 'sourceRevision': 'b' * 40}})
    result = governance.scan(tmp_path, depth=0)
    assert result['drift'] == [{'id': 'pack', 'revisions': ['a' * 40, 'b' * 40]}]
    assert 'adoption/lock disagreement' in result['errors'][0]
    assert {p['source'] for p in result['repositories'][0]['standards']} == {'adoption', 'lock'}
    assert result['repositories'][0]['name'] == tmp_path.name


def test_matching_lock_pin_does_not_duplicate_or_report_drift(tmp_path):
    repository(tmp_path, {'adoptions': [{'id': 'pack', 'revision': 'a' * 40}]},
               {'standard': {'id': 'pack', 'sourceRevision': 'a' * 40}})
    result = governance.scan(tmp_path, depth=0)
    assert result['errors'] == []
    assert result['drift'] == []
    assert len(result['repositories'][0]['standards']) == 1


def test_invalid_utf8_is_distinct_from_missing_manifest(tmp_path):
    repository(tmp_path)
    (tmp_path / '.governance' / 'standard-adoption.json').write_bytes(b'\xff')
    result = governance.scan(tmp_path, depth=0)
    assert result['repositories'][0]['mode'] == 'invalid'
    assert 'UnicodeDecodeError' in result['errors'][0]


@pytest.mark.parametrize('value', [None, [], {'id': ''}, {'id': 'pack', 'sourceRevision': []}])
def test_invalid_lock_is_reported(tmp_path, value):
    repository(tmp_path, lock={'standard': value})
    result = governance.scan(tmp_path)
    assert result['errors']
    assert result['repositories'][0]['standards'] == []


def test_invalid_items_do_not_hide_valid_items(tmp_path):
    repository(tmp_path, {'adoptions': [None, {'id': ''}, {'id': 'bad', 'revision': []}, {'id': 'good'}]})
    result = governance.scan(tmp_path)
    assert len(result['errors']) == 3
    assert [p['id'] for p in result['repositories'][0]['standards']] == ['good']


def test_unreadable_directory_is_observation_error(tmp_path, monkeypatch):
    def denied(path):
        raise PermissionError('denied')
    monkeypatch.setattr(Path, 'iterdir', denied)
    result = governance.scan(tmp_path)
    assert 'PermissionError' in result['errors'][0]


@pytest.mark.parametrize('depth', [-1, True, 1.5])
def test_invalid_depth_is_rejected(tmp_path, depth):
    with pytest.raises(ValueError, match='non-negative integer'):
        governance.scan(tmp_path, depth)
