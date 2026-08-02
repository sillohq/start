"""File and directory operations.

These are the operations that touch developer code, so they are the most
conservative in the system: a write that would replace existing content either
skips, fails, or produces a diff — never a silent clobber.
"""

from __future__ import annotations

from pathlib import Path

from ..exceptions import OperationError
from ..utils import filesystem as fs
from ..utils.environment import EnvFile, EnvVar
from .base import ExecutionContext, Operation, OperationResult, OperationStatus

#: Delimiters for regions of a file that Sillo Start owns and may rewrite.
#: Content outside the markers is the developer's and is never touched.
MARKER_BEGIN = "# >>> sillo-start: {name} >>>"
MARKER_END = "# <<< sillo-start: {name} <<<"


class CreateDirectory(Operation):
    """Create a directory, and its parents, if it is not already there."""

    def __init__(self, path: str | Path, *, keep: bool = False) -> None:
        """
        Args:
            path: Directory to create, relative to the project root.
            keep: Also write a ``.gitkeep`` so the empty directory survives a
                commit — used for ``storage/`` and ``migrations/``.
        """
        self.path = path
        self.keep = keep
        self._created: list[Path] = []

    def describe(self, context: ExecutionContext) -> str:
        return f"create directory {context.relative(context.resolve(self.path))}/"

    def apply(self, context: ExecutionContext) -> OperationResult:
        target = context.resolve(self.path)
        if target.is_dir() and not (self.keep and not (target / ".gitkeep").exists()):
            return OperationResult(self, OperationStatus.SKIPPED, "already exists")

        if not context.dry_run:
            # Record which parents we create so rollback removes exactly those
            # and leaves pre-existing directories alone.
            missing = []
            probe = target
            while not probe.exists() and probe != probe.parent:
                missing.append(probe)
                probe = probe.parent
            self._created = missing
            fs.ensure_dir(target)
            if self.keep:
                keepfile = target / ".gitkeep"
                if not keepfile.exists():
                    keepfile.write_text("", encoding="utf-8")
        return OperationResult(self, OperationStatus.APPLIED, context.relative(target))

    def rollback(self, context: ExecutionContext) -> None:
        if self.keep:
            keepfile = context.resolve(self.path) / ".gitkeep"
            keepfile.unlink(missing_ok=True)
        for directory in self._created:
            # Only remove directories we created and that are still empty —
            # another operation may have legitimately filled one.
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
        self._created = []


class CreateFile(Operation):
    """Write a file.

    An existing file is skipped by default rather than overwritten, because it
    may contain code the developer wrote. ``overwrite=True`` opts into
    replacement and captures the previous bytes for rollback.
    """

    def __init__(
        self,
        path: str | Path,
        content: str,
        *,
        overwrite: bool = False,
        skip_if_exists: bool = True,
        executable: bool = False,
    ) -> None:
        """
        Args:
            path: Destination, relative to the project root.
            content: File contents.
            overwrite: Replace an existing file, keeping a copy for rollback.
            skip_if_exists: Treat an existing file as a no-op. When both this
                and *overwrite* are false, an existing file is an error.
            executable: Set the owner-execute bit, for generated scripts.
        """
        self.path = path
        self.content = content
        self.overwrite = overwrite
        self.skip_if_exists = skip_if_exists
        self.executable = executable
        self._previous: str | None = None
        self._existed = False

    def describe(self, context: ExecutionContext) -> str:
        target = context.resolve(self.path)
        verb = "update" if target.exists() and self.overwrite else "create"
        return f"{verb} {context.relative(target)}"

    def apply(self, context: ExecutionContext) -> OperationResult:
        target = context.resolve(self.path)
        self._existed = target.exists()

        if self._existed:
            current = fs.read_text(target)
            if current == self._normalised():
                return OperationResult(self, OperationStatus.SKIPPED, "unchanged")
            if not self.overwrite and not context.force:
                if self.skip_if_exists:
                    return OperationResult(
                        self, OperationStatus.SKIPPED, "exists, left untouched"
                    )
                raise OperationError(
                    f"Refusing to overwrite {context.relative(target)}",
                    hint="Pass --force to replace it.",
                )
            self._previous = current

        diff = self.preview(context)
        if not context.dry_run:
            fs.write_text(target, self.content, overwrite=True)
            if self.executable:
                target.chmod(target.stat().st_mode | 0o111)
        return OperationResult(
            self, OperationStatus.APPLIED, context.relative(target), diff=diff
        )

    def rollback(self, context: ExecutionContext) -> None:
        target = context.resolve(self.path)
        if self._previous is not None:
            target.write_text(self._previous, encoding="utf-8")
        elif not self._existed:
            target.unlink(missing_ok=True)
        self._previous = None

    def preview(self, context: ExecutionContext) -> str:
        target = context.resolve(self.path)
        before = fs.read_text(target) if target.exists() else ""
        return fs.unified_diff(before, self._normalised(), path=context.relative(target))

    def _normalised(self) -> str:
        """The content as it will land on disk, with a trailing newline."""
        if self.content and not self.content.endswith("\n"):
            return self.content + "\n"
        return self.content


