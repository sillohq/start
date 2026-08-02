"""``sillo-start create`` and ``sillo-start init``."""

from __future__ import annotations

from pathlib import Path

import typer

from ..blueprints.registry import registry as blueprint_registry
from ..config.defaults import (
    AuthStrategy,
    CacheDriver,
    DatabaseDriver,
    InertiaAdapter,
    MailDriver,
    PythonPackageManager,
    QueueDriver,
    StorageDriver,
)
from ..exceptions import UsageError
from ..operations.base import ExecutionContext
from ..packages.resolver import validate_selection
from ..project.creator import ProjectCreator
from ..project.manifest import ProjectOptions, build_manifest
from ..prompts.questions import Answerer
from ..prompts.wizard import SetupWizard, confirm_summary
from ..utils.console import console, is_ci
from .app import app, handle_errors


@app.command()
@handle_errors
def create(
    name: str = typer.Argument(None, help="Project name. Also the directory name."),
    blueprint: str = typer.Option(
        None, "--blueprint", "-b", help="Project archetype. See --list-blueprints."
    ),
    directory: Path = typer.Option(
        None, "--directory", "-d", help="Where to create the project. Defaults to ./<name>."
    ),
    database: DatabaseDriver = typer.Option(None, "--database", help="Database backend."),
    auth: AuthStrategy = typer.Option(None, "--auth", help="Authentication strategy."),
    admin: bool = typer.Option(None, "--admin/--no-admin", help="Include the admin panel."),
    inertia: InertiaAdapter = typer.Option(None, "--inertia", help="Add an Inertia frontend."),
    queue: QueueDriver = typer.Option(None, "--queue", help="Background job backend."),
    scheduler: bool = typer.Option(None, "--scheduler/--no-scheduler", help="Add scheduled tasks."),
    cache: CacheDriver = typer.Option(None, "--cache", help="Cache backend."),
    mail: MailDriver = typer.Option(None, "--mail", help="Mail transport."),
    storage: StorageDriver = typer.Option(None, "--storage", help="File storage backend."),
    package_group: list[str] = typer.Option(
        None, "--package-group", "-p", help="Enable a package group. Repeatable."
    ),
    package_manager: PythonPackageManager = typer.Option(
        PythonPackageManager.UV, "--package-manager", help="Python package manager."
    ),
    install: bool = typer.Option(
        False,
        "--install/--no-install",
        help=(
            "Install dependencies and apply the initial migration. "
            "Without it, run `sillo-start migrate init` afterwards."
        ),
    ),
    git: bool = typer.Option(True, "--git/--no-git", help="Initialise a git repository."),
    force: bool = typer.Option(False, "--force", "-f", help="Generate into a non-empty directory."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be created."),
    interaction: bool = typer.Option(
        True, "--interaction/--no-interaction", help="Run the setup wizard."
    ),
    list_blueprints: bool = typer.Option(
        False, "--list-blueprints", help="List the available blueprints and exit."
    ),
) -> None:
    """Create a new Sillo application.

    Run without flags for a guided setup, or pass flags with --no-interaction
    to generate a project unattended:

        sillo-start create myapp --database postgres --auth session --admin --no-interaction
    """
    if list_blueprints:
        _print_blueprints()
        raise typer.Exit()

    # CI has no terminal to prompt on, so the wizard is skipped there unless
    # interaction was explicitly requested.
    interactive = interaction and not is_ci()

    if interactive and not _has_explicit_choices(locals()):
        options, chosen_blueprint = SetupWizard().run(name)
        if not confirm_summary(options, chosen_blueprint, Answerer()):
            console.warning("Cancelled — nothing was created.")
            raise typer.Exit(code=130)
    else:
        if not name:
            raise UsageError(
                "A project name is required in non-interactive mode.",
                hint="sillo-start create myapp --no-interaction",
            )
        chosen_blueprint = blueprint_registry.get(blueprint or _infer_blueprint(inertia))
        options = ProjectOptions(
            name=name,
            blueprint=chosen_blueprint.name,
            database=database,
            auth=auth,
            admin=admin,
            inertia=inertia,
            queue=queue,
            scheduler=scheduler,
            cache=cache,
            mail=mail,
            storage=storage,
            package_groups=validate_selection(list(package_group or [])),
            python_manager=package_manager,
        )

    # An explicit --blueprint always wins, including over the wizard's choice.
    if blueprint:
        chosen_blueprint = blueprint_registry.get(blueprint)
        options.blueprint = chosen_blueprint.name

    manifest = build_manifest(options, chosen_blueprint)
    root = (directory or Path.cwd() / options.name).resolve()

    creator = ProjectCreator()

    if dry_run:
        _preview(creator, root, manifest, chosen_blueprint)
        raise typer.Exit()

    console.header(f"Creating {options.name}", f"blueprint: {chosen_blueprint.name}")
    with console.progress("Generating project…"):
        result = creator.create(
            root, manifest, chosen_blueprint, force=force, install=install, git=git
        )

    _report(result, installed=install)


@app.command()
@handle_errors
def init(
    blueprint: str = typer.Option("api", "--blueprint", "-b", help="Project archetype."),
    force: bool = typer.Option(False, "--force", "-f", help="Generate into a non-empty directory."),
    interaction: bool = typer.Option(True, "--interaction/--no-interaction"),
) -> None:
    """Create a Sillo application in the current directory.

    The directory name becomes the project name.
    """
    root = Path.cwd()
    name = root.name

    if interaction and not is_ci():
        options, chosen_blueprint = SetupWizard().run(name)
    else:
        chosen_blueprint = blueprint_registry.get(blueprint)
        options = ProjectOptions(name=name, blueprint=chosen_blueprint.name)

    manifest = build_manifest(options, chosen_blueprint)
    console.header(f"Initialising {name}", f"blueprint: {chosen_blueprint.name}")
    result = ProjectCreator().create(root, manifest, chosen_blueprint, force=force, git=False)
    _report(result, installed=False, inside=True)


# -- helpers ------------------------------------------------------------


def _has_explicit_choices(arguments: dict) -> bool:
    """Report whether any feature flag was passed.

    Passing flags is taken as intent to skip the wizard for those decisions —
    being asked a question you already answered on the command line is a poor
    experience.
    """
    return any(
        arguments.get(key) is not None
        for key in (
            "database",
            "auth",
            "admin",
            "inertia",
            "queue",
            "scheduler",
            "cache",
            "mail",
            "storage",
        )
    ) or bool(arguments.get("package_group"))


def _infer_blueprint(inertia: InertiaAdapter | None) -> str:
    """Choose a default blueprint from the flags given."""
    return f"inertia-{inertia.value}" if inertia else "api"


def _print_blueprints() -> None:
    """List the registered blueprints."""
    console.header("Available blueprints")
    console.table(
        ["Name", "Description"],
        [(bp.name, bp.summary) for bp in blueprint_registry.all()],
    )
    console.blank()
    console.hint("Use one with: sillo-start create myapp --blueprint <name>")


def _preview(creator: ProjectCreator, root: Path, manifest, blueprint) -> None:
    """Render the creation plan without writing anything."""
    resolution = creator._resolve_groups(manifest)  # noqa: SLF001 — same package
    plan = creator.build_plan(root, manifest, blueprint, resolution, install=False, git=False)
    context = ExecutionContext(project_root=root, manifest=manifest, dry_run=True)

    console.header("Dry run", f"{len(plan)} operation(s) — nothing will be written")
    plan.render(context, console=console)
    console.blank()
    console.info(f"Package groups: {', '.join(resolution.names)}")


def _report(result, *, installed: bool, inside: bool = False) -> None:
    """Print the post-creation summary."""
    console.blank()
    console.success(f"Created {result.manifest.project.name}")
    console.blank()

    console.print("[bold]Next steps[/bold]")
    steps = result.next_steps
    if inside:
        steps = [step for step in steps if not step.startswith("cd ")]
    console.commands(steps)

    if result.urls:
        console.blank()
        console.print("[bold]Once running[/bold]")
        width = max(len(label) for label in result.urls)
        for label, url in result.urls.items():
            console.print(f"  {label.ljust(width)}   [cyan]{url}[/cyan]")

    notes = result.resolution.post_install_notes()
    if notes:
        console.blank()
        console.print("[bold]Notes[/bold]")
        console.bullets(notes)
