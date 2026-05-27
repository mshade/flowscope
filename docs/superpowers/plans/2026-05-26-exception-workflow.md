# Exception Request Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When flowscope blocks a workflow, automatically create a draft exception-request PR in the consuming repo with a pre-populated skeleton, and post a link back on the original blocked PR.

**Architecture:** Four independent layers of change — policy engine (drop status, add workflow scoping), new exception scaffold Python module, updated action.yml input, updated entrypoint.sh shell logic. Tasks are ordered so each builds on tested prior work.

**Tech Stack:** Python 3.11+, pytest, ruamel.yaml (existing), bash, `gh` CLI (pre-installed on GitHub-hosted runners), `git`.

---

## File Map

| Action | Path |
|---|---|
| Modify | `src/flowscope/policy.py` |
| Modify | `tests/test_policy.py` |
| Create | `src/flowscope/exception.py` |
| Create | `tests/test_exception_scaffold.py` |
| Modify | `action.yml` |
| Modify | `entrypoint.sh` |

---

### Task 1: Policy engine — drop `status`, add workflow-scoped exception matching

**Files:**
- Modify: `src/flowscope/policy.py`
- Modify: `tests/test_policy.py`

The policy engine currently requires `status: "active"` on every exception entry and matches exceptions only on `scope`. This task removes the status gate and adds optional workflow-path scoping: an exception with a `workflow` field only suppresses violations in that specific workflow file; one without `workflow` is a repo-wide grant (backwards compat).

- [ ] **Step 1: Write failing tests for workflow-scoped exception matching**

Add to `tests/test_policy.py`:

```python
def test_exception_without_workflow_field_suppresses_any_workflow():
    from datetime import date
    perms = parse_workflow(FIXTURES / "write_all.yml")
    exceptions = [
        {
            "scope": "write-all",
            "justification": "Repo-wide grant",
            "approved_by": "platform-team",
            "expires_at": str(date(2099, 1, 1)),
        }
    ]
    violations = evaluate_policy(perms, "any-workflow.yml", raw_doc=None, exceptions=exceptions)
    assert not any(v.tier == ViolationTier.HARD_BLOCK for v in violations)


def test_exception_with_matching_workflow_suppresses():
    from datetime import date
    perms = parse_workflow(FIXTURES / "write_all.yml")
    exceptions = [
        {
            "scope": "write-all",
            "justification": "Deploy needs full token",
            "approved_by": "platform-team",
            "expires_at": str(date(2099, 1, 1)),
            "workflow": ".github/workflows/deploy.yml",
        }
    ]
    violations = evaluate_policy(
        perms, ".github/workflows/deploy.yml", raw_doc=None, exceptions=exceptions
    )
    assert not any(v.tier == ViolationTier.HARD_BLOCK for v in violations)


def test_exception_with_nonmatching_workflow_does_not_suppress():
    from datetime import date
    perms = parse_workflow(FIXTURES / "write_all.yml")
    exceptions = [
        {
            "scope": "write-all",
            "justification": "Deploy needs full token",
            "approved_by": "platform-team",
            "expires_at": str(date(2099, 1, 1)),
            "workflow": ".github/workflows/deploy.yml",
        }
    ]
    violations = evaluate_policy(
        perms, ".github/workflows/release.yml", raw_doc=None, exceptions=exceptions
    )
    assert any(v.tier == ViolationTier.HARD_BLOCK for v in violations)
```

- [ ] **Step 2: Run new tests to confirm they fail**

```bash
uv run pytest tests/test_policy.py::test_exception_without_workflow_field_suppresses_any_workflow tests/test_policy.py::test_exception_with_matching_workflow_suppresses tests/test_policy.py::test_exception_with_nonmatching_workflow_does_not_suppress -v
```

Expected: the first test passes (no workflow field = repo-wide, already works by coincidence), the latter two fail because `_scope_is_excepted` doesn't check `workflow` yet.

- [ ] **Step 3: Update `_is_exception_active` in `src/flowscope/policy.py` — drop `status` check**

Replace:

```python
def _is_exception_active(exc: dict[str, Any]) -> bool:
    if exc.get("status") != "active":
        return False
    try:
        expires = date.fromisoformat(str(exc["expires_at"]))
    except (KeyError, ValueError):
        return False
    return expires >= date.today()
```

