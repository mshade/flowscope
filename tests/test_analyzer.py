from pathlib import Path
import json
import pytest
from flowscope.analyzer import analyze_workflow
from flowscope.models import ViolationTier

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


def test_agentic_step_requires_review_fails_check():
    # agentic_scoped.yml: job-level permissions (no Rule 3), agentic action, no baseline
    # → only violation should be REQUIRES_REVIEW
    result = analyze_workflow(FIXTURES / "agentic_scoped.yml")
    assert result.passed is False
    assert result.requires_review()
    assert not result.has_hard_block()


def test_workflow_path_preserved_in_result():
    fixture_path = FIXTURES / "clean_minimal.yml"
    result = analyze_workflow(fixture_path)
    assert str(fixture_path) in result.workflow_path or str(fixture_path.absolute()) == result.workflow_path


import subprocess
import sys


def test_cli_exits_1_on_hard_block():
    result = subprocess.run(
        [sys.executable, "-m", "flowscope.cli", str(FIXTURES / "write_all.yml")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1


def test_cli_exits_0_on_clean():
    result = subprocess.run(
        [sys.executable, "-m", "flowscope.cli", str(FIXTURES / "clean_minimal.yml")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_cli_outputs_json():
    result = subprocess.run(
        [sys.executable, "-m", "flowscope.cli", str(FIXTURES / "write_all.yml")],
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    assert "violations" in data
    assert "passed" in data
