"""Shared low-level helpers."""

from .console import Console, console, is_ci
from .naming import is_valid_project_name, is_valid_python_identifier, package_name_for
from .pkgmanagers import detect_python_manager
from .subprocess import CommandResult, require_tool, run, tool_exists, which

__all__ = [
    "Console",
    "console",
    "is_ci",
    "is_valid_project_name",
    "is_valid_python_identifier",
    "package_name_for",
    "detect_python_manager",
    "CommandResult",
    "require_tool",
    "run",
    "tool_exists",
    "which",
]
