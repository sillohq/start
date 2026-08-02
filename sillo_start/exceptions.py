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


class ProjectError(SilloStartError):
    """A project could not be created, located, or read."""


class ProjectExistsError(ProjectError):
    """The target directory already exists and is not empty."""


class ManifestError(SilloStartError):
    """``sillo.toml`` is missing, unreadable, or fails validation."""


class ManifestNotFoundError(ManifestError):
    """No ``sillo.toml`` was found in this directory or any parent."""

    def __init__(
        self,
        message: str = "No sillo.toml found in this directory or any parent.",
        *,
        hint: str | None = "Run this from inside a Sillo project, or create one with `sillo-start create <name>`.",
    ) -> None:
        super().__init__(message, hint=hint)


class BlueprintError(SilloStartError):
    """A blueprint is unknown or produced an invalid plan."""


class PackageGroupError(SilloStartError):
    """A package group is unknown, conflicting, or unsatisfiable."""


class DependencyResolutionError(PackageGroupError):
    """Package group dependencies could not be resolved.

    Raised for unknown requirements, mutual conflicts, and dependency cycles.
    """


class GeneratorError(SilloStartError):
    """A generator is unknown or could not produce its output."""


class OperationError(SilloStartError):
    """A single transaction operation failed while applying."""


class TransactionError(SilloStartError):
    """A transaction failed; the ``__cause__`` carries the originating error."""


class RollbackError(SilloStartError):
    """A rollback failed, which may have left the project inconsistent."""


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


class ValidationError(SilloStartError):
    """User-supplied input failed validation."""

    exit_code = 2


class PluginError(SilloStartError):
    """A third-party plugin failed to load or registered something invalid."""
