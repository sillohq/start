"""The Typer application and its shared behaviour.

The CLI layer stays thin: it parses arguments, calls into
:mod:`sillo_start.project.template`, and renders the result. The fetching and
personalising happen there, which is what lets them be driven from tests
without a terminal.

Errors are handled in one place. Anything deriving from
:class:`~sillo_start.exceptions.SilloStartError` becomes a clean message plus
its hint and a predictable exit code; the traceback appears only under
``--verbose``.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from functools import wraps
from typing import Any

import typer

from .. import __version__
from ..exceptions import SilloStartError
from ..utils.console import console

app = typer.Typer(
    name="sillo-start",
    help="Create a Sillo application from a starter repository.",
    add_completion=True,
    no_args_is_help=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)


def version_callback(value: bool) -> None:
    """Print the version and exit."""
    if value:
        console.print(f"sillo-start {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show the version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show debug output and tracebacks."
    ),
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="Suppress non-essential output."
    ),
) -> None:
    """Sillo Start — create a Sillo application from a starter repository."""
    console.configure(verbose=verbose, quiet=quiet)


def handle_errors(func: Callable[..., Any]) -> Callable[..., Any]:
    """Turn deliberate failures into clean messages and exit codes.

    Applied to every command body. ``typer.Exit`` and ``typer.Abort`` pass
    through untouched so control flow still works.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except (typer.Exit, typer.Abort):
            raise
        except SilloStartError as exc:
            console.error(exc.message, hint=exc.hint)
            if console.verbose:
                console.rich.print_exception()
            raise typer.Exit(code=exc.exit_code) from exc
        except KeyboardInterrupt:
            console.blank()
            console.warning("Cancelled.")
            raise typer.Exit(code=130) from None
        except Exception as exc:  # noqa: BLE001 — last resort, reported not swallowed
            console.error(
                f"Unexpected error: {exc}",
                hint="Re-run with --verbose for the full traceback, and please report this.",
            )
            if console.verbose:
                console.rich.print_exception()
            raise typer.Exit(code=1) from exc

    return wrapper


def run() -> None:
    """Entrypoint used by the console script."""
    try:
        app()
    except SilloStartError as exc:
        # Reached only for failures raised outside a command body.
        console.error(exc.message, hint=exc.hint)
        sys.exit(exc.exit_code)
