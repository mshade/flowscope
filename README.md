# flowscope

Static analysis gate for GitHub Actions workflow permission scopes. Catches over-permissioned workflows at PR time, not after an incident.

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

---

## Deploying org-wide

The most effective deployment is as a [required workflow](https://docs.github.com/en/actions/sharing-automations/required-workflows) at the org level. Every repo in the org gets coverage automatically — no per-repo setup, no opt-out.

### Step 1 — Create the required workflow

In your org's central `.github` repo, create a reusable workflow:

```yaml
# .github/workflows/flowscope-gate.yml
name: Permission gate

on:
  pull_request:
    paths:
      - '.github/workflows/**'

jobs:
  flowscope:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@<sha>  # pin to a SHA

      - name: Get changed workflow files
        id: changed
        run: |
          git fetch origin ${{ github.base_ref }} --depth=1
          FILES=$(git diff --name-only origin/${{ github.base_ref }}...HEAD \
            -- '.github/workflows/*.yml' '.github/workflows/*.yaml')
          echo "files=$FILES" >> "$GITHUB_OUTPUT"

      - name: Analyze each changed workflow
        run: |
          while IFS= read -r workflow; do
            [ -z "$workflow" ] && continue
            echo "=== $workflow ==="
            EXCEPTIONS=".github/flowscope-exceptions.json"
            ARGS="workflow_file=$workflow"
            [ -f "$EXCEPTIONS" ] && ARGS="$ARGS exceptions_file=$EXCEPTIONS"
          done <<< "${{ steps.changed.outputs.files }}"

      - uses: mshade/flowscope@<sha>  # pin to a SHA
        with:
          workflow_file: ${{ matrix.workflow }}
          exceptions_file: .github/flowscope-exceptions.json
          create_exception_pr: "true"
```

Then configure it as a required workflow in **Organization Settings → Actions → Required workflows**.

### Step 1b — Restrict which actions developers can use

Flowscope gates permissions on workflows that exist, but it cannot prevent a developer from adding a malicious or unvetted action before the PR is reviewed. GitHub's **Actions allowlist** closes this gap.

In **Organization Settings → Actions → General**, set the allowed actions policy to one of:

- **Allow select actions** — explicitly list approved actions and patterns. Developers cannot use anything outside the list regardless of what they put in a workflow file.
- **Allow actions created by GitHub** — permits only GitHub-owned actions; blocks all third-party and marketplace actions.

A practical middle ground for most orgs:

```
# Allow GitHub's own actions
actions/*

# Allow internally published actions from your org
your-org/*

# Explicitly allow vetted third-party actions (pin to SHA in workflows)
astral-sh/setup-uv@*
mshade/flowscope@*
```

The allowlist is enforced by the GitHub Actions runner before any workflow code executes — a workflow referencing a non-allowlisted action will fail to start, not just fail a lint check. Combined with flowscope (which checks permissions on allowed workflows) and CODEOWNERS (which gates exception approval), the three controls form a layered defense:

| Control | What it prevents |
|---------|-----------------|
| Actions allowlist | Arbitrary third-party code executing in your runners |
| flowscope | Excessive token scope on approved workflows |
| CODEOWNERS on exceptions file | Self-approved permission escalation |

### Step 2 — Protect the exceptions file with CODEOWNERS

In each consuming repo (or via a default CODEOWNERS in the `.github` repo), require security team review on the exceptions file:

```
# .github/CODEOWNERS
.github/flowscope-exceptions.json @your-org/security-team
```

Combined with a [branch protection rule](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches) requiring CODEOWNERS review, this means:

- Developers cannot self-approve an exception
- Merging an exception entry = security team has explicitly signed off
- The git history of the exceptions file is a full audit trail

### Step 3 — Enable automatic exception PRs

Set `create_exception_pr: "true"` on the action (requires `contents: write` and `pull-requests: write` on the calling workflow). When flowscope blocks a PR, it automatically:

1. Creates a branch `flowscope/exception-<workflow-stem>`
2. Scaffolds `.github/flowscope-exceptions.json` with the blocked scopes pre-filled
3. Opens a draft PR and comments on the original PR with a link
4. The developer fills in `justification` and confirms `expires_at`, then marks it ready for review
5. Security team reviews via CODEOWNERS requirement and merges
6. The exception is active immediately on merge — no further action required

This eliminates the friction of finding the right file format and opening a PR manually; developers get a one-click path to the approval queue.

---

## Using it in a single repo

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
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@<sha>  # pin to a SHA
      - uses: mshade/flowscope@<sha>  # pin to a SHA
        with:
          workflow_file: .github/workflows/deploy.yml
```

### Analyzing all changed workflow files

```yaml
name: Permission gate

on:
  pull_request:
    paths:
      - '.github/workflows/**'

jobs:
  flowscope:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@<sha>

      - name: Get changed workflow files
        id: changed
        run: |
          git fetch origin ${{ github.base_ref }} --depth=1
          git diff --name-only origin/${{ github.base_ref }}...HEAD \
            -- '.github/workflows/*.yml' \
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
      - uses: mshade/flowscope@<sha>
        with:
          workflow_file: .github/workflows/deploy.yml
          exceptions_file: .github/flowscope-exceptions.json
```

`flowscope-exceptions.json` format:

```json
[
  {
    "scope": "contents",
    "justification": "Deploy job pushes a release tag — write access is required",
    "approved_by": "security-team",
    "expires_at": "2027-01-01",
    "workflow": ".github/workflows/deploy.yml",
    "job_id": "release"
  }
]
```

Each exception is scoped to a `(scope, workflow)` pair so an approval for one workflow does not silently suppress violations in other workflows. Omit `workflow` to create a repo-wide grant. Exceptions expire automatically on `expires_at` — an expired exception is treated as if it does not exist.

### Consuming the check result downstream

The action exposes a `result` output containing the full JSON check result:

```yaml
      - uses: mshade/flowscope@<sha>
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

---

## Running locally

```bash
# Install
uv sync --extra dev

# Analyze a workflow file
uv run flowscope path/to/workflow.yml

# With an exceptions file
uv run flowscope path/to/workflow.yml --exceptions .github/flowscope-exceptions.json

# Scan all workflows in a GitHub repo (requires gh CLI)
task scan -- https://github.com/your-org/your-repo

# Exit code: 0 = passed, 1 = violation found
```

---

## Development

```bash
task test       # run the full test suite
task lint       # ruff check
task fmt        # ruff format (modifies files)
task check      # lint + format check + test
```

Tests use YAML fixture files in `tests/fixtures/` that cover each violation case. When adding a new policy rule, add a corresponding fixture and test in `tests/test_policy.py`. The four existing rules in `src/flowscope/policy.py` serve as a template.

To add support for a new agentic action, add its name (without `@ref`) to `AGENTIC_ACTIONS` in `src/flowscope/policy.py`:

```python
AGENTIC_ACTIONS: set[str] = {
    "anthropics/claude-code-action",
    "your-org/your-agentic-action",  # add here
}
```

---

## Background

Flowscope is Component 1 (the enforcement plane) of a three-plane Workflow Permission Governance System:

- **Enforcement plane** ← *this tool*: PR gate, static analysis, policy-driven check results
- **Policy plane** (planned): per-workflow permission baselines, exception registry, policy rules
- **Observation plane** (planned): runner hooks that record actual runtime token usage to build baselines

The static analysis gate is intentionally conservative where no runtime baseline exists. When the observation plane is deployed and baselines are established, the gate uses them to calibrate — warning only on scopes that exceed observed usage rather than blocking all declared write scopes. This matters most for existing repos: the observation plane generates baseline data from every workflow execution, not just ones under active modification, which surfaces overprovisioning in workflows that predate flowscope adoption.
