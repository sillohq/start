"""Blueprints: named project archetypes.

A blueprint answers two questions: what should the manifest look like for this
kind of application, and which files should exist. Everything else — package
installation, environment files, the manifest write — is shared machinery, so a
new blueprint is a small declarative class rather than a fork of the creator.

:class:`Blueprint` carries a default file set covering the structure every
Sillo project shares. Subclasses usually only set the manifest defaults and add
the handful of files specific to their shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config.defaults import AppType
from ..config.models import SilloManifest


@dataclass(frozen=True)
class FileSpec:
    """One file a blueprint contributes.

    Args:
        template: Template path under ``sillo_start/templates``.
        destination: Path within the project.
        when: Predicate deciding whether the file applies to this manifest.
            Defaults to always.
        executable: Set the execute bit — for generated scripts.
    """

    template: str
    destination: str
    when: str | None = None
    executable: bool = False

    def applies(self, manifest: SilloManifest) -> bool:
        """Evaluate the ``when`` condition against *manifest*.

        A condition is a dotted manifest attribute such as ``"auth.enabled"``,
        or a property name such as ``"uses_record"``. A leading ``!`` negates
        it, and several conditions separated by commas must all hold —
        ``"auth.enabled,auth.routes"``. Keeping conditions declarative, rather
        than letting blueprints pass arbitrary lambdas, means the file set can
        be inspected and explained by ``sillo-start inspect``.
        """
        if self.when is None:
            return True
        return all(self._holds(manifest, part) for part in self.when.split(","))

    @staticmethod
    def _holds(manifest: SilloManifest, expression: str) -> bool:
        """Evaluate one dotted condition, honouring a leading ``!``."""
        expression = expression.strip()
        negate = expression.startswith("!")
        if negate:
            expression = expression[1:]

        value: object = manifest
        for part in expression.split("."):
            value = getattr(value, part, False)
        result = bool(value)
        return not result if negate else result


@dataclass
class Blueprint:
    """A project archetype.

    Args:
        name: Identifier used with ``--blueprint``.
        summary: One-line description for ``create --list-blueprints``.
        app_type: Value written to ``[application] type``.
        groups: Package groups enabled by default.
        description: Longer explanation.
        extra_files: Files added on top of the common set.
        extra_directories: Directories added on top of the common set.
    """

    name: str
    summary: str
    app_type: AppType = AppType.API
    groups: tuple[str, ...] = ()
    description: str = ""
    extra_files: tuple[FileSpec, ...] = ()
    extra_directories: tuple[str, ...] = ()

    #: Files every Sillo project gets. Conditions keep a minimal project from
    #: receiving database or auth scaffolding it did not ask for.
    common_files: tuple[FileSpec, ...] = field(
        default=(
            FileSpec("project/pyproject.toml.j2", "pyproject.toml"),
            FileSpec("project/gitignore.j2", ".gitignore"),
            FileSpec("project/readme.md.j2", "README.md"),
            FileSpec("project/env.j2", ".env.example"),
            FileSpec("project/env.j2", ".env"),
            FileSpec("project/editorconfig.j2", ".editorconfig", when="tooling.editorconfig"),
            FileSpec("app/main.py.j2", "app/main.py"),
            FileSpec("app/bootstrap.py.j2", "app/bootstrap.py"),
            FileSpec("app/config.py.j2", "app/config.py"),
            FileSpec("routes/api.py.j2", "routes/api.py", when="api.enabled"),
            FileSpec("routes/web.py.j2", "routes/web.py", when="needs_web_routes"),
            # Database
            FileSpec("database/config.py.j2", "database/config.py", when="uses_record"),
            FileSpec("database/models_init.py.j2", "database/models/__init__.py", when="uses_record"),
            FileSpec("database/models_user.py.j2", "database/models/user.py", when="auth.enabled"),
            # Auth
            FileSpec("routes/auth.py.j2", "routes/auth.py", when="auth.enabled,auth.routes"),
            # Admin
            FileSpec("app/admin.py.j2", "app/admin.py", when="admin.enabled"),
            # Background work. The framework ships no worker CLI, so these
            # scripts are the entrypoints the orchestrator runs.
            FileSpec("scripts/worker.py.j2", "scripts/worker.py", when="queue.enabled"),
            FileSpec("scripts/jobs_init.py.j2", "app/jobs/__init__.py", when="queue.enabled"),
            FileSpec("scripts/scheduler.py.j2", "scripts/scheduler.py", when="scheduler.enabled"),
            FileSpec("scripts/tasks_init.py.j2", "app/tasks/__init__.py", when="scheduler.enabled"),
            # Tests
            FileSpec("tests/conftest.py.j2", "tests/conftest.py", when="tooling.pytest"),
            FileSpec("tests/test_app.py.j2", "tests/test_app.py", when="tooling.pytest"),
        ),
        repr=False,
    )

    #: Directories every project gets, beyond the ones implied by its files.
    #: Empty by default: a directory earns its place by having something in it.
    common_directories: tuple[str, ...] = field(
        default=(),
        repr=False,
    )

    #: Directories that need an ``__init__.py`` to be importable packages.
    package_directories: tuple[str, ...] = field(
        default=("app", "routes"),
        repr=False,
    )

    def configure(self, manifest: SilloManifest) -> None:
        """Apply this blueprint's defaults to *manifest*.

        Called before the wizard's answers are layered on, so an explicit
        choice always wins over a blueprint default.
        """
        manifest.application.type = self.app_type
        for group in self.groups:
            manifest.add_group(group)

    def files(self, manifest: SilloManifest) -> list[FileSpec]:
        """Return every file this blueprint generates for *manifest*."""
        specs = [*self.common_files, *self.extra_files]
        return [spec for spec in specs if spec.applies(manifest)]

    def directories(self, manifest: SilloManifest) -> list[str]:
        """Return the directories to create beyond those implied by files."""
        directories = [*self.common_directories, *self.extra_directories]
        if manifest.uses_record:
            directories.append(manifest.database.migrations_path)
        if manifest.storage.enabled:
            directories.append(manifest.storage.path)
        if manifest.queue.enabled:
            directories.append("app/jobs")
        if manifest.scheduler.enabled:
            directories.append("app/tasks")
        # Preserve order while removing duplicates.
        return list(dict.fromkeys(directories))

    def python_packages(self, manifest: SilloManifest) -> list[str]:
        """Extra Python requirements this blueprint needs beyond its groups."""
        return []
