"""Model Context Protocol (MCP) Server for Monag.

Exposes Monag observations to AI agents (Claude, Cursor, Antigravity, Windsurf)
via standard JSON-RPC 2.0 protocol over stdio.

Supported capabilities:
- Tools:
    - monag_status: observe live agent processes and active checkouts
    - monag_prs: inspect open vs merged PRs and unpushed branches
    - monag_audit: compare Planfile tickets with GitHub Issues
    - monag_resume: inventory worktrees and local Planfile backlog
    - monag_usage: read agent CPU usage and api-budget ledgers
    - monag_catalog: list declared repository metadata
    - monag_query: execute natural language or DSL observation queries
- Resources:
    - monag://snapshot, monag://prs, monag://audit, monag://resume, monag://usage
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import uuid

from . import dsl, nl_contract

MCP_PROTOCOL_VERSION = '2024-11-05'
SERVER_NAME = 'monag-mcp'
SERVER_VERSION = '0.3.2'


class SessionState:
    UNINITIALIZED = 'uninitialized'
    ACTIVE = 'active'
    CLOSED = 'closed'
    TERMINATED = 'terminated'


CLI_FALLBACK_MAPPING = {
    'monag_status': 'monag status [--json] [--hours H] [--limit N]',
    'monag_prs': 'monag prs [--json] [--state open|merged|all] [--hours H]',
    'monag_audit': 'monag audit [--json] [--hours H] [--issue-limit N]',
    'monag_resume': 'monag resume [--json]',
    'monag_usage': 'monag usage [--json]',
    'monag_catalog': 'monag tools [--json]',
    'monag_advise': 'monag advise [--json] [--tier floor|mission|hygiene|backlog]',
    'monag_query': 'monag ask "<natural language query>" [--json]',
    'execute_dsl': 'monag dsl "<OBSERVE statement>" [--json]',
    'describe_grammar': 'monag dsl --help (or schema://current resource)',
    'monag_health': 'monag mcp --health',
}


class MCPSession:
    def __init__(self, session_id=None):
        self.session_id = session_id or str(uuid.uuid4())
        self.state = SessionState.UNINITIALIZED
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.last_activity_at = self.created_at
        self.requests_total = 0
        self.tools_called = 0
        self.errors_total = 0
        self.last_error = None
        self.reconnect_count = 0

    def touch(self):
        self.last_activity_at = datetime.now(timezone.utc).isoformat()
        self.requests_total += 1

    def record_error(self, err_msg):
        self.errors_total += 1
        self.last_error = {
            'time': datetime.now(timezone.utc).isoformat(),
            'message': str(err_msg)
        }

    def close(self):
        self.state = SessionState.CLOSED

    def terminate(self, reason=None):
        self.state = SessionState.TERMINATED
        if reason:
            self.record_error(reason)

    def reconnect(self):
        self.reconnect_count += 1
        self.state = SessionState.ACTIVE
        self.touch()


_current_session = None


def get_session():
    global _current_session
    if _current_session is None:
        _current_session = MCPSession()
    return _current_session


def reset_session():
    global _current_session
    _current_session = MCPSession()
    return _current_session


def get_transport_health(session=None):
    sess = session or get_session()
    return {
        'schema': 'monag.mcp/health/v1',
        'status': 'healthy' if sess.state != SessionState.TERMINATED else 'terminated',
        'server': {
            'name': SERVER_NAME,
            'version': SERVER_VERSION,
            'protocol_version': MCP_PROTOCOL_VERSION,
        },
        'transport': {
            'type': 'stdio',
            'connected': sess.state == SessionState.ACTIVE,
        },
        'session': {
            'session_id': sess.session_id,
            'state': sess.state,
            'created_at': sess.created_at,
            'last_activity_at': sess.last_activity_at,
            'requests_total': sess.requests_total,
            'tools_called': sess.tools_called,
            'errors_total': sess.errors_total,
            'last_error': sess.last_error,
            'reconnect_count': sess.reconnect_count,
        },
        'cli_health': {
            'status': 'healthy',
            'independent_from_mcp': True,
            'note': 'CLI executes directly against workspace and local state without stdio transport overhead.',
        },
        'cli_fallbacks': CLI_FALLBACK_MAPPING,
    }


def format_health_markdown(health):
    sess = health['session']
    lines = [
        '# MONAG · MCP Transport & Session Health',
        '',
        f"- **Transport**: stdio (JSON-RPC 2.0)",
        f"- **Session ID**: `{sess['session_id'][:8]}`",
        f"- **State**: `{sess['state']}`",
        f"- **Requests Served**: {sess['requests_total']}",
        f"- **Tools Called**: {sess['tools_called']}",
        f"- **Errors**: {sess['errors_total']}",
        f"- **Reconnects**: {sess['reconnect_count']}",
        f"- **CLI Independence**: Local CLI remains healthy even if MCP transport disconnects.",
        '',
    ]
    if sess.get('last_error'):
        lines.append(f"> [!WARNING] Last error: {sess['last_error']['message']} ({sess['last_error']['time']})\n")
    lines.append('## Bounded Read-Only CLI Fallbacks')
    lines.append('If the MCP connection terminates or is unavailable, run equivalent read-only CLI commands directly:')
    lines.append('')
    for tool, cmd in health['cli_fallbacks'].items():
        lines.append(f"- `{tool}`: `{cmd}`")
    lines.append('')
    return '\n'.join(lines)


TOOLS = [
    {
        'name': 'monag_prs',
        'description': 'Audit GitHub Pull Requests (open, merged) and local unpushed branches across repositories.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'hours': {'type': 'number', 'description': 'Time window in hours for PR recency (default: 24.0)', 'default': 24.0},
                'state': {'type': 'string', 'enum': ['all', 'open', 'merged'], 'description': 'Filter PRs by state (default: all)', 'default': 'all'},
                'unpushed_only': {'type': 'boolean', 'description': 'Show only branches with unpushed commits or no PR', 'default': False},
            },
        },
    },
    {
        'name': 'monag_audit',
        'description': 'Compare local Planfile ticket coverage against GitHub Issues and check worktree recency.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'issue_limit': {'type': 'integer', 'description': 'GitHub issues fetched per repository (default: 200)', 'default': 200},
                'worktrees_only': {'type': 'boolean', 'description': 'Report only local worktree activity and uncommitted status', 'default': False},
                'hours': {'type': 'number', 'description': 'Recency window in hours (default: 24.0)', 'default': 24.0},
            },
        },
    },
    {
        'name': 'monag_status',
        'description': 'Get one snapshot of recognized agent processes and repository activity in the workspace.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'hours': {'type': 'number', 'description': 'Recent commit recency window in hours (default: 24.0)', 'default': 24.0},
                'limit': {'type': 'integer', 'description': 'Maximum rows per section (default: 20)', 'default': 20},
            },
        },
    },
    {
        'name': 'monag_resume',
        'description': 'Read-only restart inventory of worktree checkouts and open Planfile backlog tickets.',
        'inputSchema': {
            'type': 'object',
            'properties': {},
        },
    },
    {
        'name': 'monag_usage',
        'description': 'Read-only table of agent process resource usage and api-budget account ledgers.',
        'inputSchema': {
            'type': 'object',
            'properties': {},
        },
    },
    {
        'name': 'monag_catalog',
        'description': 'Read-only local catalog of declared repository metadata and tech stacks.',
        'inputSchema': {
            'type': 'object',
            'properties': {},
        },
    },
    {
        'name': 'monag_query',
        'description': 'Execute an observation query using natural language (in Polish or English) or structured DSL.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string', 'description': 'Natural language phrase or OBSERVE DSL command (e.g. "pokaż niescalone PR", "OBSERVE prs STATE open")'},
            },
            'required': ['query'],
        },
    },
    {
        'name': 'monag_advise',
        'description': 'Generate architectural guidance and prioritized next tasks combining candidate items, Priority DSL tiers, and reflex learning loop patterns.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'limit': {'type': 'integer', 'description': 'Maximum recommendations to return (default: 10)', 'default': 10},
                'radar': {'type': 'boolean', 'description': 'Include ticket-radar sizing', 'default': False},
                'tier': {
                    'type': 'string',
                    'description': 'Filter by Priority DSL tier (floor, mission, hygiene, backlog, all)',
                    'enum': ['all', 'floor', 'mission', 'hygiene', 'backlog'],
                    'default': 'all',
                },
                'emit_planfile': {
                    'type': 'boolean',
                    'description': 'Output tickets formatted for planfile ticket import instead of markdown',
                    'default': False,
                },
            },
        },
    },
]

TOOLS.extend([
    {'name': 'monag_health', 'description': 'Expose MCP server transport health, session lifecycle state, and bounded read-only CLI fallback commands.',
     'inputSchema': {
         'type': 'object',
         'properties': {
             'as_json': {'type': 'boolean', 'description': 'Format output text as JSON instead of Markdown', 'default': False},
         },
     }},
    {'name': 'execute_dsl', 'description': 'Execute one strictly validated MONAG OBSERVE statement.',
     'inputSchema': {'type': 'object', 'required': ['dsl_command'],
                     'properties': {'dsl_command': {'type': 'string'}}}},
    {'name': 'nl_ask', 'description': 'Resolve Polish or English observation queries; LLM translation is optional.',
     'inputSchema': {'type': 'object', 'required': ['query'], 'properties': {
         'query': {'type': 'string'}, 'allow_llm_fallback': {'type': 'boolean', 'default': True},
         'locale': {'type': 'string', 'enum': ['pl', 'en']}}}},
    {'name': 'describe_grammar', 'description': 'Describe the pinned observation schema, domains and interfaces.',
     'inputSchema': {'type': 'object', 'properties': {}}},
])
for tool in TOOLS:
    tool['inputSchema']['additionalProperties'] = False
    tool['annotations'] = {'readOnlyHint': True, 'destructiveHint': False}


RESOURCES = [
    {'uri': 'schema://current', 'name': 'Observation command JSON Schema', 'mimeType': 'application/json'},
    {'uri': 'monag://health', 'name': 'MCP Transport & Session Health', 'mimeType': 'text/markdown'},
    {'uri': 'monag://snapshot', 'name': 'Workspace Snapshot', 'mimeType': 'text/markdown'},
    {'uri': 'monag://prs', 'name': 'Pull Requests & Unpushed Branches', 'mimeType': 'text/markdown'},
    {'uri': 'monag://audit', 'name': 'Planfile / GitHub Coverage Audit', 'mimeType': 'text/markdown'},
    {'uri': 'monag://resume', 'name': 'Worktrees & Backlog Inventory', 'mimeType': 'text/markdown'},
    {'uri': 'monag://usage', 'name': 'Agent Usage & Account Ledgers', 'mimeType': 'text/markdown'},
    {'uri': 'monag://advise', 'name': 'Architectural Advisory & Task Guidance', 'mimeType': 'text/markdown'},
]


def execute_tool(name, arguments, root, depth=2, session=None):
    """Keep legacy text while returning the same machine result as CLI/REST."""
    sess = session or get_session()
    sess.tools_called += 1
    try:
        fallback_cmd = CLI_FALLBACK_MAPPING.get(name, 'monag status [--json]') if isinstance(name, str) else 'monag status [--json]'
        tool = next((item for item in TOOLS if item['name'] == name), None)
        if tool is None:
            raise ValueError(f'Unknown tool: {name}')
        nl_contract.validate(arguments, tool['inputSchema'])
        if name == 'monag_health':
            health_data = get_transport_health(sess)
            if arguments.get('as_json', False):
                out_text = json.dumps(health_data, indent=2, ensure_ascii=False)
            else:
                out_text = format_health_markdown(health_data)
            return {'content': [{'type': 'text', 'text': out_text}],
                    'structuredContent': health_data, 'isError': False}
        if name == 'describe_grammar':
            result = nl_contract.grammar()
            return {'content': [{'type': 'text', 'text': json.dumps(result)}],
                    'structuredContent': result, 'isError': False}
        if name == 'execute_dsl':
            result = nl_contract.execute(arguments['dsl_command'], root, direct=True, depth=depth)
        elif name in {'nl_ask', 'monag_query'}:
            result = nl_contract.execute(arguments['query'], root, depth=depth,
                                         allow_llm_fallback=arguments.get('allow_llm_fallback', True),
                                         locale=arguments.get('locale'))
        else:
            target = name.removeprefix('monag_')
            values = dict(arguments)
            if target == 'advise':
                values.setdefault('limit', 10)
            result = nl_contract.execute({'entity': target, 'operation': 'query',
                                          'arguments': values}, root, direct=True, depth=depth)
        if isinstance(name, str) and name in {'execute_dsl', 'nl_ask'}:
            text = json.dumps(result, ensure_ascii=False)
        elif result.get('success'):
            text = result.get('meta', {}).get('markdown', str(result))
        else:
            err_msg = result.get('errors', [{}])[0].get('message', 'Unknown error') if result.get('errors') else str(result)
            sess.record_error(f"Tool '{name}' failed: {err_msg}")
            text = f"Error: {err_msg}. CLI fallback: '{fallback_cmd}'"
        return {'content': [{'type': 'text', 'text': text}],
                'structuredContent': result, 'isError': not result.get('success', True)}
    except Exception as error:
        err_msg = f"Tool '{name}' failed: {error}"
        sess.record_error(err_msg)
        result = nl_contract.envelope(success=False, status='VALIDATION_ERROR', error=error)
        if isinstance(name, str) and name in {'execute_dsl', 'nl_ask'}:
            text = json.dumps(result, ensure_ascii=False)
        else:
            text = f"Error: {error}. CLI fallback: '{fallback_cmd}'"
        return {
            'content': [{'type': 'text', 'text': text}],
            'structuredContent': result,
            'isError': True,
        }


def handle_tool_call(name, arguments, root, depth=2, session=None):
    """Compatibility helper for callers expecting just the text content array."""
    return execute_tool(name, arguments, root, depth, session=session)['content']


def read_resource(uri, root, depth=2, session=None):
    """Read resource content by URI and return markdown text."""
    if uri == 'schema://current':
        return json.dumps(nl_contract.grammar()['commandSchema'])
    target = uri.replace('monag://', '').strip('/')
    if target == 'health':
        return format_health_markdown(get_transport_health(session))
    elif target == 'snapshot':
        res = dsl.execute('OBSERVE status', root, depth=depth)
    elif target in {'prs', 'pr'}:
        res = dsl.execute('OBSERVE prs', root, depth=depth)
    elif target == 'audit':
        res = dsl.execute('OBSERVE audit', root, depth=depth)
    elif target == 'resume':
        res = dsl.execute('OBSERVE resume', root, depth=depth)
    elif target == 'usage':
        res = dsl.execute('OBSERVE usage', root, depth=depth)
    elif target == 'advise':
        res = dsl.execute('OBSERVE advise LIMIT 10', root, depth=depth)
    else:
        raise ValueError(f'Unknown resource: {uri}')
    return res['markdown']


handle_resource_read = read_resource


def process_message(msg, root, depth=2, session=None):
    """Process single JSON-RPC message and return response dict or None for notifications."""
    sess = session or get_session()
    sess.touch()

    if not isinstance(msg, dict):
        sess.record_error('Invalid Request: msg must be object')
        return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid Request'}}

    msg_id = msg.get('id')
    method = msg.get('method')
    params = msg.get('params', {})

    if not isinstance(params, dict):
        sess.record_error('params must be an object')
        return {'jsonrpc': '2.0', 'id': msg_id, 'error': {'code': -32602, 'message': 'params must be an object'}}

    if not method:
        sess.record_error('Method required')
        return {'jsonrpc': '2.0', 'id': msg_id, 'error': {'code': -32600, 'message': 'Method required'}}

    if method == 'initialize':
        if sess.state in (SessionState.ACTIVE, SessionState.CLOSED, SessionState.TERMINATED):
            sess.reconnect()
        else:
            sess.state = SessionState.ACTIVE
        return {
            'jsonrpc': '2.0',
            'id': msg_id,
            'result': {
                'protocolVersion': MCP_PROTOCOL_VERSION,
                'capabilities': {
                    'tools': {},
                    'resources': {},
                },
                'serverInfo': {
                    'name': SERVER_NAME,
                    'version': SERVER_VERSION,
                },
            },
        }

    if method in {'notifications/initialized', 'initialized'}:
        sess.state = SessionState.ACTIVE
        return None

    if method == 'ping':
        return {'jsonrpc': '2.0', 'id': msg_id, 'result': {}}

    if method == 'tools/list':
        return {
            'jsonrpc': '2.0',
            'id': msg_id,
            'result': {'tools': TOOLS},
        }

    if method == 'tools/call':
        tool_name = params.get('name')
        arguments = params.get('arguments', {})
        try:
            return {'jsonrpc': '2.0', 'id': msg_id,
                    'result': execute_tool(tool_name, arguments, root, depth, session=sess)}
        except Exception as exc:
            sess.record_error(f"tools/call '{tool_name}' failed: {exc}")
            fallback = CLI_FALLBACK_MAPPING.get(tool_name, 'monag status') if isinstance(tool_name, str) else 'monag status'
            return {
                'jsonrpc': '2.0',
                'id': msg_id,
                'error': {
                    'code': -32603,
                    'message': f"Internal error during tool '{tool_name}': {exc}",
                    'data': {'cli_fallback': fallback}
                }
            }

    if method == 'resources/list':
        return {
            'jsonrpc': '2.0',
            'id': msg_id,
            'result': {'resources': RESOURCES},
        }

    if method == 'resources/read':
        uri = params.get('uri')
        try:
            text = handle_resource_read(uri, root, depth=depth, session=sess)
            return {
                'jsonrpc': '2.0',
                'id': msg_id,
                'result': {
                    'contents': [{'uri': uri, 'mimeType': 'application/json' if uri == 'schema://current' else 'text/markdown', 'text': text}],
                },
            }
        except Exception as error:
            sess.record_error(f"resources/read '{uri}' failed: {error}")
            return {
                'jsonrpc': '2.0',
                'id': msg_id,
                'error': {'code': -32602, 'message': str(error)},
            }

    sess.record_error(f'Method not found: {method}')
    return {
        'jsonrpc': '2.0',
        'id': msg_id,
        'error': {'code': -32601, 'message': f'Method not found: {method}'},
    }


def run_stdio_server(root, depth=2, in_stream=None, out_stream=None):
    """Run JSON-RPC stdio loop until EOF."""
    in_stream = in_stream or sys.stdin
    out_stream = out_stream or sys.stdout

    root = Path(root).expanduser().resolve()
    session = get_session()

    for line in in_stream:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as err:
            session.record_error(f'Parse error: {err}')
            err_resp = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': f'Parse error: {err}'}}
            out_stream.write(json.dumps(err_resp) + '\n')
            out_stream.flush()
            continue

        try:
            resp = process_message(msg, root, depth=depth, session=session)
            if resp is not None:
                out_stream.write(json.dumps(resp, ensure_ascii=True) + '\n')
                out_stream.flush()
        except Exception as exc:
            session.record_error(f'Unhandled server exception: {exc}')
            err_resp = {
                'jsonrpc': '2.0',
                'id': msg.get('id') if isinstance(msg, dict) else None,
                'error': {
                    'code': -32603,
                    'message': f'Server internal exception: {exc}',
                    'data': {'cli_fallback': 'monag status --json'}
                }
            }
            out_stream.write(json.dumps(err_resp) + '\n')
            out_stream.flush()

    session.close()


def diagnose_server(root, depth=2):
    """Run simulated client lifecycle and tool calls to diagnose MCP server health."""
    test_session = MCPSession()
    steps = []
    root = Path(root).expanduser().resolve()

    # Step 1: Initialize
    init_req = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}}
    init_resp = process_message(init_req, root, depth=depth, session=test_session)
    ok_init = init_resp.get('result', {}).get('protocolVersion') == MCP_PROTOCOL_VERSION
    steps.append({'step': 'initialize', 'ok': ok_init, 'response': init_resp.get('result')})

    # Step 2: Tools list
    tools_req = {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}}
    tools_resp = process_message(tools_req, root, depth=depth, session=test_session)
    tools = [t['name'] for t in tools_resp.get('result', {}).get('tools', [])]
    expected_tools = {'monag_status', 'monag_usage', 'monag_prs', 'describe_grammar', 'monag_health'}
    ok_tools = expected_tools.issubset(set(tools))
    steps.append({'step': 'tools/list', 'ok': ok_tools, 'tools_count': len(tools)})

    # Step 3: Call monag_health
    health_req = {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'monag_health', 'arguments': {}}}
    health_resp = process_message(health_req, root, depth=depth, session=test_session)
    ok_health = not health_resp.get('result', {}).get('isError', True)
    steps.append({'step': 'tools/call monag_health', 'ok': ok_health})

    # Step 4: Call describe_grammar (reproducing Issue #122 audit target)
    grammar_req = {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'describe_grammar', 'arguments': {}}}
    grammar_resp = process_message(grammar_req, root, depth=depth, session=test_session)
    ok_grammar = not grammar_resp.get('result', {}).get('isError', True)
    steps.append({'step': 'tools/call describe_grammar', 'ok': ok_grammar})

    # Step 5: Resources read monag://health
    res_req = {'jsonrpc': '2.0', 'id': 5, 'method': 'resources/read', 'params': {'uri': 'monag://health'}}
    res_resp = process_message(res_req, root, depth=depth, session=test_session)
    ok_res = 'contents' in res_resp.get('result', {})
    steps.append({'step': 'resources/read monag://health', 'ok': ok_res})

    # Step 6: Test graceful client reconnect
    reconnect_req = {'jsonrpc': '2.0', 'id': 6, 'method': 'initialize', 'params': {}}
    reconnect_resp = process_message(reconnect_req, root, depth=depth, session=test_session)
    ok_reconnect = test_session.reconnect_count == 1 and test_session.state == SessionState.ACTIVE
    steps.append({'step': 'client reconnect', 'ok': ok_reconnect, 'reconnect_count': test_session.reconnect_count})

    all_ok = all(s['ok'] for s in steps)
    health = get_transport_health(test_session)

    md_lines = [
        '# MONAG · MCP Diagnostic Report',
        '',
        f"- **Overall Status**: {'PASS' if all_ok else 'FAIL'}",
        f"- **Session ID**: `{test_session.session_id}`",
        f"- **Requests Executed**: {test_session.requests_total}",
        f"- **Errors**: {test_session.errors_total}",
        f"- **Reconnect Verified**: {'YES' if ok_reconnect else 'NO'}",
        '',
        '### Step Verification',
    ]
    for s in steps:
        status_sym = 'PASS' if s['ok'] else 'FAIL'
        md_lines.append(f"- `[{status_sym}]` {s['step']}")
    md_lines.append('')
    md_lines.append('### Bounded Read-Only CLI Fallbacks')
    for tool, cmd in health['cli_fallbacks'].items():
        md_lines.append(f"- `{tool}` → `{cmd}`")
    md_lines.append('')

    return {
        'schema': 'monag.mcp/diagnostics/v1',
        'ok': all_ok,
        'steps': steps,
        'health': health,
        'markdown': '\n'.join(md_lines),
    }
