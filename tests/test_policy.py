from pathlib import Path
import pytest
from flowscope.models import AccessLevel, JobPermissions, ViolationTier, WorkflowPermissions
from flowscope.parser import parse_workflow
from flowscope.policy import evaluate_policy

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


# ── Requires-review rules ─────────────────────────────────────────────────────

def test_agentic_step_with_write_scope_and_no_baseline_requires_review():
    from ruamel.yaml import YAML as _YAML
    _yaml = _YAML()
    with open(FIXTURES / "agentic_step.yml") as fh:
        raw = _yaml.load(fh)
    perms = parse_workflow(FIXTURES / "agentic_step.yml")
    violations = evaluate_policy(perms, "agentic_step.yml", raw_doc=raw, observed_baseline=None)
    tiers = [v.tier for v in violations]
    assert ViolationTier.REQUIRES_REVIEW in tiers
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
        }
    ]
    violations = evaluate_policy(perms, "test.yml", raw_doc=None, exceptions=exceptions)
    assert any(v.tier == ViolationTier.HARD_BLOCK for v in violations)


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
