"""``sillo-start create-app``."""

from __future__ import annotations

from pathlib import Path

import typer

from ..exceptions import UsageError
from ..utils.console import console
from ..utils.naming import is_valid_project_name
from .app import app, handle_errors


@app.command("create-app")
@handle_errors
def create_app(
    template: str = typer.Argument(
        None, help="Starter repository, e.g. sillohq/starter or sillohq/starter@v1."
    ),
    name: str = typer.Argument(None, help="Project name. Also the directory name."),
    directory: Path = typer.Option(
        None,
        "--directory",
        "-d",
        help="Where to create the project. Defaults to ./<name>.",
    ),
    ref: str = typer.Option(
        None, "--ref", help="Branch or tag to take. Defaults to main."
    ),
    install: bool = typer.Option(
        False, "--install/--no-install", help="Install dependencies after fetching."
    ),
    git: bool = typer.Option(
        True, "--git/--no-git", help="Initialise a git repository."
    ),
    force: bool = typer.Option(False, "--force", help="Allow a non-empty directory."),
) -> None:
    """Create a project from a starter repository.

        sillo-start create-app myapp
        sillo-start create-app sillohq/starter myapp
        sillo-start create-app sillohq/starter@v1.2 myapp

    The starter is a real application with its own CI, so what you get has been
    booted and exercised rather than only rendered. With one argument the
    default starter is used and the argument is the project name.
    """
    from ..project.template import DEFAULT_TEMPLATE, Template, fetch, personalise

    # One argument is the project name; the starter is only ever given when
    # both are, so `create-app myapp` does the obvious thing.
    if name is None:
        name, template = template, DEFAULT_TEMPLATE
    if not name:
        raise UsageError(
            "A project name is required.",
            hint="sillo-start create-app myapp",
        )
    if not is_valid_project_name(name):
        raise UsageError(
            f"'{name}' is not a valid project name.",
            hint="Use a letter followed by letters, digits, hyphens or underscores.",
        )

    parsed = Template.parse(template or DEFAULT_TEMPLATE, ref=ref)
    root = (directory or Path.cwd() / name).resolve()
    if root.exists() and any(root.iterdir()) and not force:
        raise UsageError(
            f"{root} is not empty.",
            hint="Choose another directory, or pass --force.",
        )

    console.header(f"Creating {name}", f"from {parsed.slug}@{parsed.ref}")
    with console.progress(f"Fetching {parsed.slug}…"):
        fetch(parsed, root)

    changed = personalise(root, name)
    console.success(f"Fetched {parsed.slug} and renamed {len(changed)} file(s)")

    if git:
        from ..utils.subprocess import run, tool_exists

        if tool_exists("git") and not (root / ".git").exists():
            run(["git", "init", "--quiet"], cwd=root, check=False)

    if install:
        from ..utils.pkgmanagers import detect_python_manager
        from ..utils.subprocess import run

        manager = detect_python_manager()
        console.header("Dependencies", f"installing with {manager.name}")
        with console.progress("Resolving…"):
            result = run(manager.sync_command(), cwd=root, check=False, timeout=900)
        if not result.ok:
            console.failure(f"{manager.name} exited with code {result.returncode}.")
            if result.output:
                console.raw(result.output)
            raise typer.Exit(code=1)
        console.success("Dependencies installed.")

    console.blank()
    console.print("[bold]Next steps[/bold]")
    steps = [f"cd {root.name}"]
    if not install:
        steps.append("make setup")
    else:
        steps.append("make migrate")
    steps.append("make dev")
    console.commands(steps)
    console.blank()
    console.hint(
        "The starter's README covers configuration, migrations and deployment."
    )
