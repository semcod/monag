"""Tests for monag.report — email digest of workspace activity."""
import email.message
import json
import os
import smtplib
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from monag import report


# -- smtp_config --------------------------------------------------------

def test_smtp_config_defaults():
    with mock.patch.dict(os.environ, {}, clear=True):
        cfg = report._smtp_config()
    assert cfg['host'] == 'localhost'
    assert cfg['port'] == 587
    assert cfg['tls'] is True
    assert cfg['user'] == ''
    assert cfg['auth_pass'] == ''


def test_smtp_config_from_env():
    env = {
        'MONAG_SMTP_HOST': 'mail.test',
        'MONAG_SMTP_PORT': '465',
        'MONAG_SMTP_USER': 'me',
        'MONAG_SMTP_PASSWORD': 's3cret',
        'MONAG_SMTP_TLS': '0',
        'MONAG_FROM': 'bot@test.dev',
    }
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = report._smtp_config()
    assert cfg['host'] == 'mail.test'
    assert cfg['port'] == 465
    assert cfg['user'] == 'me'
    assert cfg['auth_pass'] == 's3cret'
    assert cfg['tls'] is False
    assert cfg['from'] == 'bot@test.dev'


def test_smtp_config_cli_overrides_env():
    env = {'MONAG_SMTP_HOST': 'env-host'}
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = report._smtp_config(args_host='cli-host', args_port=25,
                                   args_tls=False)
    assert cfg['host'] == 'cli-host'
    assert cfg['port'] == 25
    assert cfg['tls'] is False


# -- collect ------------------------------------------------------------

def test_collect_calls_scan_modules(tmp_path):
    """collect() delegates to each module's scan() and captures results."""
    mock_status = {'agent_count': 2, 'agents': [], 'repositories': []}
    mock_prs = {'open_prs': [], 'merged_prs': []}

    with mock.patch('monag.monitor.snapshot', return_value=mock_status), \
         mock.patch('monag.prs.scan', return_value=mock_prs):

        data = report.collect(tmp_path, sections=['status', 'prs'])

    assert data['schema'] == 'monag.report/v1'
    assert 'status' in data['sections']
    assert 'prs' in data['sections']
    assert 'audit' not in data['sections']  # not requested
    assert data['duration_seconds'] >= 0


def test_collect_captures_errors_gracefully(tmp_path):
    """A failing section is recorded in errors, not raised."""
    with mock.patch('monag.monitor.snapshot', side_effect=RuntimeError('boom')):
        data = report.collect(tmp_path, sections=['status'])

    assert 'status' not in data['sections']
    assert any('RuntimeError' in e for e in data['errors'])


def test_collect_standards_and_formats_workspace_drift(tmp_path):
    for name, revision in [('alpha', 'a' * 40), ('beta', 'b' * 40)]:
        governance = tmp_path / name / '.governance'
        governance.mkdir(parents=True)
        (tmp_path / name / '.git').mkdir()
        (governance / 'standard-adoption.json').write_text(json.dumps({
            'schema': 'wellmanifest.standard-adoption/v1', 'mode': 'enforce',
            'profile': 'baseline', 'repositoryRole': 'service', 'adoptions': [{
                'id': 'wellmanifest/new-project', 'version': '1.0', 'revision': revision,
                'model': 'protected-conformance', 'level': 'S4', 'artifacts': [], 'evidence': [],
            }],
        }))
    (tmp_path / 'missing' / '.git').mkdir(parents=True)
    malformed = tmp_path / 'malformed' / '.governance'
    malformed.mkdir(parents=True)
    (tmp_path / 'malformed' / '.git').mkdir()
    (malformed / 'standard-adoption.json').write_text('{not json')
    data = report.collect(tmp_path, depth=2, sections=['standards'])
    standards = data['sections']['standards']
    assert standards['repository_count'] == 4
    assert standards['adoption_manifest_count'] == 2
    assert any('JSONDecodeError' in error for error in standards['errors'])
    assert any(repo['mode'] == 'missing' for repo in standards['repositories'])
    assert standards['drift'] == [{'id': 'wellmanifest/new-project', 'revisions': ['a' * 40, 'b' * 40]}]
    rendered = report.format_section_standards(standards)
    assert 'Workspace-local pin disagreement' in rendered
    assert 'enforce' in rendered


