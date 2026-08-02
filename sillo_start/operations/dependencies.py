"""Operations that change a project's declared dependencies."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from ..exceptions import OperationError
from ..utils import filesystem as fs
from ..utils import toml_io
from ..utils.pkgmanagers import (
    FrontendPackageManager,
    PythonPackageManager,
    frontend_manager,
)
from .base import ExecutionContext, Operation, OperationResult, OperationStatus


class UpdateToml(Operation):
    """Set values in a TOML file without disturbing the rest of it.

    Used for ``pyproject.toml`` and any other TOML the project owns. Edits go
    through tomlkit, so comments and key order survive.
    """

    def __init__(
        self,
        path: str | Path,
        values: dict[str, object] | None = None,
        *,
        append: dict[str, list[str]] | None = None,
        remove: dict[str, list[str]] | None = None,
    ) -> None:
        """
        Args:
            path: TOML file to edit.
            values: Dotted-key assignments, e.g. ``{"project.version": "0.2.0"}``.
            append: Entries to add to arrays, keyed by dotted path.
            remove: Entries to drop from arrays, keyed by dotted path.
        """
        self.path = path
        self.values = values or {}
        self.append = append or {}
        self.remove = remove or {}
        self._previous: str | None = None

    def describe(self, context: ExecutionContext) -> str:
        target = context.relative(context.resolve(self.path))
        changes: list[str] = []
        if self.values:
            changes.append(", ".join(self.values))
        for dotted, items in self.append.items():
            changes.append(f"+{len(items)} to {dotted}")
        for dotted, items in self.remove.items():
            changes.append(f"-{len(items)} from {dotted}")
        return f"update {target} ({'; '.join(changes)})"

    def apply(self, context: ExecutionContext) -> OperationResult:
        target = context.resolve(self.path)
        if not target.exists():
            raise OperationError(
                f"Cannot update missing TOML file: {context.relative(target)}"
            )

        before = fs.read_text(target)
        document = toml_io.parse(before)

        touched: list[str] = []
        for dotted, value in self.values.items():
            toml_io.set_path(document, dotted, value)
            touched.append(dotted)
        for dotted, items in self.append.items():
            added = toml_io.add_to_array(document, dotted, list(items))
            touched.extend(added)
        for dotted, items in self.remove.items():
            dropped = toml_io.remove_from_array(document, dotted, list(items))
            touched.extend(dropped)

        after = toml_io.dump(document)
        if after == before:
            return OperationResult(self, OperationStatus.SKIPPED, "no change")

        self._previous = before
        diff = fs.unified_diff(before, after, path=context.relative(target))
        if not context.dry_run:
            target.write_text(after, encoding="utf-8")
        return OperationResult(
            self, OperationStatus.APPLIED, ", ".join(touched), diff=diff
        )

    def rollback(self, context: ExecutionContext) -> None:
        if self._previous is not None:
            context.resolve(self.path).write_text(self._previous, encoding="utf-8")
            self._previous = None


class UpdateJson(Operation):
    """Merge values into a JSON file, preserving unrelated keys.

    Used for ``package.json`` and ``tsconfig.json``. Nested dicts are merged
    rather than replaced, so adding one script does not drop the others.
    """

    def __init__(self, path: str | Path, values: dict, *, indent: int = 2) -> None:
        self.path = path
        self.values = values
        self.indent = indent
        self._previous: str | None = None
        self._existed = False

    def describe(self, context: ExecutionContext) -> str:
        keys = ", ".join(self.values)
        return f"update {context.relative(context.resolve(self.path))} ({keys})"

    def apply(self, context: ExecutionContext) -> OperationResult:
        target = context.resolve(self.path)
        self._existed = target.exists()
        before = fs.read_text(target) if self._existed else "{}"
        try:
            data = json.loads(before) if before.strip() else {}
        except json.JSONDecodeError as exc:
            raise OperationError(
                f"Invalid JSON in {context.relative(target)}: {exc}"
            ) from exc

        merged = _deep_merge(data, self.values)
        after = json.dumps(merged, indent=self.indent) + "\n"
        if after == before:
            return OperationResult(self, OperationStatus.SKIPPED, "no change")

        self._previous = before if self._existed else None
        diff = fs.unified_diff(before, after, path=context.relative(target))
        if not context.dry_run:
            fs.write_text(target, after, overwrite=True)
        return OperationResult(self, OperationStatus.APPLIED, ", ".join(self.values), diff=diff)

    def rollback(self, context: ExecutionContext) -> None:
        target = context.resolve(self.path)
        if self._previous is not None:
            target.write_text(self._previous, encoding="utf-8")
        elif not self._existed:
            target.unlink(missing_ok=True)
        self._previous = None


class InstallPythonPackage(Operation):
    """Declare and install Python dependencies.

    With ``uv`` the tool records the dependency in ``pyproject.toml`` itself,
    so this operation only runs the command. With ``pip`` — which records
    nothing — the requirement is written into ``pyproject.toml`` first, so the
    project stays reproducible either way.
    """

    def __init__(
        self,
        packages: Sequence[str],
        *,
        manager: PythonPackageManager,
        group: str | None = None,
        install: bool = True,
    ) -> None:
        """
        Args:
            packages: PEP 508 requirement strings.
            manager: Adapter that knows how to phrase the install.
            group: Optional dependency group, e.g. ``dev``.
            install: Run the installer. When false the dependency is only
                declared, which is what project creation does before the
                environment exists.
        """
        self.packages = list(packages)
        self.manager = manager
        self.group = group
        self.install = install
        self._declared: list[str] = []

    #: Uninstalling can break an environment in ways we cannot reliably undo,
    #: so a failed transaction reverts the manifest and says so.
    reversible = True

    def describe(self, context: ExecutionContext) -> str:
        target = f" into '{self.group}'" if self.group else ""
        verb = "install" if self.install else "declare"
        return f"{verb} {', '.join(self.packages)}{target}"

    def apply(self, context: ExecutionContext) -> OperationResult:
        if not self.packages:
            return OperationResult(self, OperationStatus.SKIPPED, "nothing to install")

        dotted = (
            f"project.optional-dependencies.{self.group}"
            if self.group
            else "project.dependencies"
        )

        if context.dry_run:
            return OperationResult(
                self, OperationStatus.APPLIED, f"would add {', '.join(self.packages)}"
            )

        if self.manager.name == "uv" and self.install:
            self.manager.add(self.packages, cwd=context.project_root, group=self.group)
            return OperationResult(self, OperationStatus.APPLIED, ", ".join(self.packages))

        # Declare in pyproject.toml ourselves, then install if asked.
        pyproject = context.project_root / "pyproject.toml"
        if pyproject.exists():
            document = toml_io.load(pyproject)
            self._declared = toml_io.add_to_array(document, dotted, self.packages)
            toml_io.save(pyproject, document)
        if self.install:
            self.manager.add(self.packages, cwd=context.project_root, group=self.group)
        return OperationResult(self, OperationStatus.APPLIED, ", ".join(self.packages))

    def rollback(self, context: ExecutionContext) -> None:
        """Undo the declaration.

        The installed distribution is deliberately left in the environment:
        removing it could break an unrelated package that depends on it, and a
        stray installed package is far less harmful than a broken environment.
        """
        pyproject = context.project_root / "pyproject.toml"
        if not self._declared or not pyproject.exists():
            return
        dotted = (
            f"project.optional-dependencies.{self.group}"
            if self.group
            else "project.dependencies"
        )
        document = toml_io.load(pyproject)
        toml_io.remove_from_array(document, dotted, self._declared)
        toml_io.save(pyproject, document)
        self._declared = []


class InstallFrontendPackage(Operation):
    """Add JavaScript dependencies to the frontend project.

    Entries are written into ``package.json`` rather than installed one by one,
    so a single ``install`` at the end resolves everything together.
    """

    def __init__(
        self,
        packages: Sequence[str],
        *,
        directory: str,
        dev: bool = False,
        manager: FrontendPackageManager | None = None,
        install: bool = False,
    ) -> None:
        self.packages = list(packages)
        self.directory = directory
        self.dev = dev
        self.manager = manager
        self.install = install
        self._added: list[str] = []

    def describe(self, context: ExecutionContext) -> str:
        kind = "dev dependencies" if self.dev else "dependencies"
        return f"add {len(self.packages)} frontend {kind} to {self.directory}/package.json"

    def apply(self, context: ExecutionContext) -> OperationResult:
        if not self.packages:
            return OperationResult(self, OperationStatus.SKIPPED, "nothing to add")

        package_json = context.resolve(self.directory) / "package.json"
        key = "devDependencies" if self.dev else "dependencies"

        if context.dry_run:
            return OperationResult(
                self, OperationStatus.APPLIED, f"would add {', '.join(self.packages)}"
            )

        data = json.loads(fs.read_text(package_json)) if package_json.exists() else {}
        section = data.setdefault(key, {})
        for spec in self.packages:
            name, version = _split_npm_spec(spec)
            if name not in section:
                section[name] = version
                self._added.append(name)

        if not self._added:
            return OperationResult(self, OperationStatus.SKIPPED, "already declared")

        fs.write_text(package_json, json.dumps(data, indent=2), overwrite=True)

        if self.install:
            manager = self.manager or frontend_manager("npm")
            manager.install(cwd=package_json.parent)
        return OperationResult(self, OperationStatus.APPLIED, ", ".join(self._added))

    def rollback(self, context: ExecutionContext) -> None:
        package_json = context.resolve(self.directory) / "package.json"
        if not self._added or not package_json.exists():
            return
        key = "devDependencies" if self.dev else "dependencies"
        data = json.loads(fs.read_text(package_json))
        for name in self._added:
            data.get(key, {}).pop(name, None)
        fs.write_text(package_json, json.dumps(data, indent=2), overwrite=True)
        self._added = []


def _split_npm_spec(spec: str) -> tuple[str, str]:
    """Split ``react@^18.0.0`` into its name and version range.

    A scoped package such as ``@inertiajs/react`` starts with ``@``, so the
    separator search skips the first character. A spec with no version gets
    ``latest``, which is what the package manager resolves on install.
    """
    if "@" in spec[1:]:
        index = spec.index("@", 1)
        return spec[:index], spec[index + 1 :]
    return spec, "latest"


def _deep_merge(base: dict, updates: dict) -> dict:
    """Merge *updates* into *base*, recursing into nested dicts."""
    result = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
