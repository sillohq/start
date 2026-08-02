"""``sillo-start package`` — inspect and manage package groups."""

from __future__ import annotations

import json

import typer

from ..config.loader import load_project
from ..exceptions import PackageGroupError
from ..operations.base import ExecutionContext
from ..operations.transaction import execute_plan
from ..packages.installer import build_install_plan, build_removal_plan
from ..packages.registry import registry
from ..packages.resolver import dependents_of, resolve
from ..utils.console import console
from .app import app, handle_errors

package_app = typer.Typer(help="Inspect and manage Sillo package groups.", no_args_is_help=True)
app.add_typer(package_app, name="package")


@package_app.command("list")
@handle_errors
def list_groups(
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """List every available package group and whether it is installed."""
    try:
        _, manifest = load_project()
        installed = set(manifest.packages.groups)
    except Exception:
        # Listing groups is useful outside a project too — for deciding what to
        # create — so a missing manifest is not an error here.
        installed = set()

    groups = registry.all()

    if as_json:
        print(
            json.dumps(
                [
                    {
                        "name": g.name,
                        "summary": g.summary,
                        "installed": g.name in installed,
                        "requires": list(g.requires),
                        "conflicts": list(g.conflicts),
                    }
                    for g in groups
                ],
                indent=2,
            )
        )
        return

    console.header("Sillo package groups")
    console.table(
        ["", "Group", "Description"],
        [
            ("✓" if g.name in installed else " ", g.name, g.summary)
            for g in groups
        ],
    )
    console.blank()
    console.hint("sillo-start package add <name>     enable a group")
    console.hint("sillo-start package info <name>    see what it installs")


@package_app.command("info")
@handle_errors
def group_info(
    name: str = typer.Argument(..., help="Package group name."),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Show what a package group installs and what it depends on."""
    group = registry.get(name)

    if as_json:
        print(
            json.dumps(
                {
                    "name": group.name,
                    "summary": group.summary,
                    "description": group.description,
                    "sillo_extras": list(group.sillo_extras),
                    "python_packages": list(group.python_packages),
                    "dev_packages": list(group.dev_packages),
                    "directories": list(group.directories),
                    "environment": [v.key for v in group.env_vars],
                    "requires": list(group.requires),
                    "conflicts": list(group.conflicts),
                },
                indent=2,
            )
        )
        return

    console.header(group.name, group.summary)
    if group.description:
        console.print(group.description)
        console.blank()

    sections = [
        ("Framework extras", list(group.sillo_extras)),
        ("Python packages", list(group.python_packages)),
        ("Dev packages", list(group.dev_packages)),
        ("Directories", list(group.directories)),
        ("Environment", [v.key for v in group.env_vars]),
        ("Requires", list(group.requires)),
        ("Conflicts", list(group.conflicts)),
    ]
    for title, values in sections:
        if values:
            console.print(f"[bold]{title}[/bold]")
            console.bullets(values)
            console.blank()

    if not any(values for _, values in sections):
        console.info("This group needs no extra dependencies — the code ships in sillo core.")


@package_app.command("add")
@handle_errors
def add_group(
    names: list[str] = typer.Argument(..., help="Package groups to enable."),
    install: bool = typer.Option(True, "--install/--no-install", help="Run the package manager."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the plan without applying it."),
) -> None:
    """Enable one or more package groups in this project."""
    root, manifest = load_project()

    resolution = resolve(names, installed=manifest.packages.groups)
    if not resolution.groups:
        console.info("Already enabled — nothing to do.")
        return

    for group in resolution.groups:
        compatible, reason = group.compatible_with(manifest)
        if not compatible:
            raise PackageGroupError(reason, hint="Run `sillo-start doctor` to review the project.")

    plan = build_install_plan(resolution, manifest, install=install)
    context = ExecutionContext(project_root=root, manifest=manifest, dry_run=dry_run)

    if resolution.implied:
        console.info(f"Also enabling required groups: {', '.join(resolution.implied)}")

    if dry_run:
        console.header("Dry run", f"{len(plan)} operation(s)")
        plan.render(context, console=console)
        return

    console.header(f"Adding {', '.join(resolution.names)}")
    report = execute_plan(plan, context, console=console)

    console.blank()
    console.success(f"Enabled {', '.join(resolution.names)} ({report.changed_count} change(s))")
    notes = resolution.post_install_notes()
    if notes:
        console.blank()
        console.print("[bold]Next[/bold]")
        console.bullets(notes)


@package_app.command("remove")
@handle_errors
def remove_group(
    name: str = typer.Argument(..., help="Package group to disable."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the plan without applying it."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Disable a package group.

    Dependencies are dropped and the group is unregistered, but generated
    source files are left alone — they may have been edited, and deleting a
    developer's code is not something a package manager should do.
    """
    root, manifest = load_project()

    if not manifest.has_group(name):
        console.info(f"'{name}' is not enabled in this project.")
        return

    blockers = dependents_of(name, installed=manifest.packages.groups)
    if blockers:
        raise PackageGroupError(
            f"'{name}' is required by: {', '.join(blockers)}.",
            hint=f"Remove those first: sillo-start package remove {blockers[0]}",
        )

    plan = build_removal_plan(name, manifest)
    context = ExecutionContext(project_root=root, manifest=manifest, dry_run=dry_run)

    if dry_run:
        console.header("Dry run", f"{len(plan)} operation(s)")
        plan.render(context, console=console)
        return

    if not yes:
        console.warning(f"This will remove the '{name}' dependencies from pyproject.toml.")
        if not typer.confirm("Continue?", default=False):
            console.info("Cancelled.")
            return

    console.header(f"Removing {name}")
    execute_plan(plan, context, console=console)

    console.blank()
    console.success(f"Disabled '{name}'")
    console.hint("Generated files were left in place — remove any you no longer need.")
