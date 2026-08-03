"""Terminal output.

All user-facing output goes through the :class:`Console` singleton here so that
quiet mode, CI detection and JSON output are honoured in one place instead of
being re-checked at every print site.

Colour is dropped automatically when the stream is not a TTY, when ``NO_COLOR``
is set, or when a CI environment variable is present, which keeps generated
logs readable in pipelines.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from rich.console import Console as RichConsole
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

_CI_VARS = ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "BUILDKITE", "CIRCLECI")


def is_ci() -> bool:
    """Report whether we appear to be running inside a CI runner."""
    return any(os.environ.get(var) for var in _CI_VARS)


def _color_enabled() -> bool:
    """Decide whether ANSI colour should be emitted."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty()


class Console:
    """Thin, intention-revealing wrapper over :mod:`rich`.

    The methods are named for what the message *means* — ``success``,
    ``warning``, ``step`` — rather than for how it looks, so the presentation
    can change centrally without touching call sites.
    """

    def __init__(self, *, quiet: bool = False, verbose: bool = False) -> None:
        self.quiet = quiet
        self.verbose = verbose
        no_color = not _color_enabled()
        self._out = RichConsole(no_color=no_color, soft_wrap=False, highlight=False)
        self._err = RichConsole(stderr=True, no_color=no_color, highlight=False)

    # -- configuration -------------------------------------------------

    def configure(
        self, *, quiet: bool | None = None, verbose: bool | None = None
    ) -> None:
        """Update verbosity in place so the global instance stays shared."""
        if quiet is not None:
            self.quiet = quiet
        if verbose is not None:
            self.verbose = verbose

    @property
    def rich(self) -> RichConsole:
        """The underlying Rich console, for callers needing full control."""
        return self._out

    # -- primitives ----------------------------------------------------

    def print(self, *args: Any, **kwargs: Any) -> None:
        """Print unless quiet mode is on."""
        if not self.quiet:
            self._out.print(*args, **kwargs)

    def blank(self) -> None:
        """Emit one blank line."""
        self.print("")

    def raw(self, text: str) -> None:
        """Print without any markup interpretation.

        Used for captured subprocess output, which may contain square brackets
        that Rich would otherwise try to parse as style tags.
        """
        if not self.quiet:
            self._out.print(Text(text))

    # -- semantic messages ---------------------------------------------

    def header(self, title: str, subtitle: str | None = None) -> None:
        """Announce a new phase of work."""
        self.blank()
        self.print(f"[bold cyan]{title}[/bold cyan]")
        if subtitle:
            self.print(f"[dim]{subtitle}[/dim]")
        self.blank()

    def success(self, message: str) -> None:
        self.print(f"[green]✓[/green] {message}")

    def failure(self, message: str) -> None:
        """Report an error. Always written to stderr, even in quiet mode."""
        self._err.print(f"[bold red]✗[/bold red] {message}")

    def warning(self, message: str) -> None:
        self.print(f"[yellow]![/yellow] {message}")

    def info(self, message: str) -> None:
        self.print(f"[blue]i[/blue] {message}")

    def step(self, message: str) -> None:
        """A single action inside a longer operation."""
        self.print(f"  [dim]›[/dim] {message}")

    def hint(self, message: str) -> None:
        """A suggested next action."""
        self.print(f"  [dim]{message}[/dim]")

    def debug(self, message: str) -> None:
        """Detail shown only under ``--verbose``."""
        if self.verbose and not self.quiet:
            self._out.print(f"[dim]debug: {message}[/dim]")

    def error(self, message: str, *, hint: str | None = None) -> None:
        """Render a failure and its remedy together."""
        self.blank()
        self.failure(message)
        if hint:
            self._err.print(f"  [dim]{hint}[/dim]")
        self._err.print("")

    # -- structured output ---------------------------------------------

    def panel(
        self, body: str, *, title: str | None = None, style: str = "cyan"
    ) -> None:
        if not self.quiet:
            self._out.print(Panel(body, title=title, border_style=style, expand=False))

    def table(
        self,
        columns: Sequence[str],
        rows: Sequence[Sequence[str]],
        *,
        title: str | None = None,
    ) -> None:
        """Render a table; a table with no rows prints nothing."""
        if self.quiet or not rows:
            return
        table = Table(
            title=title, show_header=True, header_style="bold", box=None, pad_edge=False
        )
        for column in columns:
            table.add_column(column)
        for row in rows:
            table.add_row(*row)
        self._out.print(table)

    def bullets(self, items: Sequence[str], *, marker: str = "•") -> None:
        for item in items:
            self.print(f"  [dim]{marker}[/dim] {item}")

    def commands(self, commands: Sequence[str]) -> None:
        """Show copyable shell commands, one per line."""
        for command in commands:
            self.print(f"  [bold]{command}[/bold]")

    def code(self, source: str, *, language: str = "python") -> None:
        if not self.quiet:
            self._out.print(Syntax(source, language, theme="ansi_dark", word_wrap=True))

    def diff(self, text: str) -> None:
        """Render a unified diff with +/- colouring."""
        if self.quiet:
            return
        for line in text.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                self._out.print(Text(line, style="green"))
            elif line.startswith("-") and not line.startswith("---"):
                self._out.print(Text(line, style="red"))
            elif line.startswith("@@"):
                self._out.print(Text(line, style="cyan"))
            else:
                self._out.print(Text(line, style="dim"))

    # -- progress ------------------------------------------------------

    @contextmanager
    def progress(self, description: str) -> Iterator[None]:
        """Show a spinner for the duration of the block.

        Falls back to a plain line in CI and quiet mode, where an animated
        spinner would only produce log noise.
        """
        if self.quiet:
            yield
            return
        if is_ci() or not sys.stdout.isatty():
            self.step(description)
            yield
            return
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self._out,
            transient=True,
        ) as progress:
            progress.add_task(description, total=None)
            yield


#: Shared console. The CLI reconfigures this once from the root callback.
console = Console()
