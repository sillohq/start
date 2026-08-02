"""Transactional application of operations.

A feature install is a sequence of changes that only makes sense as a whole: a
project left with the dependency installed but the routes unregistered is worse
than one where nothing happened. :class:`Transaction` applies operations in
order, and on failure undoes the ones that succeeded, in reverse.

Rollback is best-effort by necessity — a subprocess may have had effects we
cannot reverse — so failures during rollback are collected and reported rather
than masking the original error.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from ..exceptions import SilloStartError, TransactionError
from ..utils.console import Console
from ..utils.console import console as default_console
from .base import ExecutionContext, Operation, OperationResult, OperationStatus


@dataclass
class TransactionReport:
    """What a finished transaction did."""

    results: list[OperationResult] = field(default_factory=list)
    rolled_back: bool = False
    #: Errors raised while undoing, when rollback itself went wrong.
    rollback_errors: list[str] = field(default_factory=list)
    error: Exception | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def applied(self) -> list[OperationResult]:
        return [r for r in self.results if r.status is OperationStatus.APPLIED]

    @property
    def skipped(self) -> list[OperationResult]:
        return [r for r in self.results if r.status is OperationStatus.SKIPPED]

    @property
    def changed_count(self) -> int:
        return len(self.applied)

    def diffs(self) -> str:
        """Concatenate every diff produced, for ``--dry-run`` output."""
        return "".join(result.diff for result in self.results if result.diff)


class ExecutionPlan:
    """An ordered set of operations, inspectable before anything runs.

    Building the plan separately from executing it is what makes ``--dry-run``
    honest: the same object is what would have been applied.
    """

    def __init__(self, title: str, operations: Sequence[Operation] | None = None) -> None:
        self.title = title
        self.operations: list[Operation] = list(operations or [])

    def add(self, *operations: Operation) -> ExecutionPlan:
        """Append operations, ignoring ``None`` for convenient conditionals."""
        self.operations.extend(op for op in operations if op is not None)
        return self

    def extend(self, operations: Iterable[Operation]) -> ExecutionPlan:
        self.operations.extend(operations)
        return self

    def __len__(self) -> int:
        return len(self.operations)

    def __bool__(self) -> bool:
        return bool(self.operations)

    def __iter__(self):
        return iter(self.operations)

    @property
    def irreversible(self) -> list[Operation]:
        """Operations that cannot be undone if a later step fails."""
        return [op for op in self.operations if not op.reversible]

    def describe(self, context: ExecutionContext) -> list[str]:
        """Render each operation as a plan line."""
        return [operation.describe(context) for operation in self.operations]

    def render(self, context: ExecutionContext, *, console: Console | None = None) -> None:
        """Print the plan."""
        out = console or default_console
        out.print(f"[bold]{self.title}[/bold]")
        for line in self.describe(context):
            out.step(line)
        irreversible = self.irreversible
        if irreversible:
            out.blank()
            out.warning(
                f"{len(irreversible)} step(s) cannot be rolled back automatically:"
            )
            for operation in irreversible:
                out.hint(operation.describe(context))


class Transaction:
    """Applies an :class:`ExecutionPlan`, rolling back on failure."""

    def __init__(
        self,
        plan: ExecutionPlan,
        context: ExecutionContext,
        *,
        console: Console | None = None,
    ) -> None:
        self.plan = plan
        self.context = context
        self.console = console or default_console

    def execute(self, *, show_progress: bool = True) -> TransactionReport:
        """Run every operation in order.

        A failure stops the run, undoes what has been applied so far, and
        re-raises as :class:`TransactionError` with the original error attached
        as ``__cause__``.

        Returns:
            A report of what was applied and skipped.

        Raises:
            TransactionError: If any operation failed.
        """
        report = TransactionReport()

        for operation in self.plan.operations:
            description = operation.describe(self.context)
            try:
                result = operation.apply(self.context)
            except Exception as exc:  # noqa: BLE001 — every failure must roll back
                report.error = exc
                report.results.append(
                    OperationResult(operation, OperationStatus.FAILED, str(exc))
                )
                self.console.blank()
                self.console.failure(f"Failed: {description}")
                self._rollback(report)
                message = exc.message if isinstance(exc, SilloStartError) else str(exc)
                hint = exc.hint if isinstance(exc, SilloStartError) else None
                raise TransactionError(
                    f"{self.plan.title} failed: {message}",
                    hint=hint,
                ) from exc

            report.results.append(result)
            if show_progress and not self.context.dry_run:
                if result.status is OperationStatus.APPLIED:
                    self.console.success(description)
                elif result.status is OperationStatus.SKIPPED and result.detail:
                    self.console.debug(f"skipped: {description} ({result.detail})")

        return report

    def _rollback(self, report: TransactionReport) -> None:
        """Undo applied operations in reverse order, collecting any failures."""
        applied = [r.operation for r in report.results if r.status is OperationStatus.APPLIED]
        if not applied:
            return

        self.console.warning(f"Rolling back {len(applied)} change(s)…")
        for operation in reversed(applied):
            try:
                operation.rollback(self.context)
            except Exception as exc:  # noqa: BLE001 — keep undoing the rest
                message = f"{operation.describe(self.context)}: {exc}"
                report.rollback_errors.append(message)
                self.console.failure(f"Rollback failed for {message}")

        report.rolled_back = True
        for result in report.results:
            if result.status is OperationStatus.APPLIED:
                result.status = OperationStatus.ROLLED_BACK

        if report.rollback_errors:
            self.console.warning(
                "The project may be in an inconsistent state; "
                "run `sillo-start doctor` to check."
            )
        else:
            self.console.success("Rolled back cleanly.")


def execute_plan(
    plan: ExecutionPlan,
    context: ExecutionContext,
    *,
    console: Console | None = None,
    show_progress: bool = True,
) -> TransactionReport:
    """Convenience wrapper: run *plan* under a transaction."""
    return Transaction(plan, context, console=console).execute(show_progress=show_progress)
