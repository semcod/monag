"""NL-DSL-LLM bridge for Monag.

Reference implementation of the normative translation contract in
``docs/information/nl-dsl-llm.md``. The rule engine in ``monag.dsl`` stays
authoritative: it is consulted first and its result is returned unchanged.
Only when the rule engine cannot map the input and a provider command is
configured (``MONAG_LLM_COMMAND``) is a provider asked to emit exactly one
canonical ``OBSERVE ...`` line, which must validate through
``monag.dsl.parse_dsl`` before execution. No provider is contacted by
default.
"""
from datetime import datetime, timezone
import os
import shlex
import subprocess

from . import dsl

SCHEMA = 'monag.dsl-llm/v1'

DEFAULT_TIMEOUT_SECONDS = 10.0

SYSTEM_PROMPT = """You translate a user's observation request into the Monag DSL.

Grammar (exactly one line, conforming or nothing):
OBSERVE <domain> [HOURS <n>] [STATE <open|merged|all>] [LIMIT <n>] [UNPUSHED_ONLY] [WORKTREES_ONLY]
domain := prs | audit | status | resume | usage | catalog | advise

Domains: prs = pull requests and branches, audit = planfile/GitHub coverage,
status = agent processes and checkout snapshot, resume = worktree checkouts
and backlog, usage = agent CPU and account ledgers, catalog = declared
project metadata.

Rules:
- Answer with exactly one OBSERVE line and nothing else. No code fences.
- If the request does not map to any domain, answer exactly: OBSERVE none
- HOURS is a lookback window (default 24). STATE only applies to prs.

Examples:
"pokaż niescalone PR z ostatnich 10h" -> OBSERVE prs HOURS 10 STATE open
"co robiły agenci w ciągu 6 godzin?" -> OBSERVE status HOURS 6
"show merged pull requests" -> OBSERVE prs STATE merged
"what projects exist here" -> OBSERVE catalog
"""


def provenance(engine, dsl_line=None, raw_input=''):
    return {'engine': engine, 'dsl': dsl_line, 'raw_input': raw_input}


def extract_observe_line(answer):
    """Return the single OBSERVE line of a provider answer, or None.

    Strips code fences and prose per contract clause 3; more than one
    candidate line makes the translation invalid.
    """
    if not answer:
        return None
    candidates = [line.strip('` \t') for line in answer.splitlines()]
    candidates = [line for line in candidates
                  if line.upper().startswith('OBSERVE ')]
    if len(candidates) != 1:
        return None
    return candidates[0]


def run_provider(prompt, command, timeout=DEFAULT_TIMEOUT_SECONDS):
    """Run the configured provider command; return its stdout or None."""
    try:
        argv = shlex.split(command)
    except ValueError:
        return None
    if not argv:
        return None
    try:
        completed = subprocess.run(
            argv, input=prompt, capture_output=True, text=True, timeout=timeout,
            check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def resolve(text, command=None, timeout=None):
    """Resolve text to a Query per the translation contract.

    Returns ``(query, provenance)``; ``query`` is None when neither the rule
    engine nor a conforming provider translation produced a query.
    """
    raw = (text or '').strip()
    rule_query = dsl.parse(raw)
    if rule_query is not None:
        return rule_query, provenance('rule', rule_query.to_dsl(), raw)

    if raw.upper().startswith('OBSERVE'):
        return None, provenance('none', None, raw)

    if command is None:
        command = os.environ.get('MONAG_LLM_COMMAND', '')
    if timeout is None:
        timeout_raw = os.environ.get('MONAG_LLM_TIMEOUT', '')
        try:
            timeout = float(timeout_raw) if timeout_raw else DEFAULT_TIMEOUT_SECONDS
            if timeout <= 0:
                return None, provenance('none', None, raw)
        except ValueError:
            timeout = DEFAULT_TIMEOUT_SECONDS
    if not command:
        return None, provenance('none', None, raw)

    answer = run_provider(SYSTEM_PROMPT + '\nRequest: ' + raw, command, timeout)
    line = extract_observe_line(answer)
    if line is None or line.lower() == 'observe none':
        return None, dict(provenance('none', None, raw), attempted_engine='llm')
    query = dsl.parse_dsl(line)
    if query is None:
        return None, dict(provenance('none', None, raw), attempted_engine='llm')
    query.raw_input = raw
    return query, provenance('llm', query.to_dsl(), raw)


def execute(query_or_text, root, depth=2, pr_limit=200, issue_limit=200,
            registry=None, command=None, timeout=None):
    """Execute a query through the NL-DSL-LLM bridge.

    Mirrors ``monag.dsl.execute`` for string input, adding the contract's
    translation step and provenance reporting. Query objects pass through
    unchanged (engine ``rule``).
    """
    if isinstance(query_or_text, str):
        query, prov = resolve(query_or_text, command=command, timeout=timeout)
        if query is None:
            return {
                'schema': SCHEMA,
                'status': 'error',
                'error': f'Unrecognized query: {query_or_text}',
                'provenance': prov,
                'executed_at': datetime.now(timezone.utc).isoformat(),
            }
    else:
        query = query_or_text
        prov = provenance('rule', query.to_dsl(), query.raw_input)
    result = dsl.execute(query, root, depth=depth, pr_limit=pr_limit,
                         issue_limit=issue_limit, registry=registry)
    result['provenance'] = prov
    return result
