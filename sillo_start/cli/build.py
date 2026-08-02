"""``sillo-start build`` — prepare the project for production."""

from __future__ import annotations

import typer

from ..config.loader import load_project
from ..utils.console import console
from ..utils.pkgmanagers import detect_python_manager, frontend_manager
from ..utils.subprocess import run
from .app import app, handle_errors


@app.command()
@handle_errors
def build(
    frontend_only: bool = typer.Option(False, "--frontend", help="Only build the frontend."),
    backend_only: bool = typer.Option(False, "--backend", help="Only install Python dependencies."),
    install: bool = typer.Option(
        True, "--install/--no-install", help="Install dependencies before building."
    ),
) -> None:
    """Install dependencies and build production assets.

    For a project with a frontend this compiles the Vite bundle and writes the
    manifest the backend reads to find hashed asset names.
    """
    root, manifest = load_project()
    did_something = False

    if not frontend_only:
        did_something |= _build_backend(root, manifest, install=install)

    if not backend_only and manifest.inertia.enabled:
        did_something |= _build_frontend(root, manifest, install=install)

    console.blank()
    if did_something:
        console.success("Build complete.")
    else:
        console.info("Nothing to build.")


def _build_backend(root, manifest, *, install: bool) -> bool:
    """Install the project's Python dependencies."""
    if not install:
        return False
    manager = detect_python_manager()
    console.header("Backend", f"installing dependencies with {manager.name}")
    with console.progress("Resolving dependencies…"):
        result = run(manager.sync_command(), cwd=root, check=False, timeout=900)

    if not result.ok:
        console.failure(f"{manager.name} exited with code {result.returncode}.")
        if result.output:
            console.raw(result.output)
        raise typer.Exit(code=1)

    console.success("Dependencies installed.")
    return True


def _build_frontend(root, manifest, *, install: bool) -> bool:
    """Install frontend dependencies and produce the production bundle."""
    frontend = root / manifest.inertia.frontend_path
    if not (frontend / "package.json").exists():
        console.warning(f"No package.json in {manifest.inertia.frontend_path}/ — skipping.")
        return False

    manager = frontend_manager(str(manifest.inertia.package_manager))
    console.header("Frontend", f"{manifest.inertia.adapter} via {manager.name}")

    if install:
        with console.progress("Installing frontend dependencies…"):
            result = run(manager.install_command(), cwd=frontend, check=False, timeout=900)
        if not result.ok:
            console.failure(f"{manager.name} install failed (exit {result.returncode}).")
            if result.output:
                console.raw(result.output)
            raise typer.Exit(code=1)
        console.success("Frontend dependencies installed.")

    with console.progress("Building assets…"):
        result = run(manager.run_command("build"), cwd=frontend, check=False, timeout=900)

    if not result.ok:
        console.failure(f"The frontend build failed (exit {result.returncode}).")
        if result.output:
            console.raw(result.output)
        raise typer.Exit(code=1)

    console.success("Assets built into dist/.")
    console.hint("Set VITE_DEV=false in production so the built manifest is used.")
    return True
