"""Exception hierarchy for Sillo Start.

Every error the tool raises on purpose derives from :class:`SilloStartError`.
The CLI layer catches that base class and renders a clean message with an exit
code, so a user never sees a traceback unless they pass ``--verbose``.

Each exception carries an optional ``hint`` — a concrete next action. Error
messages that only say what went wrong make the user guess; the hint is where
we tell them what to type.
"""

from __future__ import annotations


class SilloStartError(Exception):
    """Base class for all deliberate Sillo Start failures.

    Args:
        message: What went wrong, in one sentence.
        hint: An optional concrete remedy shown beneath the error.
        exit_code: Process exit code the CLI should use.
    """

    exit_code: int = 1

    def __init__(
        self,
        message: str,
        *,
        hint: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        if exit_code is not None:
            self.exit_code = exit_code


class UsageError(SilloStartError):
    """The command was invoked with an invalid combination of arguments."""

    exit_code = 2


class CommandError(SilloStartError):
    """An external command exited non-zero.

    The captured output is kept on the exception so the CLI can show it — Sillo
    Start never silently swallows subprocess output.
    """

    def __init__(
        self,
        message: str,
        *,
        command: list[str] | None = None,
        returncode: int | None = None,
        output: str | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message, hint=hint)
        self.command = command or []
        self.returncode = returncode
        self.output = output


class ToolNotFoundError(SilloStartError):
    """A required external tool is not installed or not on ``PATH``."""