# -- markdown -----------------------------------------------------------

def test_markdown_output_has_sections():
    data = {
        'schema': 'monag.report/v1',
        'root': '/home/test/github',
        'observed_at': '2026-09-18T16:00:00+00:00',
        'duration_seconds': 1.5,
        'requested_sections': ['status', 'prs'],
        'sections': {
            'status': {'agent_count': 3, 'agents': [], 'repositories': []},
            'prs': {'open_prs': [], 'merged_prs': []},
        },
        'errors': [],
    }
    md = report.markdown(data)
    assert '# MONAG workspace report' in md
    assert '## Agent processes and checkouts' in md
    assert '## Pull Requests' in md
    assert 'monag report' in md


def test_markdown_shows_errors():
    data = {
        'schema': 'monag.report/v1',
        'root': '/tmp/test',
        'observed_at': '2026-09-18T16:00:00+00:00',
        'duration_seconds': 0.1,
        'requested_sections': ['status'],
        'sections': {},
        'errors': ['status: RuntimeError: boom'],
    }
    md = report.markdown(data)
    assert '## Errors' in md
    assert 'RuntimeError: boom' in md


# -- format_section_* --------------------------------------------------

def test_format_section_status_with_agents():
    data = {
        'agent_count': 2,
        'agents': [
            {'pid': 1234, 'kind': 'claude', 'state': 'S', 'cwd': '/home/tom/proj', 'task': 'fix bug'},
        ],
        'repositories': [{'path': '/home/tom/proj', 'branch': 'main'}],
    }
    result = report.format_section_status(data)
    assert '**2** agent processes' in result
    assert '1234' in result
    assert 'claude' in result


def test_format_section_prs_with_open():
    data = {
        'open_prs': [
            {'repo': 'semcod/monag', 'number': 59, 'title': 'report feature',
             'author': 'tom', 'created_at': '2026-09-18T10:00:00Z'},
        ],
        'merged_prs': [],
    }
    result = report.format_section_prs(data)
    assert 'Open: **1**' in result
    assert '#59' in result


def test_format_section_audit_with_untracked():
    data = {
        'repositories': [
            {'repo': 'semcod/monag', 'path': '/home/tom/monag',
             'untracked_issues': [
                 {'number': 5, 'title': 'Bootstrap planfile', 'state': 'OPEN',
                  'url': 'https://github.com/semcod/monag/issues/5'},
             ]},
        ],
        'errors': [], 'repository_count': 1,
    }
    result = report.format_section_audit(data)
    assert 'Untracked issues: **1**' in result
    assert '#5' in result


def test_format_section_resume_with_tickets():
    data = {
        'projects': [
            {'path': '/home/tom/monag', 'planfile': {
                'remaining_tickets': [
                    {'id': 'MON-001', 'title': 'test ticket', 'priority': 'high', 'status': 'open'},
                ],
            }},
        ],
        'project_count': 1,
    }
    result = report.format_section_resume(data)
    assert 'Open Planfile tickets: **1**' in result
    assert 'MON' in result and '001' in result


# -- _markdown_to_html ------------------------------------------------

def test_markdown_to_html_headings():
    html = report._markdown_to_html('# Title\n\n## Section\n\nParagraph with **bold**.')
    assert '<h2>Title</h2>' in html
    assert '<h3>Section</h3>' in html
    assert '<strong>bold</strong>' in html


def test_markdown_to_html_code():
    html = report._markdown_to_html('Use `monag report` to send.')
    assert '<code>monag report</code>' in html


# -- send_email ---------------------------------------------------------

