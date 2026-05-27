# Static Analysis Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python static analysis tool that parses GitHub Actions workflow YAML, evaluates declared permission scopes against a tiered violation policy, and emits structured check results — packaged as a GitHub Action.

**Architecture:** A `WorkflowAnalyzer` reads workflow YAML with `ruamel.yaml` (comment-preserving), builds a two-level permission model (`WorkflowPermissions` → `JobPermissions`), then evaluates each scope against violation tier rules. Results are emitted as structured JSON annotations suitable for posting as a GitHub check. A thin CLI entry point wires the pieces together and a GitHub Action wrapper invokes it.

**Tech Stack:** Python 3.11+, `ruamel.yaml`, `dataclasses`, `pytest`, GitHub Actions `action.yml`

---

## File Structure

```
hubflow/
├── src/
│   └── hubflow/
│       ├── __init__.py
│       ├── models.py          # Permission dataclasses: WorkflowPermissions, JobPermissions, Violation, CheckResult
│       ├── parser.py          # YAML parsing → WorkflowPermissions model
│       ├── policy.py          # Violation tier evaluation logic
│       ├── analyzer.py        # Orchestrates parser + policy → CheckResult
│       └── cli.py             # Entry point: reads args, calls analyzer, writes output
├── tests/
│   ├── conftest.py            # Shared fixtures (sample YAML helpers)
│   ├── test_parser.py         # Parser unit tests
│   ├── test_policy.py         # Policy rule unit tests
│   ├── test_analyzer.py       # Analyzer integration tests
│   └── fixtures/
│       ├── write_all.yml          # permissions: write-all
│       ├── empty_permissions.yml  # permissions: {}
│       ├── workflow_level_write.yml
│       ├── job_level_scoped.yml
│       ├── agentic_step.yml
│       ├── clean_minimal.yml
│       └── exception_registered.yml
├── action.yml                 # GitHub Action definition
├── pyproject.toml             # Package config + dependencies
└── docs/
    └── superpowers/
        └── plans/
            └── 2026-05-26-static-analysis-gate.md
```

---

## Task 1: Project scaffold and dataclasses

**Files:**
- Create: `pyproject.toml`
- Create: `src/hubflow/__init__.py`
- Create: `src/hubflow/models.py`
- Create: `tests/conftest.py`
- Create: `tests/test_parser.py` (stub — actual tests added in Task 2)

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "hubflow"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "ruamel.yaml>=0.18",
]

[project.scripts]
hubflow = "hubflow.cli:main"

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-cov",
]

