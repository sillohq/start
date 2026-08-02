"""``sillo-start add`` — install a feature into an existing project.

``add`` is a friendlier front for the package-group machinery: it maps a
feature name onto the groups and manifest changes that feature implies, so a
developer types ``sillo-start add auth`` rather than knowing which groups and
which flags are involved.
"""

from __future__ import annotations

import typer

from ..config.defaults import AuthStrategy, InertiaAdapter, QueueDriver
from ..config.loader import load_project
from ..exceptions import UsageError
from ..operations.base import ExecutionContext
from ..operations.commands import UpdateManifest
from ..operations.transaction import execute_plan
from ..packages.installer import build_install_plan
from ..packages.resolver import resolve
from ..utils.console import console
from .app import app, handle_errors

#: Features and the package groups each one needs.
FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "auth": ("record", "auth"),
    "admin": ("record", "auth", "admin"),
    "inertia": ("inertia",),
    "queue": ("work",),
    "scheduler": ("work",),
    "record": ("record",),
    "database": ("record",),
    "monitoring": ("monitoring",),
    "security": ("security",),
    "realtime": ("realtime",),
    "testing": ("testing",),
    "api": ("api",),
}


@app.command()
@handle_errors
def add(
    feature: str = typer.Argument(None, help="Feature to add. Omit to list the options."),
    adapter: InertiaAdapter = typer.Option(None, "--adapter", help="Frontend framework, for inertia."),
    strategy: AuthStrategy = typer.Option(None, "--strategy", help="Auth strategy, for auth."),
    driver: QueueDriver = typer.Option(None, "--driver", help="Queue backend, for queue."),
    install: bool = typer.Option(True, "--install/--no-install", help="Run the package manager."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the plan without applying it."),
) -> None:
    """Add a feature to this project.

        sillo-start add auth --strategy session
        sillo-start add admin
        sillo-start add inertia --adapter react
        sillo-start add queue --driver redis
    """
    if not feature:
        _list_features()
        return

    if feature not in FEATURE_GROUPS:
        raise UsageError(
            f"Unknown feature: '{feature}'",
            hint=f"Available: {', '.join(sorted(FEATURE_GROUPS))}.",
        )

    root, manifest = load_project()

    if feature == "inertia":
        from ..features.inertia import add_inertia

        add_inertia(
            root,
            manifest,
            adapter=adapter or InertiaAdapter.REACT,
            install=install,
            dry_run=dry_run,
        )
        return

    groups = FEATURE_GROUPS[feature]
    resolution = resolve(list(groups), installed=manifest.packages.groups)

    mutation = _manifest_change(feature, strategy=strategy, driver=driver)
    plan = build_install_plan(
        resolution,
        manifest,
        install=install,
        title=f"Add {feature}",
    )
    if mutation is not None:
        plan.add(UpdateManifest(mutation, description=f"enable {feature} in sillo.toml"))

    if not plan:
        console.info(f"'{feature}' is already configured.")
        return

    context = ExecutionContext(project_root=root, manifest=manifest, dry_run=dry_run)

    if dry_run:
        console.header("Dry run", f"{len(plan)} operation(s)")
        plan.render(context, console=console)
        return

    console.header(f"Adding {feature}")
    if resolution.implied:
        console.info(f"Also enabling: {', '.join(resolution.implied)}")

    execute_plan(plan, context, console=console)

    console.blank()
    console.success(f"Added {feature}.")
    _next_steps(feature, manifest)


def _manifest_change(feature: str, *, strategy, driver):
    """Return the manifest mutation a feature implies, or ``None``."""
    if feature in ("auth",):

        def mutate(manifest):
            manifest.auth.enabled = True
            manifest.auth.strategy = strategy or AuthStrategy.SESSION
            if manifest.auth.strategy == AuthStrategy.SESSION:
                manifest.session.enabled = True
            manifest.database.enabled = True

        return mutate

    if feature == "admin":

        def mutate(manifest):
            manifest.admin.enabled = True
            manifest.auth.enabled = True
            if manifest.auth.strategy == AuthStrategy.NONE:
                manifest.auth.strategy = AuthStrategy.SESSION
                manifest.session.enabled = True
            if not manifest.admin.title:
                manifest.admin.title = f"{manifest.project.name} Admin"

        return mutate

    if feature in ("queue",):

        def mutate(manifest):
            manifest.queue.enabled = True
            manifest.queue.driver = driver or QueueDriver.REDIS
            manifest.development.worker_command = "python scripts/worker.py"

        return mutate

    if feature == "scheduler":

        def mutate(manifest):
            manifest.scheduler.enabled = True
            manifest.development.scheduler_command = "python scripts/scheduler.py"

        return mutate

    if feature in ("record", "database"):

        def mutate(manifest):
            manifest.database.enabled = True

        return mutate

    return None


def _next_steps(feature: str, manifest) -> None:
    """Print what to do after adding a feature."""
    steps = {
        "auth": ["sillo-start migrate make -m 'add users'", "sillo-start migrate run"],
        "admin": ["sillo-start migrate run", "sillo-start admin create-user"],
        "queue": ["sillo-start dev  # the worker starts alongside the app"],
        "scheduler": ["sillo-start dev  # the scheduler starts alongside the app"],
        "record": ["sillo-start migrate init"],
    }.get(feature)

    if steps:
        console.blank()
        console.print("[bold]Next[/bold]")
        console.commands(steps)


def _list_features() -> None:
    """Show the features that can be added."""
    console.header("Features you can add")
    console.table(
        ["Feature", "Enables"],
        [(name, ", ".join(groups)) for name, groups in sorted(FEATURE_GROUPS.items())],
    )
    console.blank()
    console.hint("sillo-start add auth --strategy session")