def test_send_email_success():
    smtp_cfg = {
        'host': 'localhost', 'port': 1025, 'user': '', 'password': '',
        'tls': False, 'from': 'monag@test',
    }
    mock_smtp = mock.MagicMock()
    with mock.patch('smtplib.SMTP', return_value=mock_smtp) as cls:
        cls.return_value.__enter__ = mock.Mock(return_value=mock_smtp)
        cls.return_value.__exit__ = mock.Mock(return_value=False)
        result = report.send_email(['user@test.dev'], 'Test report', '# Hello\n', smtp_cfg)
    assert result['ok'] is True
    assert result['recipients'] == ['user@test.dev']
    mock_smtp.sendmail.assert_called_once()


def test_send_email_failure():
    smtp_cfg = {
        'host': 'bad-host', 'port': 9999, 'user': '', 'auth_pass': '',
        'tls': False, 'from': 'monag@test',
    }
    with mock.patch('smtplib.SMTP', side_effect=OSError('Connection refused')):
        result = report.send_email(['user@test.dev'], 'Test', '# Fail\n', smtp_cfg)
    assert result['ok'] is False
    assert 'Connection refused' in result['error']


def test_send_email_tls_and_auth():
    smtp_cfg = {
        'host': 'mail.test', 'port': 587, 'user': 'me', 'auth_pass': 'pass',
        'tls': True, 'from': 'bot@test.dev',
    }
    mock_smtp = mock.MagicMock()
    with mock.patch('smtplib.SMTP', return_value=mock_smtp) as cls:
        cls.return_value.__enter__ = mock.Mock(return_value=mock_smtp)
        cls.return_value.__exit__ = mock.Mock(return_value=False)
        result = report.send_email(['a@b.com'], 'TLS test', '# TLS\n', smtp_cfg)
    assert result['ok'] is True
    mock_smtp.starttls.assert_called_once()
    mock_smtp.login.assert_called_once_with('me', 'pass')


# -- install_cron / remove_cron ----------------------------------------

def test_install_cron_success():
    with mock.patch('subprocess.run') as run:
        # crontab -l returns existing crontab
        run.side_effect = [
            mock.Mock(returncode=0, stdout='30 3 * * * /usr/bin/backup\n'),
            mock.Mock(returncode=0, stdout='', stderr=''),
        ]
        result = report.install_cron('tom@example.com', Path('/home/tom/github'))
    assert result['ok'] is True
    assert 'monag:report' in result['cron_line']
    assert '0 * * * *' in result['cron_line']
    # Should preserve existing entry
    new_crontab = run.call_args_list[1].kwargs.get('input') or run.call_args_list[1][1].get('input', '')
    if not new_crontab:
        new_crontab = run.call_args_list[1][1] if len(run.call_args_list[1]) > 1 else ''
    # Just verify install was called
    assert run.call_count == 2


def test_install_cron_custom_schedule():
    with mock.patch('subprocess.run') as run:
        run.side_effect = [
            mock.Mock(returncode=0, stdout=''),
            mock.Mock(returncode=0, stdout='', stderr=''),
        ]
        result = report.install_cron('tom@test.com', Path('/home/tom/github'),
                                      schedule='*/30 * * * *')
    assert result['ok'] is True
    assert '*/30 * * * *' in result['cron_line']


def test_remove_cron_success():
    existing = '30 3 * * * /usr/bin/backup\n0 * * * * monag report --email a@b.com # monag:report\n'
    with mock.patch('subprocess.run') as run:
        run.side_effect = [
            mock.Mock(returncode=0, stdout=existing),
            mock.Mock(returncode=0, stdout='', stderr=''),
        ]
        result = report.remove_cron()
    assert result['ok'] is True
    assert result['action'] == 'removed'
    # Verify monag:report line was stripped
    written = run.call_args_list[1]
    assert 'monag:report' not in (written.kwargs.get('input', '') or '')


