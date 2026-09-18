"""Natural Language Intent Parser and Query DSL for Monag.

Maps natural language statements (in Polish and English) and structured DSL commands
into unified observation queries across all Monag domains:
- `prs`: pull requests, unpushed branches, merge status
- `audit`: Planfile ticket coverage vs. GitHub Issues
- `status`: agent processes and checkout snapshot
- `resume`: worktree checkouts and Planfile backlog
- `usage`: agent CPU/process usage and api-budget ledgers
- `catalog`: declared project metadata and stacks

DSL syntax:
    OBSERVE <domain> [HOURS <n>] [STATE <open|merged|all>] [LIMIT <n>] [UNPUSHED_ONLY]
Example:
    OBSERVE prs STATE open HOURS 24
"""
from datetime import datetime, timezone
import re
from pathlib import Path

SCHEMA = 'monag.dsl/v1'

VALID_DOMAINS = {'prs', 'pr', 'audit', 'status', 'agents', 'resume', 'usage', 'catalog'}


class Query:
    """Structured representation of a Monag observation query."""

    def __init__(self, target, hours=24.0, state='all', limit=20, unpushed_only=False,
                 worktrees_only=False, raw_input=None):
        # Normalize target
        if target in {'pr', 'prs'}:
            self.target = 'prs'
        elif target in {'agents', 'status'}:
            self.target = 'status'
        else:
            self.target = target
        self.hours = float(hours) if hours is not None else 24.0
        self.state = state if state in {'open', 'merged', 'all'} else 'all'
        self.limit = int(limit) if limit is not None else 20
        self.unpushed_only = bool(unpushed_only)
        self.worktrees_only = bool(worktrees_only)
        self.raw_input = raw_input or ''

    def to_dsl(self):
        """Serialize query to canonical DSL string."""
        parts = [f'OBSERVE {self.target}']
        if self.hours != 24.0:
            parts.append(f'HOURS {self.hours:g}')
        if self.state != 'all':
            parts.append(f'STATE {self.state}')
        if self.limit != 20:
            parts.append(f'LIMIT {self.limit}')
        if self.unpushed_only:
            parts.append('UNPUSHED_ONLY')
        if self.worktrees_only:
            parts.append('WORKTREES_ONLY')
        return ' '.join(parts)

    def to_dict(self):
        return {
            'target': self.target,
            'hours': self.hours,
            'state': self.state,
            'limit': self.limit,
            'unpushed_only': self.unpushed_only,
            'worktrees_only': self.worktrees_only,
            'dsl': self.to_dsl(),
            'raw_input': self.raw_input,
        }

    def __repr__(self):
        return f'<Query {self.to_dsl()}>'


def parse_hours(text):
    """Extract hour duration from text (e.g. '24h', '10 godzin', 'last 2 hours')."""
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:h|godz(?:in[a-y]?)?|hours?)', text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def parse_dsl(text):
    """Parse canonical DSL format: OBSERVE <target> [KEY VALUE ...]."""
    tokens = text.strip().split()
    if not tokens:
        return None
    if tokens[0].upper() != 'OBSERVE' or len(tokens) < 2:
        return None

    target = tokens[1].lower()
    if target not in VALID_DOMAINS:
        return None

    kwargs = {'target': target, 'raw_input': text}
    i = 2
    while i < len(tokens):
        key = tokens[i].upper()
        if key == 'HOURS' and i + 1 < len(tokens):
            try:
                kwargs['hours'] = float(tokens[i + 1])
            except ValueError:
                pass
            i += 2
        elif key == 'STATE' and i + 1 < len(tokens):
            kwargs['state'] = tokens[i + 1].lower()
            i += 2
        elif key == 'LIMIT' and i + 1 < len(tokens):
            try:
                kwargs['limit'] = int(tokens[i + 1])
            except ValueError:
                pass
            i += 2
        elif key == 'UNPUSHED_ONLY':
            kwargs['unpushed_only'] = True
            i += 1
        elif key == 'WORKTREES_ONLY':
            kwargs['worktrees_only'] = True
            i += 1
        else:
            i += 1

    return Query(**kwargs)


