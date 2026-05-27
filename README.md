# flowscope

Static analysis gate for GitHub Actions workflow permission scopes. Catches over-permissioned workflows at PR time, not after an incident.

Flowscope is the enforcement plane of a larger [Workflow Permission Governance System](docs/architecture.md). It parses declared permission scopes, evaluates them against a tiered policy, and emits structured check results. Deployed as a GitHub Action — typically as an org-level required workflow so coverage is automatic across every repo.

## What it catches

| Violation | Tier | Behavior |
|-----------|------|----------|
| `permissions: write-all` | Hard block | Fails the check |
| `permissions: {}` (implicit full access) | Hard block | Fails the check |
| Workflow-level write scope with any unscoped job | Hard block | Fails the check |
| `pull_request_target` trigger + any write scope | Hard block | Fails the check (fork-PR-poisoning vector) |
| Agentic action (e.g. `claude-code-action`) with write scope and no observed baseline | Requires review | Non-blocking annotation |
| `workflow_run` trigger + any write scope | Requires review | Non-blocking annotation |
| High-risk scope (`actions`, `id-token`, `packages`, `attestations`) without inline justification | Advisory | Soft notice; suppressed by `# flowscope:reason: <why>` on the scope line |

**Tier resolution paths:**

- **Hard block** — fix the workflow or register an exception in `.github/flowscope-exceptions.json` (security team approves via CODEOWNERS).
- **Requires review** — recorded by the CODEOWNERS-routed PR approval on agentic/high-risk workflow file patterns. *This tier assumes the deployment-level CODEOWNERS controls are in place* (see [Step 4](#step-4--route-workflow-and-exception-changes-through-codeowners)); without them, REQUIRES_REVIEW is an unblocked annotation. flowscope's role is to point the reviewer at the specific risk pattern within a diff CODEOWNERS already routed to them.
- **Advisory** — inline `# flowscope:reason: <why>` comment on the scope line, or remove the scope.
- **Warning** — defined but currently unemitted; reserved for observation-plane signals (declared scope exceeds observed runtime usage).

**Context matters.** Not every write scope is equally dangerous. `pull_request_target` runs in the base-repo context with secrets but fires on fork PRs — if the workflow checks out the PR HEAD, attacker code executes with write access (Rules 5, 6 catch this trigger family). Among scopes themselves, `actions: write` cannot modify workflow files (locked behind the `workflow` PAT scope) but can delete logs (anti-forensics), disable workflows (turn off security gates), and manipulate caches; `id-token: write` mints OIDC tokens for cloud IAM role assumption — both deserve inline justification (Rule 7).

---

## Deploying org-wide

Most effective deployment is as a [required workflow](https://docs.github.com/en/actions/sharing-automations/required-workflows) at the org level. Every repo gets coverage automatically, no opt-out.

Flowscope assumes three platform-level controls (see [Deployment Assumptions](docs/architecture.md#deployment-assumptions)): self-hosted runners for token-level audit, org-mandated required workflows so coverage cannot be bypassed, and org-level CODEOWNERS routing workflow changes to the right reviewers.

### Step 1 — Create the required workflow

In your org's central `.github` repo:

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
      - name: Install flowscope
        run: pip install "git+https://github.com/mshade/flowscope.git" --quiet

      - name: Scan changed workflow files
        run: |
          git fetch origin "$GITHUB_BASE_REF" --depth=1
          git diff --name-only "origin/$GITHUB_BASE_REF...HEAD" \
            -- '.github/workflows/*.yml' '.github/workflows/*.yaml' \
            | while IFS= read -r workflow; do
                [ -z "$workflow" ] && continue
                echo "=== $workflow ==="
                ARGS=("$workflow")
                [ -f .github/flowscope-exceptions.json ] \
                  && ARGS+=(--exceptions .github/flowscope-exceptions.json)
                flowscope "${ARGS[@]}"
              done
```

Configure it as a required workflow in **Organization Settings → Actions → Required workflows**.

### Step 2 — Restrict which actions developers can use

flowscope gates permissions on workflows that exist; it cannot prevent a developer adding a malicious or unvetted action. GitHub's **Actions allowlist** (**Organization Settings → Actions → General**) closes that gap by refusing to run actions outside an approved list. The runner enforces it before workflow code executes.

A practical allowlist:

```
actions/*                # GitHub's own actions
your-org/*               # Your org's internally published actions
astral-sh/setup-uv@*     # Vetted third-party — pin to SHA in workflows
mshade/flowscope@*
```

The combined layered defense:

| Control | What it prevents |
|---------|-----------------|
| Actions allowlist | Arbitrary third-party code executing in runners |
| flowscope | Excessive token scope on approved workflows |
| CODEOWNERS routing (workflow files + exceptions file) | Unreviewed workflow changes; self-approved permission escalation |
| Self-hosted runners | Opaque runtime; enables full token audit and observation plane |

### Step 3 — Migrate to self-hosted runners

GitHub-hosted runners are opaque: workflow-level logs only, no visibility into what `GITHUB_TOKEN` called at the network layer. Self-hosted runners enable:

- **Network egress control** — route runner traffic through a proxy/firewall; token API calls become observable.
- **Observation plane hooks** — the planned post-job hook that records actual scope usage runs on runners you control.
- **Audit telemetry** — every job start, action execution, and token use flows to your SIEM.
- **Ephemeral isolation** — via [actions-runner-controller](https://github.com/actions/actions-runner-controller).

Use runner groups to migrate incrementally: scope a group to high-risk repos first, expand as workflows validate, then set the group as the org default.

### Step 4 — Route workflow and exception changes through CODEOWNERS

CODEOWNERS provides the human audit layer on top of static analysis — and is what makes REQUIRES_REVIEW act as a gate rather than just an annotation. Configure at the org level (via `.github`) so it applies to every repo, and explicitly control:

| Path | Reviewer | Why |
|------|----------|-----|
| `.github/CODEOWNERS` | platform + security | Routing itself must not be self-modifiable |
| `.github/workflows/**` | platform team | All workflow changes get a human reviewer |
| `.github/actions/**`, `action.yml`, `action.yaml` | platform team | Composite/local actions execute in the same trust context |
| `.github/workflows/*deploy*.yml`, `*release*.yml` | security team | Most powerful tokens; escalate via specific patterns (last match wins) |
| `.github/workflows/*claude*.yml`, `*agent*.yml`, `*ai*.yml` | security team | Highest-risk category — always security review |
| `.github/flowscope-exceptions.json` | security team | Permission exceptions are explicit security-team decisions |

Combined with a [branch protection rule](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches) requiring CODEOWNERS review: routing cannot be changed without sign-off, high-risk workflows escalate automatically, exceptions cannot be self-approved, and git history of every controlled path becomes the audit trail.

### Step 5 — Enable automatic exception PRs

Set `create_exception_pr: "true"` on the action (requires `contents: write` and `pull-requests: write`). When flowscope blocks a PR, it automatically:

1. Creates branch `flowscope/exception-<workflow-stem>` (deterministic — re-pushes are idempotent)
2. Scaffolds `.github/flowscope-exceptions.json` with the blocked scopes pre-filled
3. Opens a draft PR and comments on the original PR with the link
4. Developer fills `justification` and confirms `expires_at`, marks ready for review
5. Security team approves via CODEOWNERS, merges — exception is active immediately

Removes the friction of finding the right file format and opening a PR manually.

### Step 6 — Gradual rollout with `--warn-only`

Before flipping enforcement on, deploy in audit mode. `warn_only: "true"` exits 0 regardless of violations; the step summary marks them as "would have failed":

```yaml
      - uses: mshade/flowscope@<sha>
        with:
          workflow_file: ${{ env.WORKFLOW }}
          warn_only: "true"
          registry_url: ${{ secrets.FLOWSCOPE_REGISTRY_URL }}
```

`registry_url` (or env var `FLOWSCOPE_REGISTRY_URL`) POSTs the violations JSON to a central endpoint when violations are found — the integration point for the policy plane. Best-effort, never fails the check.

Typical rollout: deploy warn-only org-wide → review the registry feed → fix or register exceptions for the common patterns → flip warn-only off for low-risk repo groups first → expand to default-blocking.

---

## Using it in a single repo

Drop into `.github/workflows/permission-gate.yml`:

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
      - uses: mshade/flowscope@<sha>
        with:
          workflow_file: .github/workflows/deploy.yml
          exceptions_file: .github/flowscope-exceptions.json
```

### Exceptions file

`.github/flowscope-exceptions.json`:

```json
[
  {
    "scope": "contents",
    "justification": "Deploy job pushes a release tag — write access required",
    "approved_by": "security-team",
    "expires_at": "2027-01-01",
    "workflow": ".github/workflows/deploy.yml",
    "job_id": "release"
  }
]
```

Each exception is scoped to a `(scope, workflow)` pair — an approval for one workflow does not silently suppress violations in another. Omit `workflow` for a repo-wide grant. Exceptions expire automatically on `expires_at`.

### Consuming the check result

The action exposes a `result` output with the full JSON check result:

```yaml
      - uses: mshade/flowscope@<sha>
        id: gate
        with:
          workflow_file: .github/workflows/deploy.yml
      - if: always()
        run: echo '${{ steps.gate.outputs.result }}' | jq .
```

---

## Running locally

```bash
uv sync --extra dev

uv run flowscope path/to/workflow.yml
uv run flowscope path/to/workflow.yml --exceptions .github/flowscope-exceptions.json
uv run flowscope path/to/workflow.yml --warn-only

# Scan all workflows in a GitHub repo (requires gh CLI)
task scan -- https://github.com/your-org/your-repo
```

Exit code: `0` = passed or `--warn-only`, `1` = hard-block found.

---

## Development

```bash
task test       # pytest
task lint       # ruff check
task fmt        # ruff format
task check      # lint + format check + test
```

New policy rules go in `src/flowscope/policy.py` with a fixture in `tests/fixtures/` and tests in `tests/test_policy.py`. To register a new agentic action, add it to `AGENTIC_ACTIONS`; for a new high-risk scope, add it to `HIGH_RISK_SCOPES` with a one-line rationale.

---

## Background

Flowscope is the enforcement plane of a three-plane Workflow Permission Governance System. The architecture, including the planned **observation plane** (runner hooks recording actual token usage) and **policy plane** (baseline store + exception registry with audit trail), is in [`docs/architecture.md`](docs/architecture.md).

The static analysis gate is intentionally conservative where no runtime baseline exists. With the observation plane deployed, the gate calibrates against actual usage — warning when declared scope exceeds observed need. This is most valuable for existing repos: the observation plane sees every workflow execution, not just changes under PR review, surfacing pre-existing overprovisioning that a PR gate can never catch.
