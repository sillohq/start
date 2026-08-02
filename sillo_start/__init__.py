"""Sillo Start — bootstrapper and orchestrator for Sillo applications.

Sillo Start creates properly structured Sillo projects, installs and removes
features against an existing project, and runs the development services a
project needs. ``sillo.toml`` at the project root is the authoritative record
of what a project is; every command reads and updates it.

The package is layered so the CLI stays a thin shell over reusable logic:

``config``
    The manifest schema and its loading/writing.
``operations``
    Reversible units of work (write a file, edit TOML, install a package) and
    the transaction that applies them or rolls them back.
``packages``
    The package-group registry, dependency resolver, and installers.
``blueprints``
    Named project archetypes that turn wizard answers into a manifest.
``project``
    Creation, inspection and validation of projects on disk.
``generators``
    Component scaffolding for an existing project.
``orchestration``
    The supervised process manager behind ``sillo-start dev``.
``prompts``
    The interactive wizard.
``cli``
    Typer commands, which do argument handling and rendering only.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
