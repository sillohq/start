"""``python -m sillo_start`` and the ``sillo-start`` console script."""

from __future__ import annotations


def main() -> None:
    """Load the command tree and run the CLI."""
    # Imported here rather than at module scope so that plugin loading and
    # command registration happen once, at invocation, and a broken plugin
    # cannot make `python -m sillo_start` unimportable.
    from .cli import build_cli

    # A Typer app is called, not `.main()`ed — calling it is what runs the
    # underlying Click command with argv.
    build_cli()()


if __name__ == "__main__":
    main()
