"""Extensible executable detection; never search prompts or arbitrary arguments."""
from pathlib import Path
import re

ALIASES = {name: name for name in (
    'codex', 'claude', 'aider', 'gemini', 'opencode', 'goose', 'cursor-agent',
    'amp', 'qwen', 'kilo', 'copilot', 'crush', 'openhands', 'continue', 'devin',
)}
MODULES = {'aider': 'aider', 'aider.main': 'aider', 'openhands': 'openhands'}
SCOPES = {'@openai/codex': 'codex', '@anthropic-ai/claude-code': 'claude',
          '@google/gemini-cli': 'gemini', '@qwen-code/qwen-code': 'qwen',
          '@github/copilot': 'copilot'}
# Agent Client Protocol adapters started by IDEs, e.g. claude-agent-acp or glm-acp-agent.
ACP = re.compile(r'[a-z0-9][a-z0-9_.-]*-(?:agent-acp|acp-agent|acp)')
# Helper modes selected by a leading flag are not agent sessions.
HELPER_FLAGS = {'--chrome-native-host'}


def aliases(entries=()):
    result = dict(ALIASES)
    for entry in entries:
        kind, sep, executable = entry.partition('=')
        if not sep or not re.fullmatch(r'[a-zA-Z0-9_-]+', kind) or not executable or Path(executable).name != executable:
            raise ValueError('--agent must be LABEL=EXECUTABLE (a basename, without a path)')
        result[executable] = kind
    return result


def kind_of(name, registry):
    return registry.get(name) or (name if ACP.fullmatch(name) else None)


def helper(arguments):
    # Only an exact leading flag is compared; a positional prompt is never read.
    return bool(arguments) and arguments[0] in HELPER_FLAGS


def identify(argv, registry=None):
    registry = ALIASES if registry is None else registry
    if not argv or not argv[0]:
        return None, False
    executable = Path(argv[0]).name
    kind = kind_of(executable, registry)
    if kind:
        return (None, False) if helper(argv[1:]) else (kind, False)
    runtime = executable in {'node', 'nodejs', 'bun', 'deno'} or re.fullmatch(r'python(?:\d+(?:\.\d+)*)?', executable)
    if not runtime or len(argv) < 2:
        return None, False
    if argv[1] == '-m' and len(argv) > 2:
        return MODULES.get(argv[2], registry.get(argv[2])), True
    # Only the runtime's entrypoint is inspected, never trailing arguments.
    script = argv[1]
    if script.startswith('-'):
        return None, False
    name = Path(script).name.removesuffix('.js').removesuffix('.mjs').removesuffix('.py')
    kind = kind_of(name, registry) or next((k for scope, k in SCOPES.items() if f'/{scope}/' in script), None)
    if not kind or helper(argv[2:]):
        return None, False
    return kind, True
