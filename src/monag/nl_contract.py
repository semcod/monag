"""Closed observation profile of wellmanifest/nl-dsl-llm (2040efe37b9e).

All executable inputs validate against COMMAND_SCHEMA before DSL dispatch.
The validator implements only the keywords used by this fixed, local schema;
it is not a general-purpose JSON Schema library or a remote schema resolver.
Mutating MONAG commands and MCP client registration are outside this profile.
"""
import copy
import math
import time
import uuid

STANDARD_REVISION = '2040efe37b9eb898350f3fec0285a2d4e69d4e34'
DOMAINS = ['prs', 'audit', 'status', 'resume', 'usage', 'catalog', 'advise']
PARAMETERS = {
    'hours': {'type': 'number', 'minimum': 0},
    'state': {'type': 'string', 'enum': ['all', 'open', 'merged']},
    'limit': {'type': 'integer', 'minimum': 1},
    'unpushed_only': {'type': 'boolean'},
    'worktrees_only': {'type': 'boolean'},
    'issue_limit': {'type': 'integer', 'minimum': 1},
    'radar': {'type': 'boolean'},
    'tier': {'type': 'string', 'enum': ['all', 'floor', 'mission', 'hygiene', 'backlog']},
    'emit_planfile': {'type': 'boolean'},
}
COMMAND_SCHEMA = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    'title': 'MONAG read-only observation command',
    'type': 'object', 'additionalProperties': False,
    'required': ['entity', 'operation'],
    'properties': {
        'entity': {'type': 'string', 'enum': DOMAINS},
        'operation': {'type': 'string', 'enum': ['query']},
        'arguments': {'type': 'object', 'additionalProperties': False,
                      'properties': PARAMETERS},
    },
}


def validate(value, schema, field='input'):
    """Validate this profile's closed object/scalar schemas without coercion."""
    kind = schema['type']
    matches = {
        'object': lambda: isinstance(value, dict),
        'string': lambda: isinstance(value, str),
        'boolean': lambda: type(value) is bool,
        'integer': lambda: type(value) is int,
        'number': lambda: type(value) in (int, float) and math.isfinite(value),
    }
    if kind not in matches or not matches[kind]():
        raise ValueError(f'{field} must be {kind}')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(f'{field} must be one of {schema["enum"]}')
    if 'minimum' in schema and value < schema['minimum']:
        raise ValueError(f'{field} must be >= {schema["minimum"]}')
    if kind == 'object':
        properties = schema.get('properties', {})
        if schema.get('additionalProperties') is False and set(value) - set(properties):
            raise ValueError(f'{field} has unsupported fields')
        if set(schema.get('required', [])) - set(value):
            raise ValueError(f'{field} is missing required fields')
        for name, item in value.items():
            if name in properties:
                validate(item, properties[name], f'{field}.{name}')


def command(query):
    arguments = {name: getattr(query, name) for name in PARAMETERS}
    if arguments['issue_limit'] is None:
        del arguments['issue_limit']
    return {'entity': query.target, 'operation': 'query', 'arguments': arguments}


def validate_query(query):
    validate(command(query), COMMAND_SCHEMA)


def grammar():
    """Return a fresh JSON schema and discoverable invocation contract."""
    return {
        'standard': 'wellmanifest/nl-dsl-llm', 'sourceRevision': STANDARD_REVISION,
        'profile': 'read-only observations; mutation commands are not covered',
        'commandSchema': copy.deepcopy(COMMAND_SCHEMA),
        'dsl': 'OBSERVE <domain> [HOURS n] [STATE all|open|merged] [LIMIT n] '
               '[ISSUE_LIMIT n] [UNPUSHED_ONLY] [WORKTREES_ONLY] [RADAR] '
               '[TIER all|floor|mission|hygiene|backlog] [EMIT_PLANFILE]',
        'domains': list(DOMAINS),
        'examples': ['OBSERVE catalog', 'OBSERVE prs STATE open', 'OBSERVE advise LIMIT 10'],
        'interfaces': {'mcp': ['nl_ask', 'execute_dsl', 'describe_grammar'],
                       'cli': ['monag --json ask "pokaż katalog"',
                               'monag --json dsl "OBSERVE catalog"'],
                       'rest': ['/api/v1/query', '/api/v1/dsl', '/api/v1/schema']},
    }


def envelope(*, success, status, data=None, error=None, source='direct_dsl',
             canonical=None, provenance=None, markdown='', started=None):
    return {
        'success': success, 'status': status, 'data': data,
        'errors': [] if success else [{'code': status, 'message': str(error)}],
        'meta': {'executionTimeMs': max(0, (time.perf_counter() - started) * 1000) if started else 0,
                 'sourceLayer': source, 'canonicalDsl': canonical,
                 'traceId': str(uuid.uuid4()), 'provenance': provenance,
                 'markdown': markdown, 'standardRevision': STANDARD_REVISION},
    }


def execute(value, root, *, direct=False, allow_llm_fallback=True, locale=None, **options):
    """Resolve and validate once, then dispatch exclusively through the DSL."""
    from . import dsl, dsl_llm
    started = time.perf_counter()
    source = 'direct_dsl' if direct else 'nl_fast_path'
    canonical = None
    prov = None
    try:
        if type(allow_llm_fallback) is not bool:
            raise ValueError('allow_llm_fallback must be boolean')
        if locale not in (None, 'pl', 'en'):
            raise ValueError('locale must be pl or en')
        if direct and isinstance(value, dict):
            validate(value, COMMAND_SCHEMA)
            query = dsl.Query(value['entity'], **value.get('arguments', {}))
            prov = dsl_llm.provenance('rule', query.to_dsl())
        else:
            if not isinstance(value, str) or not value.strip():
                raise ValueError('A nonempty query or DSL statement is required')
            canonical_input = value.lstrip().upper().startswith('OBSERVE')
            if direct or canonical_input:
                source = 'direct_dsl'
                query = dsl.parse_dsl(value)
                prov = dsl_llm.provenance('rule', query.to_dsl() if query else None, value)
            else:
                query, prov = dsl_llm.resolve(value, command=None if allow_llm_fallback else '')
                source = ('llm_fallback' if prov['engine'] == 'llm' or
                          prov.get('attempted_engine') == 'llm' else 'nl_fast_path')
            if query is None:
                raise ValueError('Unrecognized or invalid observation command')
        validate_query(query)
        canonical = query.to_dsl()
    except (ValueError, TypeError, OverflowError) as error:
        return envelope(success=False, status='VALIDATION_ERROR', error=error,
                        source=source, canonical=canonical, provenance=prov, started=started)
    try:
        result = dsl.execute(query, root, **options)
        if result.get('status') == 'error':
            raise ValueError(result.get('error', 'Observation failed'))
        return envelope(success=True, status='OK', data=result.get('data'),
                        source=source, canonical=canonical, provenance=prov,
                        markdown=result.get('markdown', ''), started=started)
    except Exception as error:
        return envelope(success=False, status='EXECUTION_ERROR', error=error,
                        source=source, canonical=canonical, provenance=prov, started=started)
