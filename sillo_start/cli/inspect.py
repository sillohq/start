"""``sillo-start inspect`` — show a project's configuration."""

from __future__ import annotations

import json

import typer

from ..config.loader import load_project
from ..utils.console import console
from ..utils.filesystem import relative_to_cwd
from .app import app, handle_errors


@app.command("inspect")
@handle_errors
def inspect_project(
    as_json: bool = typer.Option(False, "--json", help="Emit the manifest as JSON."),
    section: str = typer.Option(None, "--section", "-s", help="Show only one section."),
) -> None:
    """Show what this project is configured with.

    Reads ``sillo.toml``, which is the authoritative record — this reports the
    project's declared configuration, not a guess from the filesystem.
    """
    root, manifest = load_project()

    if as_json:
        data = manifest.to_dict()
        if section:
            data = data.get(section, {})
        print(json.dumps({"root": str(root), **data} if not section else data, indent=2))
        return

    if section:
        values = manifest.to_dict().get(section)
        if values is None:
            console.error(
                f"No such section: '{section}'",
                hint=f"Sections: {', '.join(manifest.to_dict())}.",
            )
            raise typer.Exit(code=2)
        console.header(f"[{section}]")
        console.table(["Key", "Value"], [(k, str(v)) for k, v in values.items()])
        return

    console.header(manifest.project.name, relative_to_cwd(root))

    console.print("[bold]Application[/bold]")
    console.table(
        ["", ""],
        [
            ("Type", str(manifest.application.type)),
            ("Entrypoint", manifest.application.entrypoint),
            ("Version", manifest.project.version),
            ("Sillo", manifest.project.sillo_version),
            ("Created with", manifest.project.created_with or "unknown"),
        ],
    )

    console.blank()
    console.print("[bold]Features[/bold]")
    console.table(
        ["", ""],
        [
            ("Database", _describe_database(manifest)),
            ("Auth", str(manifest.auth.strategy) if manifest.auth.enabled else "off"),
            ("Authorization", "on" if manifest.authorization.enabled else "off"),
            ("Admin", manifest.admin.prefix if manifest.admin.enabled else "off"),
            ("Frontend", str(manifest.inertia.adapter) if manifest.inertia.enabled else "off"),
            ("Queue", str(manifest.queue.driver) if manifest.queue.enabled else "off"),
            ("Scheduler", "on" if manifest.scheduler.enabled else "off"),
            ("Cache", str(manifest.cache.driver) if manifest.cache.enabled else "off"),
            ("Sessions", str(manifest.session.driver) if manifest.session.enabled else "off"),
            ("Mail", str(manifest.mail.driver) if manifest.mail.enabled else "off"),
            ("Storage", str(manifest.storage.driver) if manifest.storage.enabled else "off"),
        ],
    )

    console.blank()
    console.print("[bold]Package groups[/bold]")
    if manifest.packages.groups:
        console.bullets(sorted(manifest.packages.groups))
    else:
        console.hint("none enabled")

    console.blank()
    console.print("[bold]Development services[/bold]")
    commands = {
        "backend": manifest.development.backend_command,
        "frontend": manifest.development.frontend_command,
        "worker": manifest.development.worker_command,
        "scheduler": manifest.development.scheduler_command,
        **manifest.development.extra_services,
    }
    rows = [(name, command) for name, command in commands.items() if command]
    console.table(["Service", "Command"], rows)


def _describe_database(manifest) -> str:
    """Render the database configuration as one readable line."""
    if not manifest.database.enabled:
        return "off"
    return f"{manifest.database.driver} via {manifest.database.orm}"
