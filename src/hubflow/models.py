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
