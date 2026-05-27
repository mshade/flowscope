from pathlib import Path
import pytest
from flowscope.models import AccessLevel, WorkflowPermissions
from flowscope.parser import parse_workflow

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
