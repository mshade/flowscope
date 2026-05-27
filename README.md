# flowscope

Static analysis gate for GitHub Actions workflow permission scopes. Catches over-permissioned tokens before they land — at PR time, not after an incident.

Flowscope is the enforcement plane of a larger [Workflow Permission Governance System](#background). It parses declared permission scopes in workflow YAML, evaluates them against a tiered violation policy, and emits structured check results. It runs as a GitHub Action and can be wired into a required org-level workflow so coverage is automatic across every repo.

## What it catches

| Violation | Tier | Behavior |
|-----------|------|----------|
| `permissions: write-all` | Hard block | Fails the check |
| `permissions: {}` (implicit full access) | Hard block | Fails the check |
| Workflow-level write scope with any unscoped job | Hard block | Fails the check |
| Agentic action (e.g. `claude-code-action`) with write scope and no observed baseline | Requires review | Fails the check; cleared by human approval |

**Hard block** is resolved by fixing the workflow or registering a formal exception. **Requires review** is resolved by explicit sign-off from a security or platform team reviewer — no code change or exception entry required, just a conscious human acknowledgment of the risk. This distinction matters for agentic workloads where the right answer is often "yes, this needs write access" but someone should verify that before it merges.

**Hard block** and **requires review** both fail the check. **Warning** surfaces in annotations but does not block.

A job is considered "scoped" when it has an explicit `permissions:` block. A workflow-level write scope is only acceptable when every job declares its own permissions block — otherwise that write scope silently applies to jobs that may not need it.

## Using it in a workflow

### Basic usage

Analyze a single workflow file:

```yaml
name: Permission gate

on:
  pull_request:
    paths:
      - '.github/workflows/**'

jobs:
  flowscope:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: your-org/flowscope@main
        with:
          workflow_file: ${{ github.workspace }}/.github/workflows/deploy.yml
```

### Analyzing all changed workflow files

To gate on every workflow file touched by a PR:

```yaml
name: Permission gate

on:
  pull_request:
    paths:
      - '.github/workflows/**'

jobs:
  flowscope:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Get changed workflow files
        id: changed
        run: |
          git fetch origin ${{ github.base_ref }} --depth=1
          git diff --name-only origin/${{ github.base_ref }}...HEAD -- '.github/workflows/*.yml' \
            | tee changed_workflows.txt

      - name: Analyze each changed workflow
        run: |
          while IFS= read -r workflow; do
            echo "=== $workflow ==="
            uv run flowscope "$workflow"
          done < changed_workflows.txt
```

### With an exceptions file

Teams with legitimate broad permission requirements can register a scoped exception. Pass a JSON file to suppress specific violations:

```yaml
      - uses: your-org/flowscope@main
        with:
          workflow_file: .github/workflows/deploy.yml
          exceptions_file: .github/flowscope-exceptions.json
```

`flowscope-exceptions.json` format:

```json
[
  {
    "scope": "write-all",
    "justification": "Legacy deploy job requires full token until migration is complete",
    "approved_by": "platform-team",
    "expires_at": "2026-12-31",
    "status": "active"
  }
]
```

Exceptions are only honored when `status` is `"active"` and `expires_at` has not passed.

### Consuming the check result downstream

The action exposes a `result` output containing the full JSON check result, available to subsequent steps:

```yaml
      - uses: your-org/flowscope@main
        id: gate
        with:
          workflow_file: .github/workflows/deploy.yml

      - name: Post summary
        if: always()
        run: echo '${{ steps.gate.outputs.result }}' | jq .
```

The result schema:

```json
{
  "workflow_path": ".github/workflows/deploy.yml",
  "passed": false,
  "violations": [
    {
      "tier": "hard_block",
      "file_path": ".github/workflows/deploy.yml",
      "line": null,
      "scope": "write-all",
      "job_id": null,
      "message": "permissions: write-all grants full token access",
      "remediation": "Replace with explicit per-job permission blocks..."
    }
  ]
}
```

## Running locally

```bash
# Install
uv sync --extra dev

# Analyze a workflow file
uv run flowscope path/to/workflow.yml

# With exceptions
uv run flowscope path/to/workflow.yml --exceptions exceptions.json

# Exit code: 0 = passed, 1 = hard block violation found
```

## Development

```bash
# Run the full test suite
uv run pytest tests/ -v

# Run a single test
uv run pytest tests/test_policy.py::test_write_all_is_hard_block -v
```

Tests use YAML fixture files in `tests/fixtures/` that cover each violation case. When adding a new policy rule, add a corresponding fixture and tests in `tests/test_policy.py`. The four existing rules in `src/flowscope/policy.py` are well-commented and serve as a template.

To add support for a new agentic action, add its name (without `@ref`) to `AGENTIC_ACTIONS` in `src/flowscope/policy.py`:

```python
AGENTIC_ACTIONS: set[str] = {
    "anthropics/claude-code-action",
    "your-org/your-agentic-action",  # add here
}
```

## Background

Flowscope is Component 1 (the enforcement plane) of a three-plane Workflow Permission Governance System:

- **Enforcement plane** ← *this tool*: PR gate, static analysis, policy-driven check results
- **Policy plane** (planned): per-workflow permission baselines, exception registry, policy rules
- **Observation plane** (planned): runner hooks and API proxy that record actual runtime permission usage to build baselines

The static analysis gate is intentionally conservative where no runtime baseline exists. When the observation plane is deployed and baselines are established, the gate uses them to calibrate — warning only on scopes that exceed observed usage rather than all declared write scopes.
