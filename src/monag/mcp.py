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
import json
from pathlib import Path
import sys

from . import dsl

MCP_PROTOCOL_VERSION = '2024-11-05'
SERVER_NAME = 'monag-mcp'
SERVER_VERSION = '0.3.2'

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
            },
        },
    },
]

RESOURCES = [
    {'uri': 'monag://snapshot', 'name': 'Workspace Snapshot', 'mimeType': 'text/markdown'},
    {'uri': 'monag://prs', 'name': 'Pull Requests & Unpushed Branches', 'mimeType': 'text/markdown'},
    {'uri': 'monag://audit', 'name': 'Planfile / GitHub Coverage Audit', 'mimeType': 'text/markdown'},
    {'uri': 'monag://resume', 'name': 'Worktrees & Backlog Inventory', 'mimeType': 'text/markdown'},
    {'uri': 'monag://usage', 'name': 'Agent Usage & Account Ledgers', 'mimeType': 'text/markdown'},
    {'uri': 'monag://advise', 'name': 'Architectural Advisory & Task Guidance', 'mimeType': 'text/markdown'},
]


def handle_tool_call(name, arguments, root, depth=2):
    """Execute tool and return MCP formatted content array."""
    arguments = arguments or {}

    if name == 'monag_prs':
        query = dsl.Query(
            target='prs',
            hours=float(arguments.get('hours', 24.0)),
            state=arguments.get('state', 'all'),
            unpushed_only=bool(arguments.get('unpushed_only', False)),
        )
        res = dsl.execute(query, root, depth=depth)
        return [{'type': 'text', 'text': res['markdown']}]

    elif name == 'monag_audit':
        query = dsl.Query(
            target='audit',
            issue_limit=int(arguments.get('issue_limit', 200)),
            worktrees_only=bool(arguments.get('worktrees_only', False)),
            hours=float(arguments.get('hours', 24.0)),
        )
        res = dsl.execute(query, root, depth=depth)
        return [{'type': 'text', 'text': res['markdown']}]

    elif name == 'monag_status':
        query = dsl.Query(
            target='status',
            hours=float(arguments.get('hours', 24.0)),
            limit=int(arguments.get('limit', 20)),
        )
        res = dsl.execute(query, root, depth=depth)
        return [{'type': 'text', 'text': res['markdown']}]

    elif name == 'monag_resume':
        query = dsl.Query(target='resume')
        res = dsl.execute(query, root, depth=depth)
        return [{'type': 'text', 'text': res['markdown']}]

    elif name == 'monag_usage':
        query = dsl.Query(target='usage')
        res = dsl.execute(query, root, depth=depth)
        return [{'type': 'text', 'text': res['markdown']}]

    elif name == 'monag_catalog':
        query = dsl.Query(target='catalog')
        res = dsl.execute(query, root, depth=depth)
        return [{'type': 'text', 'text': res['markdown']}]

    elif name == 'monag_query':
        from . import dsl_llm
        q_str = arguments.get('query', '')
        res = dsl_llm.execute(q_str, root, depth=depth)
        if res.get('status') == 'error':
            return [{'type': 'text', 'text': f"Error: {res.get('error')}"}]
        return [{'type': 'text', 'text': res['markdown']}]

    elif name == 'monag_advise':
        from . import advise
        data = advise.advise(root, depth=depth, limit=int(arguments.get('limit', 10)),
                             radar=bool(arguments.get('radar', False)),
                             tier=arguments.get('tier'))
        return [{'type': 'text', 'text': advise.markdown(data)}]

    else:
        raise ValueError(f'Unknown tool: {name}')


def read_resource(uri, root, depth=2):
    """Read resource content by URI and return markdown text."""
    target = uri.replace('monag://', '').strip('/')
    if target == 'snapshot':
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
        from . import advise
        data = advise.advise(root, depth=depth, limit=10)
        return advise.markdown(data)
    else:
        raise ValueError(f'Unknown resource: {uri}')
    return res['markdown']


handle_resource_read = read_resource


def process_message(msg, root, depth=2):
    """Process single JSON-RPC message and return response dict or None for notifications."""
    if not isinstance(msg, dict):
        return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid Request'}}

    msg_id = msg.get('id')
    method = msg.get('method')
    params = msg.get('params', {})

    if not method:
        return {'jsonrpc': '2.0', 'id': msg_id, 'error': {'code': -32600, 'message': 'Method required'}}

    if method == 'initialize':
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
            content = handle_tool_call(tool_name, arguments, root, depth=depth)
            return {
                'jsonrpc': '2.0',
                'id': msg_id,
                'result': {'content': content, 'isError': False},
            }
        except Exception as error:
            return {
                'jsonrpc': '2.0',
                'id': msg_id,
                'result': {
                    'content': [{'type': 'text', 'text': f'Tool execution error: {error}'}],
                    'isError': True,
                },
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
            text = handle_resource_read(uri, root, depth=depth)
            return {
                'jsonrpc': '2.0',
                'id': msg_id,
                'result': {
                    'contents': [{'uri': uri, 'mimeType': 'text/markdown', 'text': text}],
                },
            }
        except Exception as error:
            return {
                'jsonrpc': '2.0',
                'id': msg_id,
                'error': {'code': -32602, 'message': str(error)},
            }

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

    for line in in_stream:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as err:
            err_resp = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': f'Parse error: {err}'}}
            out_stream.write(json.dumps(err_resp) + '\n')
            out_stream.flush()
            continue

        resp = process_message(msg, root, depth=depth)
        if resp is not None:
            out_stream.write(json.dumps(resp, ensure_ascii=True) + '\n')
            out_stream.flush()
