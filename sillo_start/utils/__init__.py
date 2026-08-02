"""Shared low-level helpers used across every layer of Sillo Start."""

from .console import Console, console, is_ci
from .environment import EnvFile, EnvVar, generate_secret_key
from .filesystem import (
    ensure_dir,
    is_empty_dir,
    is_writable,
    read_text,
    relative_to_cwd,
    remove,
    unified_diff,
    write_text,
)
from .naming import (
    is_valid_project_name,
    is_valid_python_identifier,
    package_name_for,
    pluralize,
    table_name,
    to_camel,
    to_kebab,
    to_pascal,
    to_snake,
    to_title,
)
from .ports import can_connect, find_free_port, is_port_free, is_port_in_use
from .subprocess import CommandResult, require_tool, run, stream, tool_exists, which

__all__ = [
    "Console",
    "console",
    "is_ci",
    "EnvFile",
    "EnvVar",
    "generate_secret_key",
    "ensure_dir",
    "is_empty_dir",
    "is_writable",
    "read_text",
    "relative_to_cwd",
    "remove",
    "unified_diff",
    "write_text",
    "is_valid_project_name",
    "is_valid_python_identifier",
    "package_name_for",
    "pluralize",
    "table_name",
    "to_camel",
    "to_kebab",
    "to_pascal",
    "to_snake",
    "to_title",
    "can_connect",
    "find_free_port",
    "is_port_free",
    "is_port_in_use",
    "CommandResult",
    "require_tool",
    "run",
    "stream",
    "tool_exists",
    "which",
]
