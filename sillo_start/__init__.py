"""Sillo Start — creates a Sillo application from a starter repository.

The tool fetches `sillohq/starter` as a tarball, renames it to yours, gives it
its own secrets, and optionally initialises a git repository. It does not
generate code from templates and it does not manage a project after creation:
migrations, users, workers and the dev server all belong to the project's own
``sillo`` command.

The package is small and layered so the CLI stays a thin shell:

``cli``
    Typer commands (``app``, ``create``), which do argument handling and
    rendering only.
``project``
    ``Template``: fetching a starter, personalising it, generating secrets.
``utils``
    Console output, name derivation, package-manager detection, subprocess
    helpers.
``exceptions``
    ``SilloStartError`` and the specific failures raised beneath it.
"""

from __future__ import annotations

__version__ = "1.0.0a1"

__all__ = ["__version__"]