class DeleteFile(Operation):
    """Remove a file, keeping its contents so the deletion can be undone."""

    def __init__(self, path: str | Path) -> None:
        self.path = path
        self._previous: str | None = None

    def describe(self, context: ExecutionContext) -> str:
        return f"delete {context.relative(context.resolve(self.path))}"

    def apply(self, context: ExecutionContext) -> OperationResult:
        target = context.resolve(self.path)
        if not target.exists():
            return OperationResult(self, OperationStatus.SKIPPED, "not present")
        self._previous = fs.read_text(target)
        if not context.dry_run:
            target.unlink()
        return OperationResult(self, OperationStatus.APPLIED, context.relative(target))

    def rollback(self, context: ExecutionContext) -> None:
        if self._previous is not None:
            fs.write_text(context.resolve(self.path), self._previous, overwrite=True)
            self._previous = None


class UpdateMarkerSection(Operation):
    """Replace a delimited region of a file that Sillo Start owns.

    Some files — a routes module, a settings file — need a block the tool can
    regenerate while the rest stays under the developer's control. The block is
    fenced with begin/end markers; only what is between them is rewritten, and
    a missing block is appended.
    """

    def __init__(
        self,
        path: str | Path,
        name: str,
        content: str,
        *,
        comment_prefix: str = "#",
    ) -> None:
        """
        Args:
            path: File to edit.
            name: Marker identifier, unique within the file.
            content: Replacement body for the region.
            comment_prefix: Comment syntax for the target language, so the
                markers stay valid in TypeScript and YAML as well as Python.
        """
        self.path = path
        self.name = name
        self.content = content
        self.comment_prefix = comment_prefix
        self._previous: str | None = None

    @property
    def begin(self) -> str:
        return MARKER_BEGIN.format(name=self.name).replace("#", self.comment_prefix, 1)

    @property
    def end(self) -> str:
        return MARKER_END.format(name=self.name).replace("#", self.comment_prefix, 1)

    def describe(self, context: ExecutionContext) -> str:
        return (
            f"update '{self.name}' section in "
            f"{context.relative(context.resolve(self.path))}"
        )

    def apply(self, context: ExecutionContext) -> OperationResult:
        target = context.resolve(self.path)
        before = fs.read_text(target) if target.exists() else ""
        after = self._rewrite(before)
        if before == after:
            return OperationResult(self, OperationStatus.SKIPPED, "unchanged")
        self._previous = before if target.exists() else None
        diff = fs.unified_diff(before, after, path=context.relative(target))
        if not context.dry_run:
            fs.write_text(target, after, overwrite=True)
        return OperationResult(
            self, OperationStatus.APPLIED, context.relative(target), diff=diff
        )

    def rollback(self, context: ExecutionContext) -> None:
        target = context.resolve(self.path)
        if self._previous is not None:
            target.write_text(self._previous, encoding="utf-8")
        else:
            target.unlink(missing_ok=True)
        self._previous = None

    def _rewrite(self, text: str) -> str:
        """Replace the marked block, or append one when absent."""
        block = f"{self.begin}\n{self.content.rstrip()}\n{self.end}"
        if self.begin in text and self.end in text:
            head, _, rest = text.partition(self.begin)
            _, _, tail = rest.partition(self.end)
            return f"{head}{block}{tail}"
        separator = "\n\n" if text.strip() else ""
        return f"{text.rstrip()}{separator}{block}\n" if text.strip() else f"{block}\n"


class UpdateEnvironment(Operation):
    """Add environment variables to a ``.env``-style file.

    Existing keys are left alone: a developer's real database password must
    survive ``sillo-start add``.
    """

    def __init__(
        self,
        path: str | Path,
        variables: list[EnvVar],
        *,
        section: str | None = None,
    ) -> None:
        """
        Args:
            path: The dotenv file to update.
            variables: Variables to add when not already present.
            section: Optional heading, written above the new block.
        """
        self.path = path
        self.variables = variables
        self.section = section
        self._previous: str | None = None
        self._existed = False

    def describe(self, context: ExecutionContext) -> str:
        keys = ", ".join(var.key for var in self.variables)
        return f"set {keys} in {context.relative(context.resolve(self.path))}"

    def apply(self, context: ExecutionContext) -> OperationResult:
        target = context.resolve(self.path)
        self._existed = target.exists()
        before = fs.read_text(target) if self._existed else ""

        env = EnvFile.parse(before)
        added = [var for var in self.variables if not env.has(var.key)]
        if not added:
            return OperationResult(self, OperationStatus.SKIPPED, "all variables present")

        if self.section:
            env.add_section(self.section, added)
        else:
            for var in added:
                env.set(var.key, var.value, comment=var.comment)

        after = env.render()
        self._previous = before if self._existed else None
        diff = fs.unified_diff(before, after, path=context.relative(target))
        if not context.dry_run:
            env.save(target)
        return OperationResult(
            self,
            OperationStatus.APPLIED,
            ", ".join(var.key for var in added),
            diff=diff,
        )

    def rollback(self, context: ExecutionContext) -> None:
        target = context.resolve(self.path)
        if self._previous is not None:
            target.write_text(self._previous, encoding="utf-8")
        elif not self._existed:
            target.unlink(missing_ok=True)
        self._previous = None