With:

```python
def _is_exception_active(exc: dict[str, Any]) -> bool:
    try:
        expires = date.fromisoformat(str(exc["expires_at"]))
    except (KeyError, ValueError):
        return False
    return expires >= date.today()
```

- [ ] **Step 4: Update `_scope_is_excepted` to accept and check `workflow_path`**

Replace:

```python
def _scope_is_excepted(scope: str, exceptions: list[dict]) -> bool:
    return any(
        exc.get("scope") == scope and _is_exception_active(exc)
        for exc in exceptions
    )
```

With:

```python
def _scope_is_excepted(scope: str, exceptions: list[dict], workflow_path: str = "") -> bool:
    return any(
        exc.get("scope") == scope
        and _is_exception_active(exc)
        and (not exc.get("workflow") or exc.get("workflow") == workflow_path)
        for exc in exceptions
    )
```

- [ ] **Step 5: Pass `workflow_path` at all three `_scope_is_excepted` call sites in `evaluate_policy`**

In `src/flowscope/policy.py`, find the three calls to `_scope_is_excepted` (Rules 1, 2, 3) and add `workflow_path=workflow_path` to each:

```python
# Rule 1
if not _scope_is_excepted(_WRITE_ALL_SCOPE, exceptions, workflow_path=workflow_path):

# Rule 2
if not _scope_is_excepted(_IMPLICIT_FULL_SCOPE, exceptions, workflow_path=workflow_path):

# Rule 3 (inside the for-scope loop)
if not _scope_is_excepted(scope, exceptions, workflow_path=workflow_path):
```

- [ ] **Step 6: Run the new tests — all three should now pass**

```bash
uv run pytest tests/test_policy.py::test_exception_without_workflow_field_suppresses_any_workflow tests/test_policy.py::test_exception_with_matching_workflow_suppresses tests/test_policy.py::test_exception_with_nonmatching_workflow_does_not_suppress -v
```

Expected: PASS PASS PASS

- [ ] **Step 7: Remove `status` from existing exception fixtures in `tests/test_policy.py`**

In `test_registered_exception_suppresses_hard_block`, remove the `"status": "active"` line from the exception dict. In `test_expired_exception_does_not_suppress`, remove `"status": "active"` from its exception dict. Both tests should still pass — expiry is the only gate now.

- [ ] **Step 8: Run the full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add src/flowscope/policy.py tests/test_policy.py
git commit -m "feat: drop status field, add workflow-scoped exception matching"
```

---

### Task 2: Exception scaffold module

**Files:**
- Create: `src/flowscope/exception.py`
- Create: `tests/test_exception_scaffold.py`
- Modify: `pyproject.toml` (add script entry)

Reads the JSON output from the main CLI (via stdin), generates one exception entry per violation that has a `scope`, merges into `.github/flowscope-exceptions.json` without clobbering existing entries.

- [ ] **Step 1: Write failing tests**

Create `tests/test_exception_scaffold.py`:

```python
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from flowscope.exception import scaffold


def test_scaffold_creates_entry_per_scoped_violation(tmp_path):
    violations_json = {
        "workflow_path": ".github/workflows/deploy.yml",
        "passed": False,
        "violations": [
            {
                "tier": "HARD_BLOCK",
                "scope": "contents:write",
                "job_id": "deploy",
                "message": "...",
                "remediation": "...",
                "file_path": ".github/workflows/deploy.yml",
                "line": None,
            }
        ],
    }
    output = tmp_path / "flowscope-exceptions.json"
    scaffold(violations_json, ".github/workflows/deploy.yml", output)

    entries = json.loads(output.read_text())
    assert len(entries) == 1
    entry = entries[0]
    assert entry["scope"] == "contents:write"
    assert entry["workflow"] == ".github/workflows/deploy.yml"
    assert entry["job_id"] == "deploy"
    assert entry["justification"] == "TODO: describe why this exception is needed"
    assert entry["approved_by"] == ""
    assert "status" not in entry