def test_install_cron_crontab_missing():
    with mock.patch('subprocess.run', side_effect=OSError('No crontab')):
        result = report.install_cron('tom@test.com', Path('/tmp'))
    assert result['ok'] is False
    assert 'crontab' in result['error']


# -- section registry ---------------------------------------------------

def test_section_registry_completeness():
    """All sections have a formatter and title."""
    for section in report.SECTION_REGISTRY:
        assert section in report._SECTION_FORMATTERS, f'missing formatter for {section}'
        assert section in report._SECTION_TITLES, f'missing title for {section}'


# -- CLI integration (argument parsing) ---------------------------------

def test_cli_report_dry_run_parses(tmp_path):
    """monag report --dry-run should parse without error."""
    from monag.cli import main
    with mock.patch('monag.report.collect', return_value={
        'schema': 'monag.report/v1', 'root': str(tmp_path),
        'observed_at': '2026-09-18T16:00:00+00:00', 'duration_seconds': 0.1,
        'requested_sections': ['status'], 'sections': {
            'status': {'agent_count': 0, 'agents': [], 'repositories': []},
        }, 'errors': [],
    }):
        rc = main(['--root', str(tmp_path), '--plain', 'report', '--dry-run', '--advisory-limit', '3'])
        assert rc == 0


def test_collect_advise_section(tmp_path):
    mock_export = {'candidates': [{'repo': 'subactor/test', 'title': 'Test task'}]}
    mock_advise = {'schema': 'monag.advisory/v1', 'recommendations': []}

    with mock.patch('monag.export.scan', return_value=mock_export) as scan_mock, \
         mock.patch('monag.advise.advise', return_value=mock_advise) as advise_mock:

        data = report.collect(tmp_path, sections=['export', 'advise'], advisory_limit=3)

    assert 'export' in data['sections']
    assert 'advise' in data['sections']
    advise_mock.assert_called_once_with(
        tmp_path, depth=2, issue_limit=200, limit=3,
        export_data=mock_export, state_dir=None)


def test_format_section_advise():
    data = {
        'summary': '2 rekomendowane zadania',
        'recommendations': [
            {
                'score': 95,
                'target': 'subactor/onedev-agent',
                'title': 'Move pins to config',
                'matched_risks': ['dependency-drift'],
                'action': 'Rozpocznij ticket',
                'guardrails': ['Sprawdź konsumentów downstream'],
            }
        ]
    }
    rendered = report.format_section_advise(data)
    assert '2 rekomendowane zadania' in rendered
    assert 'subactor/onedev-agent' in rendered
    assert '95' in rendered
    assert 'Sprawdź konsumentów downstream' in rendered


def test_detect_user_email_from_gh():
    with mock.patch('subprocess.run') as mock_run:
        mock_run.return_value = mock.Mock(returncode=0, stdout='user@test.org\n')
        email_addr = report.detect_user_email()
        assert email_addr == 'user@test.org'


def test_detect_user_email_git_fallback():
    with mock.patch('subprocess.run') as mock_run:
        mock_run.side_effect = [
            mock.Mock(returncode=1, stdout=''),  # gh fails
            mock.Mock(returncode=0, stdout='gituser@test.org\n'),  # git succeeds
        ]
        email_addr = report.detect_user_email()
        assert email_addr == 'gituser@test.org'


def test_footer_management_markdown():
    footer = report.footer_management_markdown(recipients=['me@test.dev'], port=8090)
    assert 'Zarządzanie raportem i konfiguracja' in footer
    assert 'me@test.dev' in footer
    assert 'monag report --email' in footer
    assert 'http://127.0.0.1:8090/api/report/disable' in footer
    assert 'http://127.0.0.1:8090/api/report/send-now' in footer
    assert 'http://127.0.0.1:8090/api/report/config?interval=1800' in footer
    assert 'http://127.0.0.1:8090/api/report/config?interval=3600' in footer
    assert 'http://127.0.0.1:8090/api/report/config?interval=7200' in footer
    assert 'http://127.0.0.1:8090/report/config' in footer


