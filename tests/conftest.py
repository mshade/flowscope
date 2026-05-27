import textwrap
from pathlib import Path
import pytest


def make_workflow(content: str) -> str:
    """Strip leading indent so inline YAML in tests looks clean."""
    return textwrap.dedent(content)