def test_scaffold_expires_90_days_out(tmp_path):
    violations_json = {
        "violations": [
            {
                "scope": "contents:write",
                "job_id": None,
                "tier": "HARD_BLOCK",
                "message": "",
                "remediation": "",
                "file_path": "x.yml",
                "line": None,
            }
        ]
    }
    output = tmp_path / "exceptions.json"
    scaffold(violations_json, "x.yml", output)

    entries = json.loads(output.read_text())
    expected = str(date.today() + timedelta(days=90))
    assert entries[0]["expires_at"] == expected


def test_scaffold_merges_without_clobbering_existing(tmp_path):
    existing = [
        {
            "scope": "contents:write",
            "justification": "Already approved",
            "approved_by": "security-team",
            "expires_at": "2099-01-01",
            "workflow": ".github/workflows/deploy.yml",
            "job_id": "build",
        }
    ]
    output = tmp_path / "exceptions.json"
    output.write_text(json.dumps(existing))

    violations_json = {
        "violations": [
            {
                "scope": "pull-requests:write",
                "job_id": "release",
                "tier": "HARD_BLOCK",
                "message": "",
                "remediation": "",
                "file_path": ".github/workflows/deploy.yml",
                "line": None,
            }
        ]
    }
    scaffold(violations_json, ".github/workflows/deploy.yml", output)

    entries = json.loads(output.read_text())
    assert len(entries) == 2
    scopes = {e["scope"] for e in entries}
    assert scopes == {"contents:write", "pull-requests:write"}
    original = next(e for e in entries if e["scope"] == "contents:write")
    assert original["justification"] == "Already approved"


def test_scaffold_skips_duplicate_scope_workflow(tmp_path):
    existing = [
        {
            "scope": "contents:write",
            "justification": "Already approved",
            "approved_by": "security-team",
            "expires_at": "2099-01-01",
            "workflow": ".github/workflows/deploy.yml",
            "job_id": "build",
        }
    ]
    output = tmp_path / "exceptions.json"
    output.write_text(json.dumps(existing))

    violations_json = {
        "violations": [
            {
                "scope": "contents:write",
                "job_id": "deploy",
                "tier": "HARD_BLOCK",
                "message": "",
                "remediation": "",
                "file_path": ".github/workflows/deploy.yml",
                "line": None,
            }
        ]
    }
    scaffold(violations_json, ".github/workflows/deploy.yml", output)

    entries = json.loads(output.read_text())
    assert len(entries) == 1


def test_scaffold_skips_violations_without_scope(tmp_path):
    violations_json = {
        "violations": [
            {
                "scope": None,
                "job_id": "agent-job",
                "tier": "REQUIRES_REVIEW",
                "message": "",
                "remediation": "",
                "file_path": "x.yml",
                "line": None,
            }
        ]
    }
    output = tmp_path / "exceptions.json"
    scaffold(violations_json, "x.yml", output)

    entries = json.loads(output.read_text())
    assert len(entries) == 0
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_exception_scaffold.py -v
```

Expected: `ImportError` — `flowscope.exception` does not exist yet.

- [ ] **Step 3: Create `src/flowscope/exception.py`**

```python
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any


def _build_entry(violation: dict[str, Any], workflow: str) -> dict[str, Any]:
    return {
        "scope": violation["scope"],
        "justification": "TODO: describe why this exception is needed",
        "approved_by": "",
        "expires_at": str(date.today() + timedelta(days=90)),
        "workflow": workflow,
        "job_id": violation.get("job_id"),
    }


