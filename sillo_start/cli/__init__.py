"""The Typer command tree.

Importing a command module registers its commands on the shared ``app``, so
:func:`build_cli` simply imports them in a fixed order and returns the app.
Plugins are loaded first, giving them a chance to register blueprints, package
groups, generators and services before any command reads a registry.
"""

from __future__ import annotations

import typer


def build_cli() -> typer.Typer:
    """Assemble and return the CLI application."""
    from ..plugins.loader import load_plugins
    from .app import app

    load_plugins()

    # Each import has the side effect of registering commands.
    from . import (  # noqa: F401
        add,
        admin,
        build,
        create,
        dev,
        doctor,
        generate,
        inspect,
        migrate,
        package,
    )

    return app


__all__ = ["build_cli"]
