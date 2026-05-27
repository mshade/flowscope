# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install / sync dependencies (includes ruff, pytest)
uv sync --extra dev

# Run all tests
task test                        # or: uv run pytest tests/ -v

# Lint and format
task lint                        # ruff check
task fmt                         # ruff format (modifies files)
task fmt:check                   # ruff format --check (read-only)
task check                       # lint + fmt:check + test

# Run the CLI against a workflow file
uv run flowscope path/to/workflow.yml

# With optional baseline and exceptions files
uv run flowscope path/to/workflow.yml --baseline baseline.json --exceptions exceptions.json

# Scan all workflows in a GitHub repo (requires gh CLI + auth)
task scan -- https://github.com/owner/repo

# Scan specific workflow files in a GitHub repo
task scan -- https://github.com/owner/repo .github/workflows/build.yml .github/workflows/deploy.yml
```

## Architecture

Flowscope is a static analysis gate for GitHub Actions workflow permission scopes. It is Component 1 of a larger three-plane governance system; the observation plane (runtime runner hooks) and policy plane (baseline store) are designed but not yet built.

**Data flow:**

```
workflow.yml → parser.py → WorkflowPermissions
                                  ↓
                           policy.py (+ raw_doc, baseline, exceptions)
                                  ↓
                            list[Violation]
                                  ↓
                           analyzer.py → CheckResult
                                  ↓
                             cli.py → JSON stdout + exit code
```

**Two-level permission model** (`models.py`): GitHub Actions permissions operate at workflow-level and job-level; job-level overrides workflow-level for that job. `WorkflowPermissions` holds the workflow-level scope map plus a `jobs` dict of `JobPermissions`. The special cases `write_all` and `implicit_full_access` are flags rather than scope entries because they collapse all scope detail.

**`parser.py`** loads YAML with `ruamel.yaml` (comment-preserving, for future advisory checks) and populates the model. Only jobs with an explicit non-empty `permissions` block get a `JobPermissions` entry.

**`policy.py`** (`evaluate_policy`) implements four rules in order:

| Rule | Condition | Tier |
|------|-----------|------|
| 1 | `permissions: write-all` | HARD_BLOCK (returns immediately) |
| 2 | `permissions: {}` (implicit full access) | HARD_BLOCK (returns immediately) |
| 3 | Workflow-level write scope with any unscoped job | HARD_BLOCK |
| 4 | Job uses a known agentic action + write scope + no observed baseline | REQUIRES_REVIEW |

Rules 1 and 2 return early — there's nothing meaningful to say about job scoping when the workflow is already maximally permissioned. Rule 4 is blind when `raw_doc=None` (no step data available). `AGENTIC_ACTIONS` in `policy.py` is the registry of known agentic action names (currently `anthropics/claude-code-action`).

**Exception suppression**: `evaluate_policy` accepts an `exceptions` list (dicts with `scope`, `expires_at`, and optional `workflow`). An active exception must not be expired; a `workflow` field scopes it to a specific workflow file; omitting `workflow` makes it a repo-wide grant.

**`analyzer.py`** loads the YAML once, passes the raw doc to both the parser and the policy evaluator, and returns a `CheckResult`. The `passed` field is `False` if any `HARD_BLOCK` violation exists.

**GitHub Action**: `action.yml` defines a composite action that installs the package and runs `entrypoint.sh`. The entrypoint captures CLI output, writes it to `$GITHUB_OUTPUT` as a multiline `result` value, then exits with the CLI's exit code — ensuring the output is written even when violations are found (exit 1).

## Violation tiers

- `HARD_BLOCK` — fails the check; resolved by fixing the workflow or registering a formal exception
- `REQUIRES_REVIEW` — fails the check; resolved by explicit human sign-off (no code change or exception entry required)
- `WARNING` — does not fail the check, surfaces in annotations
- `ADVISORY` — not yet implemented; planned for write scopes with no inline justification comment

## Extending policy rules

Add new rules to `evaluate_policy` in `policy.py`. Each rule appends `Violation` objects to the `violations` list. The `raw_doc` parameter is the raw ruamel.yaml-parsed document and is needed for any rule that inspects job steps or job names beyond what the parsed model exposes. To add a new agentic action, add its name (without `@ref`) to `AGENTIC_ACTIONS`.
