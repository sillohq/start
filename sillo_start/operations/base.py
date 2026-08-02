"""The operation protocol.

Every change Sillo Start makes to a project is expressed as an
:class:`Operation`: a small, named, reversible unit of work. Installing a
feature then becomes a list of operations that a :class:`~.transaction.Transaction`
applies in order and undoes in reverse if anything fails.

Structuring mutation this way buys three things that ad-hoc code cannot give:
a plan that can be shown before anything happens, a genuine ``--dry-run``, and
rollback that restores the previous bytes rather than guessing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..config.models import SilloManifest


class OperationStatus(str, Enum):
    """Outcome of applying one operation."""

    PENDING = "pending"
    APPLIED = "applied"
    #: The operation was a no-op — the change was already in place. Skipped
    #: operations are not rolled back, since undoing them would remove state
    #: the operation did not create.
    SKIPPED = "skipped"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class ExecutionContext:
    """Everything an operation needs to know about where it is running.

    Args:
        project_root: Directory that relative operation paths resolve against.
        manifest: The project manifest, when one exists. Operations may read it
            and, for manifest operations, replace it.
        dry_run: Describe changes without performing them.
        force: Permit overwriting files that already exist.
        variables: Free-form values shared between operations in one
            transaction — a generated secret, a resolved package manager.
    """

    project_root: Path
    manifest: SilloManifest | None = None
    dry_run: bool = False
    force: bool = False
    variables: dict[str, Any] = field(default_factory=dict)

    def resolve(self, path: str | Path) -> Path:
        """Resolve *path* against the project root.

        Absolute paths pass through, so an operation can target a location
        outside the project when it genuinely needs to.
        """
        candidate = Path(path)
        return candidate if candidate.is_absolute() else self.project_root / candidate

    def relative(self, path: Path) -> str:
        """Render *path* relative to the project root, for display."""
        try:
            return str(path.relative_to(self.project_root))
        except ValueError:
            return str(path)


@dataclass
class OperationResult:
    """What an operation did, for reporting and for the rollback decision."""

    operation: Operation
    status: OperationStatus
    detail: str = ""
    #: Unified diff of the change, populated when the operation can produce one.
    diff: str = ""

    @property
    def changed(self) -> bool:
        """Whether this operation actually modified anything."""
        return self.status is OperationStatus.APPLIED


class Operation(ABC):
    """A single reversible change to a project.

    Subclasses implement :meth:`apply` and, when the change is undoable,
    :meth:`rollback`. :meth:`describe` provides the one-line summary shown in
    the execution plan, and should read as an instruction rather than a class
    name — "create app/main.py", not "CreateFile".
    """

    #: Set by subclasses whose effects cannot be undone, so the transaction can
    #: warn before it starts rather than discovering it mid-rollback.
    reversible: bool = True

    @abstractmethod
    def describe(self, context: ExecutionContext) -> str:
        """Return the one-line plan entry for this operation."""

    @abstractmethod
    def apply(self, context: ExecutionContext) -> OperationResult:
        """Perform the change.

        Implementations must honour ``context.dry_run`` by computing the result
        — including any diff — without touching the filesystem or running
        commands.

        Raises:
            OperationError: If the change cannot be made.
        """

    def rollback(self, context: ExecutionContext) -> None:
        """Undo the change.

        Only called for operations that reported
        :attr:`OperationStatus.APPLIED`. The default is a no-op, which is
        correct for operations that change nothing observable.
        """
        return None

    def preview(self, context: ExecutionContext) -> str:
        """Return a diff of the pending change, or an empty string.

        Used by ``--dry-run`` to show file-level detail beneath the plan.
        """
        return ""

    def __repr__(self) -> str:
        return f"<{type(self).__name__}>"


class CompositeOperation(Operation):
    """An operation made of other operations, applied as one unit.

    Useful for a feature step that is naturally several changes — create the
    directory, write the module, register the route — that should appear in the
    plan as one line and roll back together.
    """

    def __init__(self, description: str, operations: list[Operation]) -> None:
        self.description = description
        self.operations = operations
        self._applied: list[Operation] = []

    @property
    def reversible(self) -> bool:  # type: ignore[override]
        return all(operation.reversible for operation in self.operations)

    def describe(self, context: ExecutionContext) -> str:
        return self.description

    def apply(self, context: ExecutionContext) -> OperationResult:
        self._applied = []
        details = []
        for operation in self.operations:
            result = operation.apply(context)
            if result.status is OperationStatus.APPLIED:
                self._applied.append(operation)
                details.append(result.detail)
        status = OperationStatus.APPLIED if self._applied else OperationStatus.SKIPPED
        return OperationResult(self, status, detail="; ".join(filter(None, details)))

    def rollback(self, context: ExecutionContext) -> None:
        for operation in reversed(self._applied):
            operation.rollback(context)
        self._applied = []

    def preview(self, context: ExecutionContext) -> str:
        return "".join(operation.preview(context) for operation in self.operations)
