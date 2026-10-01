import json

import pytest

from monag import drift
from monag.cli import main

NODE = """VERSION: 6
CONFIG:
  NAME 'StackNet node'
  SET 'node.stacknet.uart_tx' '43'  # COMMU TTL
  SET 'node.stacknet.uart_rx' '44'
"""


def spec(tmp_path, store_tx='43'):
    owner = tmp_path / 'stacknet-node.oql'
    owner.write_text(NODE)
    store = tmp_path / 'store.oql'
    store.write_text(NODE.replace("'43'", f"'{store_tx}'"))
    env = tmp_path / '.env'
    env.write_text('STACKNET_HARDWARE_PROFILE=cores3-lan-dri0050\n')
    unit = tmp_path / 'backend.container'
    unit.write_text('[Container]\nEnvironment=STACKNET_TIC249_SIDECAR_URL=http://127.0.0.1:8205 OTHER=1\n')
    rig = tmp_path / 'rig.oql'
    rig.write_text("CONFIG:\n  SET 'rig.stacknet.firmware_profile' 'cores3-lan-dri0050'\n"
                   "  SET 'rig.tic249.sidecar_url' 'http://127.0.0.1:8205'\n")
    return {
        'schema': drift.SCHEMA, 'name': 'test rig',
        'facts': [
            {'id': 'uart_tx', 'owner': {'oql': str(owner), 'key': 'node.stacknet.uart_tx'},
             'copies': [{'name': 'store', 'oql': str(store), 'key': 'node.stacknet.uart_tx'},
                        {'name': 'device', 'http': 'http://stack/health',
                         'json': 'data.node_configuration.active.uart_tx'}]},
            {'id': 'profile', 'owner': {'oql': str(rig), 'key': 'rig.stacknet.firmware_profile'},
             'copies': [{'name': 'build env', 'env': str(env), 'key': 'STACKNET_HARDWARE_PROFILE'},
                        {'name': 'device', 'http': 'http://stack/health', 'json': 'data.hardware_profile.id'}]},
            {'id': 'sidecar', 'owner': {'oql': str(rig), 'key': 'rig.tic249.sidecar_url'},
             'copies': [{'name': 'quadlet', 'quadlet': str(unit), 'key': 'STACKNET_TIC249_SIDECAR_URL'},
                        {'name': 'health source', 'http': 'http://dn/motor', 'json': 'result.source',
                         'expect': 'displaynet-tic249-sidecar'}]},
        ]}


def fetch(url):
    if url == 'http://stack/health':
        return {'data': {'node_configuration': {'active': {'uart_tx': 43}},
                         'hardware_profile': {'id': 'cores3-lan-dri0050'}}}
    return {'result': {'source': 'displaynet-tic249-sidecar'}}


def test_everything_matches(tmp_path):
    report = drift.check(spec(tmp_path), fetch=fetch)
    assert report['summary'] == {'match': 6, 'mismatch': 0, 'unavailable': 0}
    assert report['drift'] is False


def test_stale_copy_is_a_mismatch(tmp_path):
    # 2026-10-01: the DisplayNet OQL store still said 17 while StackNet ran 43.
    report = drift.check(spec(tmp_path, store_tx='17'), fetch=fetch)
    copy = report['facts'][0]['copies'][0]
    assert copy['state'] == 'mismatch' and copy['observed'] == '17' and copy['expected'] == '43'
    assert report['drift'] is True
    assert '**MISMATCH**' in drift.markdown(report)


def test_unreachable_copy_is_unavailable_not_drift(tmp_path):
    def offline(url):
        if 'stack' in url:
            raise drift.SourceError('connection refused')
        return fetch(url)
    report = drift.check(spec(tmp_path), fetch=offline)
    assert report['summary']['unavailable'] == 2 and report['drift'] is False


def test_spec_validation(tmp_path):
    bad = tmp_path / 'bad.json'
    bad.write_text(json.dumps({'schema': 'other', 'facts': []}))
    with pytest.raises(ValueError):
        drift.load_spec(bad)


def test_cli_exit_code_reports_drift(tmp_path, capsys, monkeypatch):
    data = spec(tmp_path, store_tx='17')
    for fact in data['facts']:  # keep the CLI offline
        fact['copies'] = [c for c in fact['copies'] if 'http' not in c]
    path = tmp_path / 'spec.json'
    path.write_text(json.dumps(data))
    assert main(['drift', '--spec', str(path), '--json']) == 1
    assert json.loads(capsys.readouterr().out)['summary']['mismatch'] == 1


def test_relative_paths_resolve_against_the_spec(tmp_path, monkeypatch):
    (tmp_path / 'layers').mkdir()
    (tmp_path / 'layers' / 'node.oql').write_text(NODE)
    (tmp_path / 'copy.oql').write_text(NODE)
    path = tmp_path / 'spec.json'
    path.write_text(json.dumps({'schema': drift.SCHEMA, 'facts': [
        {'id': 'tx', 'owner': {'oql': 'layers/node.oql', 'key': 'node.stacknet.uart_tx'},
         'copies': [{'oql': 'copy.oql', 'key': 'node.stacknet.uart_tx'}]}]}))
    monkeypatch.chdir('/')
    assert drift.check(drift.load_spec(path))['summary']['match'] == 1
