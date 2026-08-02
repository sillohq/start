"""``sillo-start migrate`` — a unified interface over the migration tool."""

from __future__ import annotations

import json

import typer

from ..config.loader import load_project
from ..project.migrations import ensure_driver_installed, get_backend
from ..utils.console import console, is_ci
from .app import app, handle_errors

migrate_app = typer.Typer(help="Create and apply database migrations.", no_args_is_help=True)
app.add_typer(migrate_app, name="migrate")


@migrate_app.command("init")
@handle_errors
def migrate_init(
    fake: bool = typer.Option(
        False,
        "--fake",
        help="Record the initial migration without running its SQL.",
    ),
) -> None:
    """Set up migrations and create the database.

    Writes the initial migration from the current models and applies it, so the
    database exists and its schema is recorded. This is what `create` runs for
    you when it installs dependencies; run it by hand after `--no-install`, or
    on a checkout of someone else's project.

    Use --fake when the tables already exist from outside the migration system.
    """
    root, manifest = load_project()
    ensure_driver_installed(manifest)
    backend = get_backend(manifest)

    console.header("Initialising migrations", f"location: {manifest.database.migrations_path}")
    result = backend.initialise(root, manifest)
    if not result.ok:
        _report(result, success="Migrations initialised.")
        return

    # initialise() only writes the migration. Applying it here is the whole
    # point of the command — without it there is no database and no tables,
    # which is not what "initialise" leads anyone to expect.
    _apply_pending(root, manifest, backend, fake=fake)


@migrate_app.command("make")
@handle_errors
def migrate_make(
    message: str = typer.Option("update", "--message", "-m", help="What this migration does."),
    apply: bool = typer.Option(
        False,
        "--apply",
        "-a",
        help="Apply the migration immediately instead of only writing it.",
    ),
) -> None:
    """Generate a migration from the current models.

    Only models registered in the models package are seen — a model that is not
    imported there produces an empty migration.

    Pass --apply to write and apply in one step:

        sillo-start migrate make -m add_posts --apply
    """
    root, manifest = load_project()
    ensure_driver_installed(manifest)
    backend = get_backend(manifest)

    console.header("Creating migration", message)
    result = backend.make(root, manifest, message)

    # Tortoise exits successfully when the models already match the schema.
    # Reporting "Migration created" there would send the operator looking for
    # a file that was never written.
    unchanged = result.ok and "no changes detected" in result.output.lower()
    if unchanged:
        console.info("Models already match the last migration — nothing to write.")
    else:
        _report(result, success="Migration created.")

    if not apply:
        if not unchanged:
            console.hint("Review it, then apply it with `sillo-start migrate run`.")
        return

    # Writing a migration failed, so there is nothing safe to apply — stop
    # rather than upgrading to a state the operator did not ask for.
    if not result.ok:
        return

    # Still upgrade when nothing new was written: --apply means "leave the
    # database current", and earlier migrations may be pending.
    _apply_pending(root, manifest, backend)


@migrate_app.command("run")
@handle_errors
def migrate_run(
    fake: bool = typer.Option(
        False,
        "--fake",
        help="Record migrations as applied without running their SQL.",
    ),
) -> None:
    """Apply every pending migration."""
    root, manifest = load_project()
    ensure_driver_installed(manifest)
    backend = get_backend(manifest)
    _apply_pending(root, manifest, backend, fake=fake)


def _apply_pending(root, manifest, backend, *, fake: bool = False) -> None:
    """Initialise if needed, then apply every pending migration.

    Shared by ``migrate run`` and ``migrate make --apply`` so both report the
    same way and both handle a schema that predates the migration history.
    """
    status = backend.status(root, manifest)
    if not status.initialised:
        console.info("Migrations are not set up yet — initialising first.")
        backend.initialise(root, manifest)

    console.header("Applying migrations")
    result = backend.upgrade(root, manifest, fake=fake)

    # A database whose tables were created outside the migration system — by an
    # earlier generate_schemas, or a schema restored from a dump — has nothing
    # recorded in the history table, so the first migration tries to create
    # tables that are already there. Say so, rather than leaving the operator
    # with a raw OperationalError.
    if not result.ok and "already exists" in result.output.lower():
        console.warning(
            "The schema already exists but no migrations are recorded against it."
        )
        console.hint(
            "If the tables match your models, adopt them with "
            "`sillo-start migrate run --fake`, which records the migrations "
            "without re-running their SQL."
        )
        return

    _report(result, success="Database is up to date.")


@migrate_app.command("rollback")
@handle_errors
def migrate_rollback(
    steps: int = typer.Option(1, "--steps", "-s", min=1, help="How many migrations to undo."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Undo the most recent migration(s).

    Rolling back drops whatever the migration created, so it asks first unless
    told otherwise or running in CI.
    """
    root, manifest = load_project()
    backend = get_backend(manifest)

    if not yes and not is_ci():
        console.warning(f"This will roll back {steps} migration(s) and may drop data.")
        if not typer.confirm("Continue?", default=False):
            console.info("Cancelled.")
            return

    console.header("Rolling back", f"{steps} migration(s)")
    result = backend.downgrade(root, manifest, steps=steps)
    _report(result, success="Rolled back.")


@migrate_app.command("status")
@handle_errors
def migrate_status(
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Show which migrations exist and which have been applied."""
    root, manifest = load_project()
    backend = get_backend(manifest)
    status = backend.status(root, manifest)

    if as_json:
        print(
            json.dumps(
                {
                    "initialised": status.initialised,
                    "files": status.files,
                    "applied": status.applied,
                    "pending": status.pending,
                },
                indent=2,
            )
        )
        return

    console.header("Migration status", manifest.database.migrations_path)

    if not status.initialised:
        console.warning("Migrations are not set up in this project.")
        console.hint("Run `sillo-start migrate init` to get started.")
        return

    console.table(
        ["", ""],
        [
            ("Migration files", str(len(status.files))),
            ("Applied", str(len(status.applied))),
            ("Pending", str(len(status.pending))),
        ],
    )

    if status.pending:
        console.blank()
        console.warning("Pending migrations:")
        console.bullets(status.pending)
        console.hint("Apply them with `sillo-start migrate run`.")
    elif status.files:
        console.blank()
        console.success("Everything is applied.")


@migrate_app.command("seed")
@handle_errors
def migrate_seed() -> None:
    """Run the project's database seeders."""
    root, manifest = load_project()
    seeders = root / "database" / "seeders"

    modules = (
        sorted(p.stem for p in seeders.glob("*.py") if p.name != "__init__.py")
        if seeders.exists()
        else []
    )
    if not modules:
        console.info("No seeders found in database/seeders/.")
        console.hint("Create one with `sillo-start generate seeder Users`.")
        return

    console.header("Seeding", f"{len(modules)} seeder(s)")
    console.bullets(modules)
    console.blank()
    console.warning("Seeders are run by your application, not by sillo-start.")
    console.hint("Invoke them from a script or a startup hook — see database/seeders/.")


def _report(result, *, success: str) -> None:
    """Render a backend command's outcome.

    Output from the underlying tool is always shown on failure — a scaffolding
    tool that hides why a migration failed is worse than one that never ran it.
    """
    if result.ok:
        if result.stdout.strip():
            console.raw(result.stdout.strip())
        console.blank()
        console.success(success)
        return

    console.blank()
    console.failure(f"The migration tool exited with code {result.returncode}.")
    if result.output:
        console.blank()
        console.raw(result.output)
    raise typer.Exit(code=1)
