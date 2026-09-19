---
{
  "schema": "wellmanifest.docs/document/v1",
  "id": "nl-dsl-llm",
  "kind": "information",
  "version": 1,
  "title": "NL-DSL-LLM translation contract for Monag",
  "status": "accepted",
  "owner": "semcod/monag",
  "created": "2026-09-18",
  "updated": "2026-09-18",
  "review_after": "2026-10-16",
  "source_revision": "a582b1307072a7cad86b3fca11662d0a8debb81a",
  "affected_repositories": [
    "semcod/monag"
  ],
  "evidence": [
    "https://github.com/semcod/monag/pull/54"
  ]
}
---

# NL-DSL-LLM translation contract

<!-- docs:section purpose -->
## Purpose

Define the binding contract by which a large language model may extend the
rule-based natural-language front end of the Monag observation DSL
(`monag.dsl`, schema `monag.dsl/v1`). The contract is normative: any
implementation that does not satisfy a MUST clause below is non-conforming,
regardless of how useful its output appears.

<!-- docs:section scope -->
## Scope

The contract covers translation of a free-form Polish or English observation
request into exactly one canonical `OBSERVE ...` query, executed by the
existing read-only domain scanners. It does not cover generation of reports,
aggregation across statements, mutation of any state, or network observation
beyond what the rule engine already performs. The LLM is a translation aid
only; it never selects data sources beyond the six declared domains.

<!-- docs:section content -->
## Content

### 1. Resolution order

1. The rule engine (`monag.dsl.parse`) MUST be consulted first and its result
   returned unchanged when it resolves the input. This path MUST NOT spawn a
   subprocess or contact any provider (engine `rule`).
2. An LLM MUST be consulted only when the rule engine returns no query AND a
   provider command is configured (engine `llm`).
3. With no configured provider, behavior MUST be identical to the pre-LLM
   releases: an unmappable input yields an error result (engine `none`).

### 2. Provider protocol

- The provider command is read from the `MONAG_LLM_COMMAND` environment
  variable, split with `shlex`, and executed with the translation prompt on
  stdin. It MUST print its answer to stdout and exit zero.
- The invocation MUST time out; the default is 10 seconds and MAY be
  overridden with `MONAG_LLM_TIMEOUT` (seconds, `0` rejects every value).
- A non-zero exit, a timeout, or an unset command is a translation failure,
  never a query error by itself beyond the ordinary unrecognized-input error.
- The prompt MUST NOT contain secrets; only the user phrase and the fixed
  grammar below are transmitted.

### 3. Output contract

- The provider answer MUST contain exactly one line beginning with `OBSERVE `
  (case-insensitive). Code fences and surrounding prose MUST be stripped
  before extraction; if extraction yields more than one candidate line, the
  translation is invalid.
- `OBSERVE none` is the provider's explicit no-map answer and MUST be treated
  as a translation failure, not as a query.
- The extracted line MUST validate through `monag.dsl.parse_dsl`. Raw model
  output MUST NOT be executed, echoed into shell commands, or interpreted
  beyond that parse.

### 4. Grammar (monag.dsl/v1)

```
OBSERVE <domain> [HOURS <n>] [STATE <open|merged|all>] [LIMIT <n>] [UNPUSHED_ONLY] [WORKTREES_ONLY]
domain := prs | audit | status | resume | usage | catalog
```

The provider prompt MUST enumerate the domains and parameters and MUST
instruct the model to answer either with one grammar-conforming line or with
`OBSERVE none`.

### 5. Provenance and failure semantics

- Every result MUST carry `provenance.engine` in {`rule`, `llm`, `none`} and,
  for engine `llm`, the validated `provenance.dsl` line.
- Failures MUST be reported through the existing error envelope; the system
  MUST NOT retry providers, MUST NOT cache translations between processes, and
  MUST NOT fall back from a failed LLM translation to a guessed query.

### 6. Reference implementation

`src/monag/dsl_llm.py` implements this contract (`resolve`, `execute`).
`monag query`, `monag shell`, panel `/api/query` and the MCP `monag_query`
tool route through it; conformance tests live in `tests/test_dsl_llm.py`.

<!-- docs:section limitations -->
## Limitations

The contract applies only to translation into canonical queries for the six declared domains
(`prs`, `audit`, `status`, `resume`, `usage`, `catalog`). It does not mutate repository state
or access private network endpoints beyond the local execution boundary.

<!-- docs:section next_actions -->
## Next actions

Maintain integration with `semcod/algocode` for AST-level symbol inspection and duplicate
detection in query generation, and monitor provider timeouts in production.

<!-- docs:section evidence -->
## Evidence

Rule-first short-circuit, provider translation, fenced/multi-line/unparseable
rejection, timeout and disabled-by-default behavior are asserted by the unit
suite; `./project/governance-check.sh` gates the material delta.
