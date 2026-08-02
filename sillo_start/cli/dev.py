"""``sillo-start dev`` and ``sillo-start services``."""

from __future__ import annotations

import json

import typer

from ..config.loader import load_project
from ..exceptions import UsageError
from ..orchestration.services import build_registry
from ..orchestration.supervisor import ProcessSupervisor
from ..utils.console import console
from .app import app, handle_errors


@app.command()
@handle_errors
def dev(
    only: str = typer.Option(None, "--only", help="Run only these services, comma-separated."),
    without: str = typer.Option(None, "--without", help="Skip these services, comma-separated."),
    no_health: bool = typer.Option(
        False, "--no-health", help="Start without waiting for services to report healthy."
    ),
    list_services: bool = typer.Option(
        False, "--list", help="List the services this project defines and exit."
    ),
) -> None:
    """Run every development service this project needs.

    Reads ``sillo.toml`` and starts the backend, the frontend dev server, the
    queue worker and the scheduler as configured — with interleaved output, and
    a clean shutdown on Ctrl+C.

        sillo-start dev --only backend,frontend
        sillo-start dev --without worker
    """
    root, manifest = load_project()
    registry = build_registry(manifest)

    if not len(registry):
        raise UsageError(
            "This project defines no development services.",
            hint="Check the [development] section of sillo.toml.",
        )

    if list_services:
        console.header("Development services")
        console.table(
            ["Service", "Command", "URL"],
            [(s.name, s.command, s.url or "") for s in registry.all()],
        )
        return

    selected = registry.select(only=_split(only), without=_split(without))
    if not selected:
        raise UsageError(
            "That selection leaves no services to run.",
            hint=f"Available: {', '.join(registry.names())}.",
        )

    supervisor = ProcessSupervisor(project_root=root, console=console)
    for definition in selected:
        supervisor.add(definition)

    console.header(
        f"Starting {manifest.project.name}",
        f"{len(selected)} service(s): {', '.join(s.name for s in selected)}",
    )
    supervisor.start_all(wait_for_health=not no_health)
    raise typer.Exit(code=supervisor.watch())


services_app = typer.Typer(help="Inspect the development services.", no_args_is_help=True)
app.add_typer(services_app, name="services")


@services_app.command("list")
@handle_errors
def services_list(
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """List the services this project defines."""
    _, manifest = load_project()
    registry = build_registry(manifest)

    if as_json:
        print(
            json.dumps(
                [
                    {
                        "name": s.name,
                        "command": s.command,
                        "cwd": s.cwd,
                        "port": s.port,
                        "url": s.url,
                        "depends_on": list(s.depends_on),
                    }
                    for s in registry.all()
                ],
                indent=2,
            )
        )
        return

    console.header("Development services", manifest.project.name)
    console.table(
        ["Service", "Description", "Command", "URL"],
        [(s.name, s.description, s.command, s.url or "") for s in registry.all()],
    )


@services_app.command("status")
@handle_errors
def services_status(
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Check which services are currently reachable.

    Sillo Start does not run a background daemon, so this reports what is
    answering on each service's port right now — which is the question worth
    asking, and stays true whether the process was started by ``dev`` or by
    hand.
    """
    _, manifest = load_project()
    registry = build_registry(manifest)

    rows = []
    for service in registry.all():
        if service.health is not None:
            reachable = service.health.check()
            state = "up" if reachable else "down"
        else:
            state = "unknown"
        rows.append(
            {
                "name": service.name,
                "state": state,
                "url": service.url,
                "checked": service.health.describe() if service.health else None,
            }
        )

    if as_json:
        print(json.dumps(rows, indent=2))
        return

    console.header("Service status", manifest.project.name)
    console.table(
        ["Service", "State", "URL", "Checked"],
        [
            (
                row["name"],
                {"up": "[green]up[/green]", "down": "[red]down[/red]"}.get(
                    row["state"], "[dim]unknown[/dim]"
                ),
                row["url"] or "",
                row["checked"] or "",
            )
            for row in rows
        ],
    )
    console.blank()
    console.hint("Start everything with: sillo-start dev")


def _split(value: str | None) -> list[str] | None:
    """Split a comma-separated option into a list."""
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]
