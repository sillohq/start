"""Interleaving output from several processes.

Running four servers in one terminal is only useful if you can tell which line
came from which. The multiplexer prefixes every line with a padded, coloured
service name, and serialises writes so two processes cannot interleave halves
of a line.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from rich.text import Text

from ..utils.console import Console
from ..utils.console import console as default_console


@dataclass
class LogMultiplexer:
    """Serialises prefixed output from concurrent processes.

    Args:
        console: Where to write.
        colours: Colour cycle assigned to services in registration order.
    """

    console: Console = field(default_factory=lambda: default_console)
    colours: tuple[str, ...] = ("cyan", "magenta", "green", "yellow", "blue", "red")
    _assigned: dict[str, str] = field(default_factory=dict, init=False)
    _width: int = field(default=0, init=False)
    # Writes come from one reader thread per process, so the terminal needs a
    # lock or lines from different services will interleave mid-line.
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def register(self, name: str) -> None:
        """Assign a colour to a service and widen the prefix column."""
        if name not in self._assigned:
            self._assigned[name] = self.colours[len(self._assigned) % len(self.colours)]
        self._width = max(self._width, len(name))

    def write(self, service: str, line: str) -> None:
        """Write one line of output attributed to *service*."""
        line = line.rstrip("\n")
        if not line:
            return
        colour = self._assigned.get(service, "white")
        prefix = Text(f"{service.ljust(self._width)} │ ", style=colour)
        with self._lock:
            self.console.rich.print(prefix + Text(line), soft_wrap=True)

    def notice(self, service: str, message: str) -> None:
        """Write a status line about a service, distinct from its own output."""
        colour = self._assigned.get(service, "white")
        prefix = Text(f"{service.ljust(self._width)} │ ", style=colour)
        with self._lock:
            self.console.rich.print(prefix + Text(message, style="dim"))

    def banner(self, services: list[tuple[str, str | None]]) -> None:
        """Print the service table shown when the orchestrator starts."""
        self.console.blank()
        self.console.print("[bold]Running[/bold]")
        for name, url in services:
            colour = self._assigned.get(name, "white")
            label = f"[{colour}]{name.ljust(self._width)}[/{colour}]"
            self.console.print(f"  {label}   {url or ''}")
        self.console.blank()
        self.console.hint("Press Ctrl+C to stop everything.")
        self.console.blank()
