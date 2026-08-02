"""Operations that shell out, and that update the manifest."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ..config.models import SilloManifest
from ..config.writer import save_manifest
from ..utils import filesystem as fs
from ..utils.subprocess import run
from .base import ExecutionContext, Operation, OperationResult, OperationStatus


class RunCommand(Operation):
    """Run an external command as part of an installation.

    Side effects of a subprocess cannot be undone in general, so an operation
    that has no meaningful inverse declares ``undo=None`` and marks itself
    irreversible. The transaction reports that up front rather than promising a
    rollback it cannot deliver.
    """

    def __init__(
        self,
        command: Sequence[str],
        *,
        description: str | None = None,
        cwd: str | None = None,
        undo: Sequence[str] | None = None,
        optional: bool = False,
        timeout: int = 600,
    ) -> None:
        """
        Args:
            command: Argument list to execute.
            description: Plan text. Defaults to the command itself.
            cwd: Directory to run in, relative to the project root.
            undo: Command that reverses this one, when one exists.
            optional: Treat a non-zero exit as a warning rather than a failure.
                Used for niceties such as ``git init``.
            timeout: Seconds before the child is killed.
        """
        self.command = list(command)
        self.description = description
        self.cwd = cwd
        self.undo = list(undo) if undo else None
        self.optional = optional
        self.timeout = timeout
        self._ran = False

    @property
    def reversible(self) -> bool:  # type: ignore[override]
        return self.undo is not None

    def describe(self, context: ExecutionContext) -> str:
        return self.description or f"run `{' '.join(self.command)}`"

    def apply(self, context: ExecutionContext) -> OperationResult:
        if context.dry_run:
            return OperationResult(
                self, OperationStatus.APPLIED, f"would run: {' '.join(self.command)}"
            )
        directory = context.resolve(self.cwd) if self.cwd else context.project_root
        result = run(
            self.command,
            cwd=directory,
            check=not self.optional,
            timeout=self.timeout,
        )
        if not result.ok and self.optional:
            return OperationResult(
                self,
                OperationStatus.SKIPPED,
                f"optional command failed (exit {result.returncode})",
            )
        self._ran = True
        return OperationResult(self, OperationStatus.APPLIED, " ".join(self.command))

    def rollback(self, context: ExecutionContext) -> None:
        if not self._ran or not self.undo:
            return
        directory = context.resolve(self.cwd) if self.cwd else context.project_root
        run(self.undo, cwd=directory, check=False, timeout=self.timeout)
        self._ran = False


class UpdateManifest(Operation):
    """Apply a change to ``sillo.toml``.

    The mutation is expressed as a callable so callers describe the change in
    manifest terms — ``m.auth.enabled = True`` — instead of assembling TOML
    edits. The previous file is captured verbatim for rollback.
    """

    def __init__(self, mutate, *, description: str = "update sillo.toml") -> None:
        """
        Args:
            mutate: Callable taking the manifest and modifying it in place.
            description: Plan text describing the change.
        """
        self.mutate = mutate
        self.description = description
        self._previous: str | None = None

    def describe(self, context: ExecutionContext) -> str:
        return self.description

    def apply(self, context: ExecutionContext) -> OperationResult:
        if context.manifest is None:
            return OperationResult(self, OperationStatus.SKIPPED, "no manifest loaded")

        path = manifest_path(context.project_root)
        before = fs.read_text(path) if path.exists() else ""

        self.mutate(context.manifest)

        if context.dry_run:
            return OperationResult(self, OperationStatus.APPLIED, self.description)

        self._previous = before if path.exists() else None
        save_manifest(path, context.manifest)
        after = fs.read_text(path)
        return OperationResult(
            self,
            OperationStatus.APPLIED,
            self.description,
            diff=fs.unified_diff(before, after, path=path.name),
        )

    def rollback(self, context: ExecutionContext) -> None:
        path = manifest_path(context.project_root)
        if self._previous is not None:
            path.write_text(self._previous, encoding="utf-8")
            self._previous = None


class RegisterPackageGroup(Operation):
    """Record a package group as enabled in the manifest."""

    def __init__(self, group: str) -> None:
        self.group = group
        self._added = False

    def describe(self, context: ExecutionContext) -> str:
        return f"enable package group '{self.group}'"

    def apply(self, context: ExecutionContext) -> OperationResult:
        manifest = context.manifest
        if manifest is None:
            return OperationResult(self, OperationStatus.SKIPPED, "no manifest loaded")
        if manifest.has_group(self.group):
            return OperationResult(self, OperationStatus.SKIPPED, "already enabled")

        manifest.add_group(self.group)
        self._added = True
        if not context.dry_run:
            save_manifest(manifest_path(context.project_root), manifest)
        return OperationResult(self, OperationStatus.APPLIED, self.group)

    def rollback(self, context: ExecutionContext) -> None:
        if self._added and context.manifest is not None:
            context.manifest.remove_group(self.group)
            save_manifest(manifest_path(context.project_root), context.manifest)
            self._added = False


def manifest_path(project_root: Path) -> Path:
    """Return the manifest path for *project_root*.

    Prefers ``pyproject.toml`` when it carries a ``[tool.sillo]`` table, so
    updates land where the project already keeps its manifest. Falls back to a
    standalone ``sillo.toml`` — existing, and for projects with no pyproject.
    """
    from ..config.loader import find_manifest

    found = find_manifest(project_root)
    if found is not None and found.parent == project_root:
        return found
    return project_root / "sillo.toml"


def load_context_manifest(project_root: Path) -> SilloManifest | None:
    """Load the manifest for *project_root*, or ``None`` when absent."""
    from ..config.loader import load_manifest

    path = manifest_path(project_root)
    return load_manifest(path) if path.exists() else None
