"""Creating a new project.

The creator turns a manifest into an execution plan and runs it under a
transaction. Nothing is written outside that plan, so ``--dry-run`` shows
exactly what would happen and a failure part-way through leaves no half-built
directory behind.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .. import __version__
from ..blueprints.base import Blueprint
from ..config.defaults import (
    DATABASE_URL_TEMPLATES,
    REQUIRED_SILLO_EXTRAS,
    DatabaseDriver,
)
from ..config.models import SilloManifest
from ..config.writer import render_manifest_table
from ..exceptions import ProjectExistsError
from ..operations.base import ExecutionContext
from ..operations.files import CreateDirectory, CreateFile
from ..operations.transaction import ExecutionPlan, TransactionReport, execute_plan
from ..packages import registry as package_registry
from ..packages.installer import database_driver_packages, sillo_requirement
from ..packages.resolver import Resolution, resolve
from ..templating import TemplateEngine, build_context
from ..templating import engine as default_engine
from ..utils import filesystem as fs
from ..utils.console import Console
from ..utils.console import console as default_console
from ..utils.environment import generate_secret_key
from . import structure


@dataclass
class CreationResult:
    """What ``create`` produced."""

    root: Path
    manifest: SilloManifest
    resolution: Resolution
    report: TransactionReport
    next_steps: list[str] = field(default_factory=list)
    urls: dict[str, str] = field(default_factory=dict)


class ProjectCreator:
    """Builds a new project from a manifest and a blueprint."""

    def __init__(
        self,
        *,
        engine: TemplateEngine | None = None,
        console: Console | None = None,
    ) -> None:
        self.engine = engine or default_engine
        self.console = console or default_console

    def create(
        self,
        root: Path,
        manifest: SilloManifest,
        blueprint: Blueprint,
        *,
        dry_run: bool = False,
        force: bool = False,
        install: bool = False,
        git: bool = True,
    ) -> CreationResult:
        """Create the project at *root*.

        Args:
            root: Target directory. Created if missing.
            manifest: The project configuration, already merged from blueprint
                defaults and user answers.
            blueprint: Blueprint supplying the file set.
            dry_run: Plan without writing.
            force: Permit creating into a non-empty directory.
            install: Run the package manager after generating.
            git: Initialise a git repository.

        Returns:
            The creation result, including the next steps to show the user.

        Raises:
            ProjectExistsError: If *root* is non-empty and *force* is not set.
            TransactionError: If any step fails; the project is rolled back.
        """
        self._check_target(root, force=force)

        manifest.project.created_with = __version__
        resolution = self._resolve_groups(manifest)
        plan = self.build_plan(root, manifest, blueprint, resolution, install=install, git=git)

        context = ExecutionContext(
            project_root=root,
            manifest=manifest,
            dry_run=dry_run,
            force=force,
        )
        report = execute_plan(plan, context, console=self.console, show_progress=False)

        return CreationResult(
            root=root,
            manifest=manifest,
            resolution=resolution,
            report=report,
            next_steps=self.next_steps(manifest, installed=install),
            urls=self.service_urls(manifest),
        )

    # -- planning ------------------------------------------------------

    def build_plan(
        self,
        root: Path,
        manifest: SilloManifest,
        blueprint: Blueprint,
        resolution: Resolution,
        *,
        install: bool = False,
        git: bool = True,
    ) -> ExecutionPlan:
        """Build the full creation plan.

        The order is deliberate: directories, then package markers, then files,
        then the manifest. Dependency installation comes last so a resolution
        failure does not leave a directory of files behind.
        """
        plan = ExecutionPlan(f"Create project '{manifest.project.name}'")
        context = build_context(manifest, **self._extra_context(manifest, resolution))

        directories = structure.directories_for(
            manifest, extra=[*blueprint.directories(manifest), *resolution.directories()]
        )
        for directory in directories:
            plan.add(CreateDirectory(directory, keep=structure.should_keep_empty(directory)))

        specs = blueprint.files(manifest)
        # A blueprint that ships its own __init__.py for a package — the models
        # registry, say — must win over the placeholder one. Writes skip files
        # that already exist, so the placeholder has to be left out entirely
        # rather than merely ordered after it.
        templated = {spec.destination for spec in specs}
        for package in structure.package_directories(directories):
            init_file = f"{package}/__init__.py"
            if init_file not in templated:
                plan.add(
                    CreateFile(
                        init_file,
                        structure.init_file_content(package),
                        skip_if_exists=True,
                    )
                )

        for spec in specs:
            plan.add(
                CreateFile(
                    spec.destination,
                    self.engine.render(spec.template, context),
                    skip_if_exists=True,
                    executable=spec.executable,
                )
            )

        plan.extend(self._feature_operations(root, manifest, install=install))

        # The manifest goes into pyproject.toml under [tool.sillo] — see the
        # sillo_manifest context value, rendered into the pyproject template.
        # No standalone sillo.toml is written; the loader still reads one if a
        # project has it.

        plan.extend(self._tooling_operations(manifest, context))
        plan.extend(self._post_operations(root, manifest, install=install, git=git))
        return plan

    def _feature_operations(
        self, root: Path, manifest: SilloManifest, *, install: bool
    ) -> list:
        """Operations contributed by features with their own installers.

        Inertia scaffolds a whole frontend project, which is far more than a
        file list. Delegating to the same installer ``sillo-start add inertia``
        uses means a project created with an Inertia blueprint and one that
        added Inertia later end up identical.
        """
        operations: list = []
        if manifest.inertia.enabled:
            from ..config.defaults import InertiaAdapter
            from ..features.inertia import build_plan as build_inertia_plan

            inertia_plan = build_inertia_plan(
                root,
                manifest,
                adapter=InertiaAdapter(manifest.inertia.adapter),
                install=install,
            )
            # Dependencies and the manifest update are already handled by the
            # creation plan, so only the file scaffolding is taken from here.
            operations.extend(
                operation
                for operation in inertia_plan.operations
                if type(operation).__name__ in ("CreateFile", "CreateDirectory", "RunCommand")
            )
        return operations

    def _extra_context(self, manifest: SilloManifest, resolution: Resolution) -> dict:
        """Values the templates need that are not on the manifest."""
        dependencies, dev_dependencies = self.dependencies(manifest, resolution)
        return {
            "dependencies": dependencies,
            "dev_dependencies": dev_dependencies,
            "database_url": self.database_url(manifest),
            "secret_key": generate_secret_key(),
            "jwt_secret": generate_secret_key(),
            "routers": self.routers(manifest),
            "resolution": resolution,
            # Rendered into pyproject.toml as [tool.sillo.*] rather than written
            # to a separate sillo.toml, so the project's name and version are
            # stated once.
            "sillo_manifest": render_manifest_table(manifest),
        }

    def dependencies(
        self, manifest: SilloManifest, resolution: Resolution
    ) -> tuple[list[str], list[str]]:
        """Compute the project's declared dependencies.

        The framework itself is one requirement carrying the union of every
        enabled group's extras, rather than one line per group — pip would
        otherwise see several requirements for the same distribution.
        """
        extras = sorted({*resolution.sillo_extras(), *REQUIRED_SILLO_EXTRAS})
        dependencies = [sillo_requirement(extras, manifest.project.sillo_version)]
        dependencies.extend(resolution.python_packages())
        # Tortoise is reachable from `import sillo` whatever the project does,
        # so its driver is needed even by a project with no database of its own.
        driver = manifest.database.driver if manifest.database.enabled else DatabaseDriver.SQLITE
        dependencies.extend(database_driver_packages(driver))

        dev_dependencies = list(resolution.dev_packages())
        if manifest.tooling.ruff and "ruff>=0.6.0" not in dev_dependencies:
            dev_dependencies.append("ruff>=0.6.0")
        if manifest.tooling.mypy:
            dev_dependencies.append("mypy>=1.15.0")
        if manifest.tooling.pytest and not any(d.startswith("pytest") for d in dev_dependencies):
            dev_dependencies.extend(["pytest>=8.3.5", "pytest-asyncio>=0.25.3", "httpx>=0.28.1"])

        return list(dict.fromkeys(dependencies)), list(dict.fromkeys(dev_dependencies))

    def database_url(self, manifest: SilloManifest) -> str:
        """Build the default connection URL for the configured backend."""
        if not manifest.database.enabled:
            return ""
        template = DATABASE_URL_TEMPLATES.get(DatabaseDriver(manifest.database.driver), "")
        return template.format(name=manifest.project.package)

    def routers(self, manifest: SilloManifest) -> list[tuple[str, str, str]]:
        """List the routers ``bootstrap`` should mount, as (module, alias, prefix).

        The list is ordered by descending prefix length, which is load-bearing
        rather than cosmetic: a router mounted at ``/api`` claims that entire
        subtree, so a router at ``/api/auth`` mounted after it would never be
        reached. Mounting the most specific prefix first is what keeps both
        routable.

        Each module exports ``router``, so the imports are aliased to avoid
        colliding in the bootstrap namespace.
        """
        prefix = manifest.api.prefix.rstrip("/")
        routers: list[tuple[str, str, str]] = []

        if manifest.api.enabled:
            routers.append(("api", "api_router", prefix))
        if manifest.auth.enabled and manifest.auth.routes:
            routers.append(("auth", "auth_router", f"{prefix}/auth"))

        # Web pages are deliberately absent: a prefix-less router mounts as a
        # catch-all at "/" and shadows every path registered afterwards,
        # including the admin panel's, which are added during startup. The
        # bootstrap template registers those handlers individually instead.

        routers.sort(key=lambda entry: len(entry[2]), reverse=True)
        return routers

    def _tooling_operations(self, manifest: SilloManifest, context: dict) -> list:
        """Files contributed by the developer-tooling switches."""
        operations = []
        optional = [
            ("tooling/dockerfile.j2", "Dockerfile", manifest.tooling.docker),
            ("tooling/compose.yml.j2", "compose.yml", manifest.tooling.compose),
            ("tooling/makefile.j2", "Makefile", manifest.tooling.makefile),
            ("tooling/pre-commit.yaml.j2", ".pre-commit-config.yaml", manifest.tooling.pre_commit),
            ("tooling/github-ci.yml.j2", ".github/workflows/ci.yml", manifest.tooling.github_actions),
        ]
        for template, destination, enabled in optional:
            if enabled and self.engine.exists(template):
                operations.append(
                    CreateFile(destination, self.engine.render(template, context), skip_if_exists=True)
                )
        return operations

    def _post_operations(
        self, root: Path, manifest: SilloManifest, *, install: bool, git: bool
    ) -> list:
        """Optional finishing steps: git init and dependency installation."""
        from ..operations.commands import RunCommand
        from ..utils.pkgmanagers import detect_python_manager
        from ..utils.subprocess import tool_exists

        operations = []
        if git and tool_exists("git") and not (root / ".git").exists():
            operations.append(
                RunCommand(
                    ["git", "init", "--quiet"],
                    description="initialise a git repository",
                    optional=True,
                )
            )
        if install:
            manager = detect_python_manager()
            operations.append(
                RunCommand(
                    manager.sync_command(),
                    description=f"install dependencies with {manager.name}",
                    timeout=900,
                )
            )

            # Record the starting schema as migration 0001 and apply it, so the
            # database begins life under migration control. Without this the
            # tables exist with no history behind them, and the first model
            # change is detected as a brand-new table rather than an alteration
            # — which then fails to apply with "table already exists".
            #
            # Only after installing: the migration engine lives in the
            # project's environment, not this one. Optional, because a project
            # created against an unreachable database should still be created.
            if manifest.uses_record:
                from .migrations import get_backend

                operations.append(
                    RunCommand(
                        get_backend(manifest).bootstrap_argv(),
                        description="create and apply the initial migration",
                        optional=True,
                        timeout=300,
                    )
                )
        return operations

    # -- helpers -------------------------------------------------------

    def _check_target(self, root: Path, *, force: bool) -> None:
        """Refuse to generate into a directory that already has content.

        Raises:
            ProjectExistsError: If *root* is non-empty and *force* is not set.
        """
        if force or fs.is_empty_dir(root):
            return
        raise ProjectExistsError(
            f"Directory is not empty: {root}",
            hint="Choose another name, remove the directory, or pass --force to generate into it.",
        )

    def _resolve_groups(self, manifest: SilloManifest) -> Resolution:
        """Resolve the manifest's package groups into an ordered set."""
        requested = [name for name in manifest.packages.groups if package_registry.has(name)]
        resolution = resolve(requested, include_installed=True)
        # Resolution can pull in implied groups, which the manifest must record.
        for group in resolution.groups:
            manifest.add_group(group.name)
        return resolution

    def next_steps(self, manifest: SilloManifest, *, installed: bool) -> list[str]:
        """Build the copyable command list shown after creation."""
        steps = [f"cd {manifest.project.name}"]
        if not installed:
            steps.append(
                "uv sync" if manifest.tooling.package_manager == "uv" else 'pip install -e ".[dev]"'
            )
        # With --install the initial migration was already created and applied,
        # so repeating it here would just print "no migrations to apply".
        if manifest.uses_record and not installed:
            steps.append("sillo-start migrate run")
        if manifest.admin.enabled:
            steps.append("sillo-start admin create-user")
        steps.append("sillo-start dev")
        return steps

    def service_urls(self, manifest: SilloManifest) -> dict[str, str]:
        """Build the URL table shown after creation."""
        base = f"http://localhost:{manifest.application.port}"
        urls = {"Application": base}
        if manifest.api.openapi:
            urls["API docs"] = f"{base}/docs"
        if manifest.inertia.enabled:
            urls["Frontend"] = f"http://localhost:{manifest.inertia.port}"
        if manifest.admin.enabled:
            urls["Admin"] = f"{base}{manifest.admin.prefix}"
        return urls