def scaffold(violations_json: dict[str, Any], workflow: str, output_path: Path) -> None:
    violations = [v for v in violations_json.get("violations", []) if v.get("scope")]

    existing: list[dict[str, Any]] = []
    if output_path.exists():
        with open(output_path) as fh:
            existing = json.load(fh)

    existing_keys = {(e.get("scope"), e.get("workflow")) for e in existing}
    new_entries = [
        _build_entry(v, workflow)
        for v in violations
        if (v["scope"], workflow) not in existing_keys
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as fh:
        json.dump(existing + new_entries, fh, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Flowscope exception utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scaffold_parser = subparsers.add_parser(
        "scaffold", help="Generate exception skeleton from violations JSON (reads stdin)"
    )
    scaffold_parser.add_argument(
        "--workflow",
        required=True,
        help="Workflow file path, e.g. .github/workflows/deploy.yml",
    )
    scaffold_parser.add_argument(
        "--output",
        type=Path,
        default=Path(".github/flowscope-exceptions.json"),
        help="Path to write/merge exceptions file",
    )

    args = parser.parse_args()

    if args.command == "scaffold":
        violations_json = json.load(sys.stdin)
        scaffold(violations_json, args.workflow, args.output)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_exception_scaffold.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 5: Add script entry to `pyproject.toml`**

In `[project.scripts]`, add:

```toml
flowscope-exception = "flowscope.exception:main"
```

- [ ] **Step 6: Run full suite to check for regressions**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/flowscope/exception.py tests/test_exception_scaffold.py pyproject.toml
git commit -m "feat: add exception scaffold subcommand"
```

---

### Task 3: Add `create-exception-pr` input to `action.yml`

**Files:**
- Modify: `action.yml`

- [ ] **Step 1: Add the new input**

In `action.yml`, add after the existing `exceptions_file` input block:

```yaml
  create_exception_pr:
    description: >
      When true, automatically create a draft PR with an exception skeleton
      when violations are detected. Requires contents: write and
      pull-requests: write permissions in the calling workflow.
    required: false
    default: "false"
```

- [ ] **Step 2: Pass the new input as an env var to the entrypoint**

In the `Run static analysis gate` step's `env:` block, add:

```yaml
        INPUT_CREATE_EXCEPTION_PR: ${{ inputs.create_exception_pr }}
```

- [ ] **Step 3: Verify the action.yml is valid YAML**

```bash
python -c "import yaml; yaml.safe_load(open('action.yml'))" && echo "OK"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add action.yml
git commit -m "feat: add create-exception-pr input to action"
```

---

### Task 4: Exception PR creation logic in `entrypoint.sh`

**Files:**
- Modify: `entrypoint.sh`

Adds shell logic that runs after the main analysis. If `INPUT_CREATE_EXCEPTION_PR=true` and violations were found, creates a deterministic branch, runs the scaffold, opens a draft PR, and comments on the original blocked PR. Idempotent: if the branch already exists, skips creation and comments with a link to the existing PR.

Also fixes a pre-existing issue: `|| true` inside `$()` caused `EXIT_CODE` to always be 0. This replaces it with `set +e` / `set -e` guards.

- [ ] **Step 1: Replace entrypoint.sh in full**

```bash
#!/bin/bash
set -euo pipefail

WORKFLOW_FILE="${INPUT_WORKFLOW_FILE:?INPUT_WORKFLOW_FILE is required}"
BASELINE_FILE="${INPUT_BASELINE_FILE:-}"
EXCEPTIONS_FILE="${INPUT_EXCEPTIONS_FILE:-}"
CREATE_EXCEPTION_PR="${INPUT_CREATE_EXCEPTION_PR:-false}"

ARGS=("$WORKFLOW_FILE")
[[ -n "$BASELINE_FILE" ]] && ARGS+=("--baseline" "$BASELINE_FILE")
[[ -n "$EXCEPTIONS_FILE" ]] && ARGS+=("--exceptions" "$EXCEPTIONS_FILE")

# Capture output and exit code without triggering set -e on non-zero exit
set +e
OUTPUT=$(python -m flowscope.cli "${ARGS[@]}")
EXIT_CODE=$?
set -e

# Surface JSON output as a step output for downstream jobs
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    echo "result<<EOF" >> "$GITHUB_OUTPUT"
    echo "$OUTPUT" >> "$GITHUB_OUTPUT"
    echo "EOF" >> "$GITHUB_OUTPUT"
fi

# Print to stdout for CI logs
echo "$OUTPUT"

# Exception PR creation — opt-in, only when violations exist
if [[ "$CREATE_EXCEPTION_PR" == "true" && "$EXIT_CODE" -ne 0 ]]; then
    WORKFLOW_STEM=$(basename "${WORKFLOW_FILE}" .yml)
    BRANCH="flowscope/exception-${WORKFLOW_STEM}"

    if git ls-remote --heads origin "${BRANCH}" | grep -q "${BRANCH}"; then
        # Branch already exists — find the open PR and comment on the original
        EXCEPTION_PR_URL=$(gh pr list --head "${BRANCH}" --json url --jq '.[0].url // empty' 2>/dev/null || echo "")
        PR_NUMBER=$(python -c "import json,sys,os; d=json.load(open(os.environ['GITHUB_EVENT_PATH'])); print(d.get('pull_request',{}).get('number',''))" 2>/dev/null || echo "")
        if [[ -n "$PR_NUMBER" ]]; then
            if [[ -n "$EXCEPTION_PR_URL" ]]; then
                COMMENT_BODY="Flowscope blocked this workflow. An exception request is already open: ${EXCEPTION_PR_URL}"
            else
                COMMENT_BODY="Flowscope blocked this workflow. An exception request branch already exists: \`${BRANCH}\`"
            fi
            gh pr comment "$PR_NUMBER" --body "$COMMENT_BODY"
        fi
    else
        # Create the exception branch and PR
        git config user.name "github-actions[bot]"
        git config user.email "github-actions[bot]@users.noreply.github.com"
        git checkout -b "${BRANCH}"

        echo "$OUTPUT" | python -m flowscope.exception scaffold --workflow "${WORKFLOW_FILE}"

        git add .github/flowscope-exceptions.json
        git commit -m "chore: flowscope exception request for ${WORKFLOW_STEM}"
        git push origin "${BRANCH}"

        PR_BODY="**Flowscope detected permission violations in \`${WORKFLOW_FILE}\`.**

This draft PR adds a skeleton exception entry to \`.github/flowscope-exceptions.json\`.

**Developer: before marking ready for review**
1. Edit \`.github/flowscope-exceptions.json\` in this PR
2. Fill in \`justification\` — describe why this permission is needed
3. Confirm or adjust \`expires_at\`
4. Mark this PR as ready for review

**Security team:** approval of this PR constitutes the formal exception grant.
CODEOWNERS enforcement requires your review before merge.
The exception is active immediately on merge — no further action required."

        EXCEPTION_PR_URL=$(gh pr create \
            --draft \
            --title "flowscope: exception request for ${WORKFLOW_STEM}" \
            --body "$PR_BODY" \
            --head "${BRANCH}")

        PR_NUMBER=$(python -c "import json,sys,os; d=json.load(open(os.environ['GITHUB_EVENT_PATH'])); print(d.get('pull_request',{}).get('number',''))" 2>/dev/null || echo "")
        if [[ -n "$PR_NUMBER" ]]; then
            gh pr comment "$PR_NUMBER" --body "Flowscope blocked this workflow. An exception request PR has been created: ${EXCEPTION_PR_URL}

Fill in \`justification\` and confirm \`expires_at\`, then mark the PR ready for security team review."
        fi
    fi
fi

exit $EXIT_CODE
```

- [ ] **Step 2: Make the script executable**

```bash
chmod +x entrypoint.sh
```

- [ ] **Step 3: Run the full test suite to confirm no regressions**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass. (The entrypoint is shell — integration testing requires a real GitHub Actions environment.)

- [ ] **Step 4: Commit**

```bash
git add entrypoint.sh
git commit -m "feat: create exception request PR on violation detection"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| Drop `status` from policy engine | Task 1 |
| Exception with matching `workflow` suppresses | Task 1 |
| Exception with non-matching `workflow` does not suppress | Task 1 |
| Exception without `workflow` = repo-wide grant (backwards compat) | Task 1 |
| `flowscope exception scaffold` subcommand | Task 2 |
| Scaffold merges without clobbering | Task 2 |
| 90-day default expiry | Task 2 |
| Scaffold skips violations with no scope | Task 2 |
| Scaffold skips duplicate scope+workflow | Task 2 |
| `create-exception-pr` action input | Task 3 |
| Deterministic branch name `flowscope/exception-<stem>` | Task 4 |
| Branch existence check for idempotency | Task 4 |
| Draft PR with instructions | Task 4 |
| Comment on original blocked PR | Task 4 |
| Graceful skip of comment when not in PR context | Task 4 |
| `status` removed from scaffold output | Task 2 (no `status` in `_build_entry`) ✓ |

**Placeholder scan:** No TBDs, no "handle appropriately", no "similar to task N". All code blocks are complete.

**Type consistency:** `scaffold(violations_json, workflow, output_path)` — signature defined in Task 2 step 3, used identically in tests (Task 2 step 1) and entrypoint (Task 4 step 1). `_build_entry` is internal, not referenced cross-task.
