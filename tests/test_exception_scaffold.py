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