def parse_natural_language(text):
    """Parse Polish or English natural language intent into a Query object."""
    raw = text.strip()
    low = raw.lower()

    hours = parse_hours(low)
    unpushed_only = bool(re.search(r'(tylko\s+ga[łl][ęe]zie|unpushed\s+only|nieprzepchni[ęe]t)', low))

    # Detect state
    state = 'all'
    if re.search(r'(niescalon|otwart|open|unmerged)', low):
        state = 'open'
    elif re.search(r'(scalon|zmergowan|merged)', low):
        state = 'merged'

    # Domain 1: PRs & branches
    if re.search(r'(\bprs?\b|\bpr-[a-z0-9]+\b|pull\s*requests?|ga[łl][ęe]z|branch|\bmerg|scal|nieprzepchni)', low):
        return Query('prs', hours=hours if hours is not None else 24.0,
                     state=state, unpushed_only=unpushed_only, raw_input=raw)

    # Domain 2: Audit & ticket coverage
    if re.search(r'(audit|audyt|pokryci|coverage|niezmapowan|untracked|drift|issues? vs|tickets? vs|issues? against|tickets? against)', low):
        worktrees_only = bool(re.search(r'(worktrees?\s*only|tylko\s*worktree)', low))
        return Query('audit', hours=hours if hours is not None else 24.0,
                     worktrees_only=worktrees_only, raw_input=raw)

    # Domain 3: Usage & account ledger
    if re.search(r'(usage|zu[żz]yci|token|bud[żz]et|ledger|konta|accounts?)', low):
        return Query('usage', hours=hours if hours is not None else 24.0, raw_input=raw)

    # Domain 4: Resume & worktrees
    if re.search(r'(resume|wznowi|worktrees?|backlog|lease)', low):
        return Query('resume', hours=hours if hours is not None else 24.0, raw_input=raw)

    # Domain 5: Catalog
    if re.search(r'(catalog|katalog|projekty|metadata|stack)', low):
        return Query('catalog', raw_input=raw)

    # Domain 6: Agents & status snapshot
    if re.search(r'(status|agent|proces|snapshot|co\s+robi|co\s+dzia[łl]a)', low):
        return Query('status', hours=hours if hours is not None else 24.0, raw_input=raw)

    # Default fallback: if query is simple command name
    words = low.split()
    if words and words[0] in VALID_DOMAINS:
        return Query(words[0], hours=hours if hours is not None else 24.0, state=state, raw_input=raw)

    return None


def parse(text):
    """Parse text as canonical DSL or natural language."""
    if not text or not text.strip():
        return None
    raw = text.strip()
    if raw.upper().startswith('OBSERVE '):
        dsl_query = parse_dsl(raw)
        if dsl_query:
            return dsl_query
    return parse_natural_language(raw)


def execute(query_or_text, root, depth=2, pr_limit=200, issue_limit=200, registry=None):
    """Execute query against underlying domain modules, returning data and markdown."""
    root = Path(root).expanduser().resolve()
    if isinstance(query_or_text, str):
        query = parse(query_or_text)
        if query is None:
            return {
                'schema': SCHEMA,
                'status': 'error',
                'error': f'Unrecognized query: {query_or_text}',
                'executed_at': datetime.now(timezone.utc).isoformat(),
            }
    else:
        query = query_or_text

    target = query.target
    data = None
    doc = ''

    if target == 'prs':
        from . import prs
        data = prs.scan(root, depth=depth, hours=query.hours, state=query.state,
                        pr_limit=pr_limit, unpushed_only=query.unpushed_only)
        doc = prs.markdown(data, limit=query.limit)

    elif target == 'audit':
        from . import audit
        data = audit.scan(root, depth=depth, issue_limit=issue_limit,
                          recent_hours=query.hours if query.hours != 24.0 else None,
                          worktrees_hours=query.hours,
                          worktrees_only=query.worktrees_only)
        doc = audit.markdown(data, limit=query.limit)

    elif target == 'status':
        from .monitor import snapshot
        from . import presentation
        cache = {}
        since = (datetime.now(timezone.utc)).isoformat()
        data = snapshot(root, root / '.monag_state', depth, since, False, cache,
                        registry or {}, False, False, False, False)
        doc = presentation.markdown(data, limit=query.limit)

    elif target == 'resume':
        from . import resume
        data = resume.scan(root, depth=depth)
        doc = resume.markdown(data, limit=query.limit, all_projects=True)

    elif target == 'usage':
        from . import usage
        data = usage.scan(root, registry=registry or {})
        doc = usage.markdown(data, limit=query.limit)

    elif target == 'catalog':
        from . import catalog
        data = catalog.scan(root, depth=depth)
        doc = catalog.markdown(data, limit=query.limit)

    return {
        'schema': SCHEMA,
        'status': 'ok',
        'query': query.to_dict(),
        'target': target,
        'executed_at': datetime.now(timezone.utc).isoformat(),
        'data': data,
        'markdown': doc,
    }
