"""Safe wrappers around external commands.

Two rules drive this module. First, commands are always passed as argument
lists — never a shell string — so a project name or package version can never
be interpreted as shell syntax. Second, when a command fails its output is
attached to the raised error, because a scaffolding tool that hides a failing
``uv add`` is worse than one that never ran it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..exceptions import CommandError, ToolNotFoundError
from .console import console

#: Commands that may legitimately take a long time (dependency resolution).
DEFAULT_TIMEOUT = 600


@dataclass(frozen=True)
class CommandResult:
    """Outcome of a finished command."""

    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def output(self) -> str:
        """Combined output, for error reporting."""
        return "\n".join(
            part for part in (self.stdout.strip(), self.stderr.strip()) if part
        )


def which(tool: str) -> str | None:
    """Locate *tool* on ``PATH``, returning its path or ``None``."""
    return shutil.which(tool)


def tool_exists(tool: str) -> bool:
    """Report whether *tool* is available on ``PATH``."""
    return which(tool) is not None


def require_tool(tool: str, *, hint: str | None = None) -> str:
    """Return the path to *tool*, or raise with an install hint.

    Raises:
        ToolNotFoundError: If the tool is not on ``PATH``.
    """
    path = which(tool)
    if path is None:
        raise ToolNotFoundError(
            f"Required tool not found on PATH: {tool}",
            hint=hint or f"Install {tool} and make sure it is on your PATH.",
        )
    return path


def run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    check: bool = True,
    capture: bool = True,
    input_text: str | None = None,
) -> CommandResult:
    """Run *command* and return its result.

    Args:
        command: Argument list. Never a shell string.
        cwd: Working directory for the child process.
        env: Extra environment variables layered over the current environment.
        timeout: Seconds before the child is killed.
        check: Raise :class:`CommandError` on a non-zero exit.
        capture: Capture stdout/stderr. When false the child inherits our
            streams, which is what interactive tools such as ``vite`` need.
        input_text: Text piped to the child's stdin.

    Returns:
        A :class:`CommandResult` carrying the exit code and captured output.

    Raises:
        CommandError: On non-zero exit when *check* is set, or on timeout.
        ToolNotFoundError: If the executable does not exist.
    """
    argv = [str(part) for part in command]
    if not argv:
        raise CommandError("Cannot run an empty command.")

    merged_env = {**os.environ, **(env or {})}
    console.debug(f"run: {' '.join(argv)} (cwd={cwd or Path.cwd()})")

    try:
        completed = subprocess.run(  # noqa: S603 — argv list, never shell=True
            argv,
            cwd=str(cwd) if cwd else None,
            env=merged_env,
            timeout=timeout,
            capture_output=capture,
            text=True,
            input=input_text,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ToolNotFoundError(
            f"Command not found: {argv[0]}",
            hint=f"Install {argv[0]} and make sure it is on your PATH.",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise CommandError(
            f"Command timed out after {timeout}s: {' '.join(argv)}",
            command=argv,
            output=_decode(exc.stdout) + _decode(exc.stderr),
        ) from exc

    result = CommandResult(
        command=argv,
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )

    if check and not result.ok:
        raise CommandError(
            f"Command failed with exit code {result.returncode}: {' '.join(argv)}",
            command=argv,
            returncode=result.returncode,
            output=result.output,
        )
    return result


def _decode(value: str | bytes | None) -> str:
    """Coerce possibly-bytes subprocess output to text."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def stream(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> int:
    """Run *command* with its output attached to our terminal.

    Used for children whose output should appear as it happens — an interactive
    prompt, or a build whose progress the user is watching.

    Returns:
        The child's exit code.
    """
    return run(
        command,
        cwd=cwd,
        env=env,
        timeout=timeout,
        check=False,
        capture=False,
    ).returncode
