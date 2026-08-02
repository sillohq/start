"""``sillo-start generate`` — scaffold components in an existing project."""

from __future__ import annotations

import typer

from ..config.loader import load_project
from ..generators.registry import registry as generator_registry
from ..operations.base import ExecutionContext
from ..operations.transaction import ExecutionPlan, execute_plan
from ..utils.console import console
from .app import app, handle_errors


@app.command()
@handle_errors
def generate(
    kind: str = typer.Argument(None, help="What to generate. Omit to list the options."),
    name: str = typer.Argument(None, help="Component name, e.g. Post or UserService."),
    fields: list[str] = typer.Option(
        None,
        "--field",
        "-f",
        help="Model field as name:type[:flag...], e.g. -f title:str:unique. Repeatable.",
    ),
    timestamps: bool = typer.Option(True, "--timestamps/--no-timestamps", help="Add created/updated columns."),
    soft_deletes: bool = typer.Option(False, "--soft-deletes", help="Add a soft-delete column."),
    schema: bool = typer.Option(True, "--schema/--no-schema", help="Also create request schemas."),
    repository: bool = typer.Option(False, "--repository", help="Also create a repository."),
    controller: bool = typer.Option(False, "--controller", help="Also create a controller."),
    tests: bool = typer.Option(True, "--tests/--no-tests", help="Also create a test module."),
    force: bool = typer.Option(False, "--force", help="Overwrite files that already exist."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be created."),
) -> None:
    """Scaffold a component.

        sillo-start generate model Post -f title:str -f body:text -f author:fk:User
        sillo-start generate service Billing
        sillo-start generate job SendInvoice
    """
    if not kind:
        _list_generators()
        return

    generator = generator_registry.get(kind)

    if not name:
        console.error(
            f"`generate {kind}` needs a name.",
            hint=f"sillo-start generate {kind} <Name>",
        )
        raise typer.Exit(code=2)

    root, manifest = load_project()
    generator.check_requirements(manifest)
    component = generator.normalise(name)

    operations = generator.plan(
        component,
        manifest,
        force=force,
        fields=list(fields or []),
        timestamps=timestamps,
        soft_deletes=soft_deletes,
        schema=schema,
        repository=repository,
        controller=controller,
        tests=tests,
    )

    plan = ExecutionPlan(f"Generate {kind} {component}", operations)
    context = ExecutionContext(project_root=root, manifest=manifest, dry_run=dry_run, force=force)

    if dry_run:
        console.header("Dry run", f"{len(plan)} operation(s)")
        plan.render(context, console=console)
        return

    console.header(f"Generating {kind}", component)
    report = execute_plan(plan, context, console=console)

    console.blank()
    if report.changed_count:
        console.success(f"Created {report.changed_count} file(s).")
    else:
        console.info("Nothing to do — the files already exist. Pass --force to overwrite.")

    if kind == "model" and manifest.uses_record:
        console.blank()
        console.print("[bold]Next[/bold]")
        console.commands([f'sillo-start migrate make -m "create {component.lower()}"', "sillo-start migrate run"])


def _list_generators() -> None:
    """Show what can be generated."""
    console.header("Available generators")
    console.table(
        ["Name", "Creates"],
        [(g.name, g.summary) for g in generator_registry.all()],
    )
    console.blank()
    console.hint("sillo-start generate model Post -f title:str -f body:text")
