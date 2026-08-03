"""The Typer command tree.

Importing the command module registers its command on the shared ``app``, so
:func:`build_cli` imports it and returns the app.
"""

from __future__ import annotations

import typer


def build_cli() -> typer.Typer:
    """Assemble and return the CLI application."""
    from . import create  # noqa: F401 — importing registers the command
    from .app import app

    return app


__all__ = ["build_cli"]