[tool.hatch.build.targets.wheel]
packages = ["src/hubflow"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create `src/hubflow/__init__.py`** (empty)

```python
```

- [ ] **Step 3: Create `src/hubflow/models.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AccessLevel(str, Enum):
    READ = "read"
    WRITE = "write"
    NONE = "none"


class ViolationTier(str, Enum):
    HARD_BLOCK = "hard_block"
    WARNING = "warning"
    ADVISORY = "advisory"


@dataclass
class JobPermissions:
    job_id: str
    scopes: dict[str, AccessLevel] = field(default_factory=dict)


@dataclass
class WorkflowPermissions:
    workflow_level: dict[str, AccessLevel] = field(default_factory=dict)
    # write_all and implicit_full_access are special cases that collapse scope detail
    write_all: bool = False
    implicit_full_access: bool = False
    jobs: dict[str, JobPermissions] = field(default_factory=dict)


@dataclass
class Violation:
    tier: ViolationTier
    file_path: str
    line: Optional[int]
    scope: Optional[str]
    job_id: Optional[str]
    message: str
    remediation: str


@dataclass
class CheckResult:
    workflow_path: str
    passed: bool
    violations: list[Violation] = field(default_factory=list)

    def has_hard_block(self) -> bool:
        return any(v.tier == ViolationTier.HARD_BLOCK for v in self.violations)
```

- [ ] **Step 4: Create `tests/conftest.py`**

```python
import textwrap
from pathlib import Path
import pytest


def make_workflow(content: str) -> str:
    """Strip leading indent so inline YAML in tests looks clean."""
    return textwrap.dedent(content)
```

- [ ] **Step 5: Install the package in editable mode**

```bash
cd /home/mshade/projects/hubflow
pip install -e ".[dev]"
```

Expected output: `Successfully installed hubflow-0.1.0`

- [ ] **Step 6: Commit**

```bash
git init
git add pyproject.toml src/ tests/conftest.py
git commit -m "feat: project scaffold and permission dataclasses"
```

---

## Task 2: YAML parser

**Files:**
- Create: `src/hubflow/parser.py`
- Create: `tests/fixtures/write_all.yml`
- Create: `tests/fixtures/empty_permissions.yml`
- Create: `tests/fixtures/workflow_level_write.yml`
- Create: `tests/fixtures/job_level_scoped.yml`
- Create: `tests/fixtures/clean_minimal.yml`
- Create: `tests/test_parser.py`

- [ ] **Step 1: Create fixture files**

`tests/fixtures/write_all.yml`:
```yaml
name: Deploy
on: [push]
permissions: write-all
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
```

`tests/fixtures/empty_permissions.yml`:
```yaml
name: Deploy
on: [push]
permissions: {}
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
```

`tests/fixtures/workflow_level_write.yml`:
```yaml
name: Deploy
on: [push]
permissions:
  contents: write
  packages: read
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
  deploy:
    runs-on: ubuntu-latest
    steps:
      - run: echo deploy
```

`tests/fixtures/job_level_scoped.yml`:
```yaml
name: Deploy
on: [push]
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
  test:
    runs-on: ubuntu-latest
    steps:
      - run: pytest
```

`tests/fixtures/clean_minimal.yml`:
```yaml
name: CI
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
```

- [ ] **Step 2: Write the failing parser tests**

`tests/test_parser.py`:
```python
from pathlib import Path
import pytest
from hubflow.models import AccessLevel, WorkflowPermissions
from hubflow.parser import parse_workflow

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_write_all():
    result = parse_workflow(FIXTURES / "write_all.yml")
    assert result.write_all is True
    assert result.implicit_full_access is False


def test_parse_empty_permissions():
    result = parse_workflow(FIXTURES / "empty_permissions.yml")
    assert result.implicit_full_access is True
    assert result.write_all is False


def test_parse_workflow_level_scopes():
    result = parse_workflow(FIXTURES / "workflow_level_write.yml")
    assert result.workflow_level["contents"] == AccessLevel.WRITE
    assert result.workflow_level["packages"] == AccessLevel.READ


def test_parse_job_level_scopes():
    result = parse_workflow(FIXTURES / "job_level_scoped.yml")
    assert "build" in result.jobs
    assert result.jobs["build"].scopes["contents"] == AccessLevel.WRITE


def test_parse_no_job_level_permissions():
    result = parse_workflow(FIXTURES / "job_level_scoped.yml")
    # 'test' job has no explicit permissions block
    assert "test" not in result.jobs or result.jobs["test"].scopes == {}


def test_parse_no_top_level_permissions():
    result = parse_workflow(FIXTURES / "clean_minimal.yml")
    assert result.write_all is False
    assert result.implicit_full_access is False
    assert result.workflow_level == {}


def test_parse_job_permissions_in_clean_workflow():
    result = parse_workflow(FIXTURES / "clean_minimal.yml")
    assert result.jobs["test"].scopes["contents"] == AccessLevel.READ
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_parser.py -v
```

Expected: `ImportError: No module named 'hubflow.parser'`

- [ ] **Step 4: Implement `src/hubflow/parser.py`**

```python
from pathlib import Path
from ruamel.yaml import YAML
from .models import AccessLevel, JobPermissions, WorkflowPermissions

_yaml = YAML()
_yaml.preserve_quotes = True


def _parse_access_level(value: str) -> AccessLevel:
    match value.lower():
        case "read":
            return AccessLevel.READ
        case "write":
            return AccessLevel.WRITE
        case "none":
            return AccessLevel.NONE
        case _:
            return AccessLevel.READ  # unknown defaults to read (conservative)


def _parse_scope_map(raw: dict) -> dict[str, AccessLevel]:
    return {k: _parse_access_level(v) for k, v in raw.items()}


def parse_workflow(path: Path) -> WorkflowPermissions:
    with open(path) as fh:
        doc = _yaml.load(fh)

    result = WorkflowPermissions()

    top_perms = doc.get("permissions")
    if top_perms == "write-all":
        result.write_all = True
    elif isinstance(top_perms, dict) and len(top_perms) == 0:
        result.implicit_full_access = True
    elif isinstance(top_perms, dict):
        result.workflow_level = _parse_scope_map(top_perms)
    # top_perms is None → no top-level block, which is fine

    for job_id, job_data in (doc.get("jobs") or {}).items():
        job_perms = job_data.get("permissions")
        if isinstance(job_perms, dict) and job_perms:
            result.jobs[job_id] = JobPermissions(
                job_id=job_id,
                scopes=_parse_scope_map(job_perms),
            )

    return result
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_parser.py -v
```

Expected: `7 passed`

- [ ] **Step 6: Commit**

```bash
git add src/hubflow/parser.py tests/test_parser.py tests/fixtures/
git commit -m "feat: YAML parser for workflow permission model"
```

---

## Task 3: Policy violation tier evaluation

**Files:**
- Create: `src/hubflow/policy.py`
- Create: `tests/fixtures/agentic_step.yml`
- Create: `tests/test_policy.py`

The policy module receives a `WorkflowPermissions` and a `workflow_path`, and returns a list of `Violation` objects. It does **not** call GitHub APIs — baseline and exception data are injected as plain Python dicts so the module stays pure and testable.

**Known agentic actions** (hard-coded registry for v1, expandable later):
- `anthropics/claude-code-action`
- `anthropics/claude-code-action/subagents` (any ref)

- [ ] **Step 1: Create the agentic fixture**

`tests/fixtures/agentic_step.yml`:
```yaml
name: AI Agent
on: [push]
permissions:
  contents: write
  pull-requests: write
jobs:
  agent:
    runs-on: ubuntu-latest
    steps:
      - uses: anthropics/claude-code-action@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
```

- [ ] **Step 2: Write the failing policy tests**

`tests/test_policy.py`:
```python
from pathlib import Path
import pytest
from hubflow.models import AccessLevel, JobPermissions, ViolationTier, WorkflowPermissions
from hubflow.parser import parse_workflow
from hubflow.policy import evaluate_policy

FIXTURES = Path(__file__).parent / "fixtures"


# ── Hard-block rules ──────────────────────────────────────────────────────────

def test_write_all_is_hard_block():
    perms = parse_workflow(FIXTURES / "write_all.yml")
    violations = evaluate_policy(perms, "test.yml", raw_doc=None)
    tiers = [v.tier for v in violations]
    assert ViolationTier.HARD_BLOCK in tiers


def test_empty_permissions_is_hard_block():
    perms = parse_workflow(FIXTURES / "empty_permissions.yml")
    violations = evaluate_policy(perms, "test.yml", raw_doc=None)
    tiers = [v.tier for v in violations]
    assert ViolationTier.HARD_BLOCK in tiers


def test_workflow_level_write_no_job_scoping_is_hard_block():
    perms = parse_workflow(FIXTURES / "workflow_level_write.yml")
    violations = evaluate_policy(perms, "test.yml", raw_doc=None)
    tiers = [v.tier for v in violations]
    assert ViolationTier.HARD_BLOCK in tiers


# ── Clean workflow passes ─────────────────────────────────────────────────────

def test_clean_minimal_has_no_hard_block():
    perms = parse_workflow(FIXTURES / "clean_minimal.yml")
    violations = evaluate_policy(perms, "test.yml", raw_doc=None)
    assert not any(v.tier == ViolationTier.HARD_BLOCK for v in violations)


# ── Job-level scoping lifts hard-block ───────────────────────────────────────

def test_workflow_level_write_with_all_jobs_scoped_no_hard_block():
    """workflow-level write is acceptable when every job has explicit job-level permissions."""
    perms = WorkflowPermissions(
        workflow_level={"contents": AccessLevel.WRITE},
        jobs={
            "build": JobPermissions("build", {"contents": AccessLevel.WRITE}),
            "test": JobPermissions("test", {"contents": AccessLevel.READ}),
        },
    )
    violations = evaluate_policy(perms, "test.yml", raw_doc=None)
    assert not any(v.tier == ViolationTier.HARD_BLOCK for v in violations)


# ── Agentic step warnings ─────────────────────────────────────────────────────

def test_agentic_step_with_write_scope_and_no_baseline_is_warning():
    import yaml as _yaml  # stdlib yaml for raw_doc construction in tests
    with open(FIXTURES / "agentic_step.yml") as fh:
        raw = _yaml.safe_load(fh)
    perms = parse_workflow(FIXTURES / "agentic_step.yml")
    violations = evaluate_policy(perms, "agentic_step.yml", raw_doc=raw, observed_baseline=None)
    messages = [v.message for v in violations]
    assert any("agentic" in m.lower() for m in messages)


# ── Exceptions suppress violations ───────────────────────────────────────────

def test_registered_exception_suppresses_hard_block():
    from datetime import date
    perms = parse_workflow(FIXTURES / "write_all.yml")
    exceptions = [
        {
            "scope": "write-all",
            "justification": "Legacy deploy job requires full token",
            "approved_by": "platform-team",
            "expires_at": str(date(2099, 1, 1)),
            "status": "active",
        }
    ]
    violations = evaluate_policy(perms, "test.yml", raw_doc=None, exceptions=exceptions)
    assert not any(v.tier == ViolationTier.HARD_BLOCK for v in violations)


def test_expired_exception_does_not_suppress():
    from datetime import date
    perms = parse_workflow(FIXTURES / "write_all.yml")
    exceptions = [
        {
            "scope": "write-all",
            "justification": "Old exception",
            "approved_by": "platform-team",
            "expires_at": str(date(2020, 1, 1)),
            "status": "active",
        }
    ]
    violations = evaluate_policy(perms, "test.yml", raw_doc=None, exceptions=exceptions)
    assert any(v.tier == ViolationTier.HARD_BLOCK for v in violations)
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_policy.py -v
```

Expected: `ImportError: No module named 'hubflow.policy'`

- [ ] **Step 4: Implement `src/hubflow/policy.py`**

```python
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from .models import AccessLevel, JobPermissions, Violation, ViolationTier, WorkflowPermissions

# Actions known to make dynamic API calls under the job token
AGENTIC_ACTIONS: set[str] = {
    "anthropics/claude-code-action",
}

_WRITE_ALL_SCOPE = "write-all"
_IMPLICIT_FULL_SCOPE = "implicit-full-access"


def _is_exception_active(exc: dict[str, Any]) -> bool:
    if exc.get("status") != "active":
        return False
    try:
        expires = date.fromisoformat(str(exc["expires_at"]))
    except (KeyError, ValueError):
        return False
    return expires >= date.today()


def _scope_is_excepted(scope: str, exceptions: list[dict]) -> bool:
    return any(
        exc.get("scope") == scope and _is_exception_active(exc)
        for exc in exceptions
    )


def _job_names_from_doc(raw_doc: Optional[dict]) -> list[str]:
    if not raw_doc:
        return []
    return list((raw_doc.get("jobs") or {}).keys())


def _steps_for_job(raw_doc: Optional[dict], job_id: str) -> list[dict]:
    if not raw_doc:
        return []
    return (raw_doc.get("jobs") or {}).get(job_id, {}).get("steps") or []


def _job_uses_agentic_action(raw_doc: Optional[dict], job_id: str) -> bool:
    for step in _steps_for_job(raw_doc, job_id):
        uses = step.get("uses", "")
        action_name = uses.split("@")[0] if "@" in uses else uses
        if action_name in AGENTIC_ACTIONS:
            return True
    return False


def evaluate_policy(
    perms: WorkflowPermissions,
    workflow_path: str,
    raw_doc: Optional[dict],
    observed_baseline: Optional[dict[str, Any]] = None,
    exceptions: Optional[list[dict]] = None,
) -> list[Violation]:
    exceptions = exceptions or []
    violations: list[Violation] = []

    # ── Rule 1: write-all ────────────────────────────────────────────────────
    if perms.write_all:
        if not _scope_is_excepted(_WRITE_ALL_SCOPE, exceptions):
            violations.append(
                Violation(
                    tier=ViolationTier.HARD_BLOCK,
                    file_path=workflow_path,
                    line=None,
                    scope=_WRITE_ALL_SCOPE,
                    job_id=None,
                    message="permissions: write-all grants full token access",
                    remediation=(
                        "Replace with explicit per-job permission blocks scoped to "
                        "minimum required access. See docs/permissions-guide.md."
                    ),
                )
            )
        return violations  # no further analysis useful when write-all

    # ── Rule 2: implicit full access (permissions: {}) ───────────────────────
    if perms.implicit_full_access:
        if not _scope_is_excepted(_IMPLICIT_FULL_SCOPE, exceptions):
            violations.append(
                Violation(
                    tier=ViolationTier.HARD_BLOCK,
                    file_path=workflow_path,
                    line=None,
                    scope=_IMPLICIT_FULL_SCOPE,
                    job_id=None,
                    message=(
                        "permissions: {} (empty map) is equivalent to write-all "
                        "on GitHub Actions"
                    ),
                    remediation=(
                        "Declare explicit scopes at the job level. "
                        "Remove the empty top-level permissions block."
                    ),
                )
            )
        return violations

    # ── Rule 3: workflow-level write with unscoped jobs ──────────────────────
    write_scopes_at_workflow = {
        s for s, lvl in perms.workflow_level.items() if lvl == AccessLevel.WRITE
    }

    if write_scopes_at_workflow:
        all_job_ids = _job_names_from_doc(raw_doc) or list(perms.jobs.keys())
        unscoped_jobs = [jid for jid in all_job_ids if jid not in perms.jobs]

        if unscoped_jobs:
            for scope in write_scopes_at_workflow:
                if not _scope_is_excepted(scope, exceptions):
                    violations.append(
                        Violation(
                            tier=ViolationTier.HARD_BLOCK,
                            file_path=workflow_path,
                            line=None,
                            scope=scope,
                            job_id=None,
                            message=(
                                f"Workflow-level write scope '{scope}' applies to "
                                f"unscoped jobs: {unscoped_jobs}. "
                                "Job-level permissions blocks must override it."
                            ),
                            remediation=(
                                f"Add an explicit permissions block to each job "
                                f"({', '.join(unscoped_jobs)}) to restrict the "
                                f"'{scope}' write scope to only jobs that need it."
                            ),
                        )
                    )

    # ── Rule 4: agentic step with write scope and no baseline ────────────────
    all_job_ids = _job_names_from_doc(raw_doc) or list(perms.jobs.keys())
    for job_id in all_job_ids:
        if not _job_uses_agentic_action(raw_doc, job_id):
            continue

        job_perms = perms.jobs.get(job_id)
        effective_scopes = job_perms.scopes if job_perms else perms.workflow_level
        has_write = any(lvl == AccessLevel.WRITE for lvl in effective_scopes.values())

        if has_write and observed_baseline is None:
            violations.append(
                Violation(
                    tier=ViolationTier.WARNING,
                    file_path=workflow_path,
                    line=None,
                    scope=None,
                    job_id=job_id,
                    message=(
                        f"Job '{job_id}' uses an agentic action with write scope(s) "
                        "but has no observed usage baseline. "
                        "Agentic steps make dynamic API calls — over-permissioning "
                        "has a higher blast radius."
                    ),
                    remediation=(
                        "Instrument the runner with the hubflow post-job hook to "
                        "establish an observed baseline, or manually justify each "
                        "write scope with an inline comment."
                    ),
                )
            )

    return violations
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_policy.py -v
```

Expected: `8 passed`

- [ ] **Step 6: Commit**

```bash
git add src/hubflow/policy.py tests/test_policy.py tests/fixtures/agentic_step.yml
git commit -m "feat: policy violation tier evaluation"
```

---

## Task 4: Analyzer orchestration and structured output

**Files:**
- Create: `src/hubflow/analyzer.py`
- Create: `tests/test_analyzer.py`

The analyzer loads the YAML once, extracts both the parsed permissions model and the raw doc (for job-name and step lookups), then calls the policy evaluator. It returns a `CheckResult` with a `passed` flag and the full violation list.

- [ ] **Step 1: Write failing tests**

`tests/test_analyzer.py`:
```python
from pathlib import Path
import json
import pytest
from hubflow.analyzer import analyze_workflow
from hubflow.models import ViolationTier

FIXTURES = Path(__file__).parent / "fixtures"


def test_write_all_fails_check():
    result = analyze_workflow(FIXTURES / "write_all.yml")
    assert result.passed is False
    assert result.has_hard_block()


def test_empty_permissions_fails_check():
    result = analyze_workflow(FIXTURES / "empty_permissions.yml")
    assert result.passed is False
    assert result.has_hard_block()


def test_clean_minimal_passes_check():
    result = analyze_workflow(FIXTURES / "clean_minimal.yml")
    assert result.passed is True
    assert not result.has_hard_block()


def test_workflow_level_write_fails_check():
    result = analyze_workflow(FIXTURES / "workflow_level_write.yml")
    assert result.passed is False


def test_violations_include_remediation():
    result = analyze_workflow(FIXTURES / "write_all.yml")
    for v in result.violations:
        assert v.remediation, f"Violation {v} missing remediation"


def test_result_serializes_to_json():
    result = analyze_workflow(FIXTURES / "write_all.yml")
    output = {
        "workflow_path": result.workflow_path,
        "passed": result.passed,
        "violations": [
            {
                "tier": v.tier.value,
                "file_path": v.file_path,
                "line": v.line,
                "scope": v.scope,
                "job_id": v.job_id,
                "message": v.message,
                "remediation": v.remediation,
            }
            for v in result.violations
        ],
    }
    # Must be JSON-serializable
    json.dumps(output)
    assert output["passed"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_analyzer.py -v
```

Expected: `ImportError: No module named 'hubflow.analyzer'`

- [ ] **Step 3: Implement `src/hubflow/analyzer.py`**

```python
from pathlib import Path
from typing import Any, Optional

from ruamel.yaml import YAML

from .models import CheckResult
from .parser import parse_workflow
from .policy import evaluate_policy

_yaml = YAML()


def analyze_workflow(
    workflow_path: Path,
    observed_baseline: Optional[dict[str, Any]] = None,
    exceptions: Optional[list[dict]] = None,
) -> CheckResult:
    with open(workflow_path) as fh:
        raw_doc = _yaml.load(fh)

    perms = parse_workflow(workflow_path)
    violations = evaluate_policy(
        perms,
        str(workflow_path),
        raw_doc=raw_doc,
        observed_baseline=observed_baseline,
        exceptions=exceptions,
    )

    passed = not any(True for v in violations if v.tier.value == "hard_block")

    return CheckResult(
        workflow_path=str(workflow_path),
        passed=passed,
        violations=violations,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_analyzer.py -v
```

Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add src/hubflow/analyzer.py tests/test_analyzer.py
git commit -m "feat: analyzer orchestrates parser + policy into CheckResult"
```

---

## Task 5: CLI entry point

**Files:**
- Create: `src/hubflow/cli.py`

The CLI accepts a workflow file path and optional flags, runs the analyzer, prints structured JSON to stdout, and exits with code 1 if the check fails.

- [ ] **Step 1: Write failing CLI test**

Add to `tests/test_analyzer.py` (append to the file):

```python
import subprocess
import sys


def test_cli_exits_1_on_hard_block():
    result = subprocess.run(
        [sys.executable, "-m", "hubflow.cli", str(FIXTURES / "write_all.yml")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1


def test_cli_exits_0_on_clean():
    result = subprocess.run(
        [sys.executable, "-m", "hubflow.cli", str(FIXTURES / "clean_minimal.yml")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_cli_outputs_json():
    result = subprocess.run(
        [sys.executable, "-m", "hubflow.cli", str(FIXTURES / "write_all.yml")],
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    assert "violations" in data
    assert "passed" in data
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
pytest tests/test_analyzer.py::test_cli_exits_1_on_hard_block tests/test_analyzer.py::test_cli_exits_0_on_clean tests/test_analyzer.py::test_cli_outputs_json -v
```

Expected: `ModuleNotFoundError` or `SystemExit`

- [ ] **Step 3: Implement `src/hubflow/cli.py`**

```python
import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .analyzer import analyze_workflow
from .models import Violation


def _violation_to_dict(v: Violation) -> dict:
    return {
        "tier": v.tier.value,
        "file_path": v.file_path,
        "line": v.line,
        "scope": v.scope,
        "job_id": v.job_id,
        "message": v.message,
        "remediation": v.remediation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze a GitHub Actions workflow for permission violations."
    )
    parser.add_argument("workflow", type=Path, help="Path to the workflow YAML file")
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="Path to a JSON file with observed usage baseline",
    )
    parser.add_argument(
        "--exceptions",
        type=Path,
        default=None,
        help="Path to a JSON file with registered exceptions",
    )
    args = parser.parse_args()

    observed_baseline = None
    if args.baseline and args.baseline.exists():
        with open(args.baseline) as fh:
            observed_baseline = json.load(fh)

    exceptions = None
    if args.exceptions and args.exceptions.exists():
        with open(args.exceptions) as fh:
            exceptions = json.load(fh)

    result = analyze_workflow(args.workflow, observed_baseline=observed_baseline, exceptions=exceptions)

    output = {
        "workflow_path": result.workflow_path,
        "passed": result.passed,
        "violations": [_violation_to_dict(v) for v in result.violations],
    }
    print(json.dumps(output, indent=2))

    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run all tests**

```bash
pytest tests/ -v
```

Expected: all tests pass (including the 3 new CLI tests)

- [ ] **Step 5: Commit**

```bash
git add src/hubflow/cli.py tests/test_analyzer.py
git commit -m "feat: CLI entry point with JSON output and exit codes"
```

---

## Task 6: GitHub Action packaging

**Files:**
- Create: `action.yml`
- Create: `entrypoint.sh`

- [ ] **Step 1: Create `entrypoint.sh`**

```bash
#!/bin/bash
set -euo pipefail

WORKFLOW_FILE="${INPUT_WORKFLOW_FILE:?INPUT_WORKFLOW_FILE is required}"
BASELINE_FILE="${INPUT_BASELINE_FILE:-}"
EXCEPTIONS_FILE="${INPUT_EXCEPTIONS_FILE:-}"

ARGS=("$WORKFLOW_FILE")
[[ -n "$BASELINE_FILE" ]] && ARGS+=("--baseline" "$BASELINE_FILE")
[[ -n "$EXCEPTIONS_FILE" ]] && ARGS+=("--exceptions" "$EXCEPTIONS_FILE")

python -m hubflow.cli "${ARGS[@]}"
EXIT_CODE=$?

# Surface JSON output as a step output for downstream jobs
OUTPUT=$(python -m hubflow.cli "${ARGS[@]}" 2>/dev/null || true)
echo "result<<EOF" >> "$GITHUB_OUTPUT"
echo "$OUTPUT" >> "$GITHUB_OUTPUT"
echo "EOF" >> "$GITHUB_OUTPUT"

exit $EXIT_CODE
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x entrypoint.sh
```

- [ ] **Step 3: Create `action.yml`**

```yaml
name: hubflow-static-analysis-gate
description: >
  Analyzes GitHub Actions workflow files for permission scope violations.
  Hard-blocks write-all, implicit full access, and unscoped workflow-level writes.
  Warns on agentic steps with write scope and no observed baseline.

inputs:
  workflow_file:
    description: Path to the workflow YAML file to analyze
    required: true
  baseline_file:
    description: Path to JSON file with observed usage baseline (from observation plane)
    required: false
    default: ""
  exceptions_file:
    description: Path to JSON file with registered scope exceptions
    required: false
    default: ""

outputs:
  result:
    description: Full JSON check result (workflow_path, passed, violations[])

runs:
  using: composite
  steps:
    - name: Install hubflow
      shell: bash
      run: pip install -e "${{ github.action_path }}" --quiet
    - name: Run static analysis gate
      shell: bash
      env:
        INPUT_WORKFLOW_FILE: ${{ inputs.workflow_file }}
        INPUT_BASELINE_FILE: ${{ inputs.baseline_file }}
        INPUT_EXCEPTIONS_FILE: ${{ inputs.exceptions_file }}
      run: "${{ github.action_path }}/entrypoint.sh"
```

- [ ] **Step 4: Run full test suite one final time**

```bash
pytest tests/ -v --tb=short
```

Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add action.yml entrypoint.sh
git commit -m "feat: GitHub Action packaging (action.yml + entrypoint.sh)"
```

---

## Post-Plan Self-Review

### Spec coverage check

| Spec requirement | Covered by |
|---|---|
| Parse `permissions: write-all` → hard block | Task 2 parser + Task 3 policy Rule 1 |
| Parse `permissions: {}` → hard block | Task 2 parser + Task 3 policy Rule 2 |
| Workflow-level write with no job-level scoping → hard block | Task 3 policy Rule 3 |
| Job-level override model (JobPermissions) | Task 1 models + Task 2 parser |
| Warning: write scope + no baseline | Task 3 policy Rule 4 (agentic) + baseline param threading |
| Advisory: no justification comment | **Gap — see note below** |
| Suppression via registered exceptions | Task 3 policy, exception injection, tests |
| Expiry check on exceptions | Task 3 policy `_is_exception_active` |
| Structured output with file/line/tier/remediation | Task 4 analyzer + Task 5 CLI |
| GitHub Action packaging | Task 6 |
| ruamel.yaml for comment-preserving parse | Task 2 parser |
| Exit 0/1 for pass/fail | Task 5 CLI |

**Advisory gap:** The spec calls for an `ADVISORY` tier for write scopes with no justification comment in the YAML. `ruamel.yaml` preserves comments, making this technically feasible, but it requires comment-extraction logic that adds meaningful scope. It is not blocked by any earlier task. Add it as a follow-on task after the core gate is validated in production to avoid scope creep on the first delivery.

**Warning: declared scope not referenced by any known action in the job** — This requires a curated action→scope registry (noted in spec Open Questions). Not implemented in v1; the spec explicitly calls it out as future work.

### Placeholder scan

No TBDs, TODOs, or "similar to task N" patterns found. All code blocks are complete.

### Type consistency check

- `WorkflowPermissions`, `JobPermissions`, `Violation`, `CheckResult`, `AccessLevel`, `ViolationTier` — defined in Task 1, imported consistently across Tasks 2–5.
- `parse_workflow(path: Path) -> WorkflowPermissions` — defined Task 2, called in Task 4.
- `evaluate_policy(perms, path, raw_doc, observed_baseline, exceptions) -> list[Violation]` — defined Task 3, called in Task 4.
- `analyze_workflow(path, observed_baseline, exceptions) -> CheckResult` — defined Task 4, called in Task 5.
- `CheckResult.has_hard_block()` — defined Task 1, used in Task 4 tests.

All consistent.