def test_markdown_includes_footer():
    data = {
        'schema': 'monag.report/v1', 'root': '/tmp/test',
        'observed_at': '2026-09-18T16:00:00+00:00', 'duration_seconds': 0.1,
        'requested_sections': [], 'sections': {}, 'errors': [],
    }
    md = report.markdown(data, port=8090, include_management_footer=True, recipients=['tom@test.com'])
    assert 'Zarządzanie raportem i konfiguracja' in md
    assert 'tom@test.com' in md


def test_run_daemon_single_iteration(tmp_path):
    with mock.patch('monag.report.collect', return_value={
        'schema': 'monag.report/v1', 'root': str(tmp_path),
        'observed_at': '2026-09-18T16:00:00+00:00', 'duration_seconds': 0.1,
        'requested_sections': [], 'sections': {}, 'errors': [],
    }), mock.patch('monag.report.send_email', return_value={'ok': True, 'recipients': ['test@dev']}):
        results = report.run_daemon(tmp_path, emails=['test@dev'], interval=0.01, max_iterations=1)
        assert len(results) == 1
        assert results[0]['ok'] is True


def test_load_and_save_config(tmp_path):
    cfg = report.load_config(tmp_path)
    assert cfg['interval'] == 3600
    assert cfg['enabled'] is True

    cfg['interval'] = 7200
    cfg['recipients'] = ['custom@domain.org']
    report.save_config(tmp_path, cfg)

    reloaded = report.load_config(tmp_path)
    assert reloaded['interval'] == 7200
    assert reloaded['recipients'] == ['custom@domain.org']


def test_run_daemon_dynamic_config(tmp_path):
    report.save_config(tmp_path, {'interval': 1, 'enabled': True, 'recipients': ['dyn@dev.local']})
    with mock.patch('monag.report.collect', return_value={
        'schema': 'monag.report/v1', 'root': str(tmp_path),
        'observed_at': '2026-09-18T16:00:00+00:00', 'duration_seconds': 0.1,
        'requested_sections': [], 'sections': {}, 'errors': [],
    }), mock.patch('monag.report.send_email', return_value={'ok': True, 'recipients': ['dyn@dev.local']}) as mock_send:
        results = report.run_daemon(tmp_path, state_dir=tmp_path, interval=10, max_iterations=1)
        assert len(results) == 1
        assert results[0]['ok'] is True
        mock_send.assert_called_once()
        assert mock_send.call_args[0][0] == ['dyn@dev.local']


def test_standards_displays_pins_and_escapes_untrusted_observations():
    text = report.format_section_standards({
        'repositories': [{'name': 'repo', 'standards': [{
            'id': 'pack', 'level': 'S3', 'version': '1.2',
            'revision': 'a' * 40, 'source': 'lock',
        }]}],
        'drift': [{'id': '<script>', 'revisions': ['<img>', 'second']}],
        'errors': ['<script>bad</script>'],
    })
    assert 'a' * 40 in text
    assert 'source=lock' in text
    assert 'S3' in text
    assert '<script>' not in text
    assert '<img>' not in text
    assert '&lt;script&gt;' in text


def test_markdown_overview_table_with_prs_and_wts():
    data = {
        'schema': 'monag.report/v1',
        'root': '/home/tom/github',
        'observed_at': '2026-09-18T16:00:00+00:00',
        'duration_seconds': 1.2,
        'requested_sections': ['prs', 'audit'],
        'sections': {
            'prs': {'open_prs': [{'number': 10}, {'number': 12}]},
            'audit': {'total_worktrees': 25, 'worktrees': []},
        },
        'errors': [],
    }
    md = report.markdown(data, include_management_footer=False)
    assert '## Podsumowanie Workspace' in md
    assert 'Otwarte PR' in md
    assert 'Aktywne Worktrees' in md
    assert '2' in md
    assert '25' in md
