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

from . import dsl, nl_contract

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
    {'uri': 'monag://snapshot', 'name': 'Workspace Snapshot', 'mimeType': 'text/markdown'},
    {'uri': 'monag://prs', 'name': 'Pull Requests & Unpushed Branches', 'mimeType': 'text/markdown'},
    {'uri': 'monag://audit', 'name': 'Planfile / GitHub Coverage Audit', 'mimeType': 'text/markdown'},
    {'uri': 'monag://resume', 'name': 'Worktrees & Backlog Inventory', 'mimeType': 'text/markdown'},
    {'uri': 'monag://usage', 'name': 'Agent Usage & Account Ledgers', 'mimeType': 'text/markdown'},
    {'uri': 'monag://advise', 'name': 'Architectural Advisory & Task Guidance', 'mimeType': 'text/markdown'},
]


def execute_tool(name, arguments, root, depth=2):
    """Keep legacy text while returning the same machine result as CLI/REST."""
    try:
        tool = next((item for item in TOOLS if item['name'] == name), None)
        if tool is None:
            raise ValueError(f'Unknown tool: {name}')
        nl_contract.validate(arguments, tool['inputSchema'])
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
    except (ValueError, TypeError, OverflowError) as error:
        result = nl_contract.envelope(success=False, status='VALIDATION_ERROR', error=error)
    if isinstance(name, str) and name in {'execute_dsl', 'nl_ask'}:
        text = json.dumps(result, ensure_ascii=False)
    elif result['success']:
        text = result['meta']['markdown']
    else:
        text = 'Error: ' + result['errors'][0]['message']
    return {'content': [{'type': 'text', 'text': text}],
            'structuredContent': result, 'isError': not result['success']}


def handle_tool_call(name, arguments, root, depth=2):
    """Compatibility helper for callers expecting just the text content array."""
    return execute_tool(name, arguments, root, depth)['content']


def read_resource(uri, root, depth=2):
    """Read resource content by URI and return markdown text."""
    if uri == 'schema://current':
        return json.dumps(nl_contract.grammar()['commandSchema'])
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
        res = dsl.execute('OBSERVE advise LIMIT 10', root, depth=depth)
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

    if not isinstance(params, dict):
        return {'jsonrpc': '2.0', 'id': msg_id, 'error': {'code': -32602, 'message': 'params must be an object'}}

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
        return {'jsonrpc': '2.0', 'id': msg_id,
                'result': execute_tool(tool_name, arguments, root, depth)}

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
                    'contents': [{'uri': uri, 'mimeType': 'application/json' if uri == 'schema://current' else 'text/markdown', 'text': text}],
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
