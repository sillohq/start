"""Running several development services together.

The supervisor starts the selected services, interleaves their output, watches
for crashes, and stops everything cleanly on Ctrl+C. It deliberately does the
boring things carefully: checking ports before starting, so a conflict is one
clear message rather than four confusing ones; and stopping in reverse start
order, so a worker goes down before the database it talks to.
"""

from __future__ import annotations

import signal
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..exceptions import UsageError
from ..utils.console import Console
from ..utils.console import console as default_console
from ..utils.ports import is_port_in_use
from .logging import LogMultiplexer
from .process import ManagedProcess, ProcessState
from .services import ServiceDefinition

#: How often the supervisor checks on its children.
POLL_INTERVAL = 0.5
#: How long to wait for services to report healthy before showing the banner.
READY_TIMEOUT = 20.0


@dataclass
class ProcessSupervisor:
    """Starts, watches and stops a set of services.

    Args:
        project_root: Directory the services run relative to.
        console: Where status output goes.
    """

    project_root: Path
    console: Console = field(default_factory=lambda: default_console)
    processes: dict[str, ManagedProcess] = field(default_factory=dict)
    multiplexer: LogMultiplexer = field(init=False)
    _stop_requested: threading.Event = field(default_factory=threading.Event, init=False)

    def __post_init__(self) -> None:
        self.multiplexer = LogMultiplexer(console=self.console)

    # -- lifecycle ------------------------------------------------------

    def add(self, definition: ServiceDefinition) -> ManagedProcess:
        """Register a service to supervise."""
        self.multiplexer.register(definition.name)
        process = ManagedProcess(
            definition=definition,
            project_root=self.project_root,
            multiplexer=self.multiplexer,
        )
        self.processes[definition.name] = process
        return process

    def check_ports(self) -> list[str]:
        """Report services whose port is already taken.

        Checked before anything starts, because the alternative — three
        services starting and the fourth dying with EADDRINUSE — is much harder
        to read.
        """
        conflicts = []
        for process in self.processes.values():
            port = process.definition.port
            if port is not None and is_port_in_use(port):
                conflicts.append(f"{process.name} needs port {port}, which is already in use")
        return conflicts

    def start_all(self, *, wait_for_health: bool = True) -> None:
        """Start every registered service.

        Raises:
            UsageError: If a required port is already in use.
        """
        conflicts = self.check_ports()
        if conflicts:
            raise UsageError(
                "Port conflict:\n  " + "\n  ".join(conflicts),
                hint="Stop whatever is using the port, or change it in sillo.toml.",
            )

        for process in self.processes.values():
            self.multiplexer.notice(process.name, f"starting: {process.definition.command}")
            process.start()

        if wait_for_health:
            self.wait_until_ready()

        self.multiplexer.banner(
            [(p.name, p.definition.url) for p in self.processes.values()]
        )

    def wait_until_ready(self, timeout: float = READY_TIMEOUT) -> None:
        """Wait for services with health checks to come up.

        Returns once every checkable service is healthy, or when *timeout*
        expires — a slow service is reported, not fatal, because it may simply
        be a cold Vite build.
        """
        pending = [p for p in self.processes.values() if p.definition.health is not None]
        if not pending:
            return

        deadline = time.monotonic() + timeout
        while pending and time.monotonic() < deadline:
            if self._stop_requested.is_set():
                return
            still_pending = []
            for process in pending:
                if not process.alive:
                    continue
                if process.health():
                    self.multiplexer.notice(process.name, "ready")
                else:
                    still_pending.append(process)
            pending = still_pending
            if pending:
                time.sleep(POLL_INTERVAL)

        for process in pending:
            if process.alive:
                self.multiplexer.notice(process.name, "still starting up")

    def watch(self) -> int:
        """Supervise until interrupted or every service has stopped.

        Returns:
            The process exit code: 0 for a clean shutdown, 1 if a service
            failed and could not be restarted.
        """
        self._install_signal_handlers()

        try:
            while not self._stop_requested.is_set():
                if not self._tick():
                    break
                time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            # Reached when the interrupt lands outside the handler's window.
            self._stop_requested.set()

        self.stop_all()
        failed = [p.name for p in self.processes.values() if p.state is ProcessState.FAILED]
        if failed:
            self.console.blank()
            self.console.failure(f"Service(s) failed: {', '.join(failed)}")
            return 1
        return 0

    def _tick(self) -> bool:
        """Check every process once.

        Returns:
            False when there is nothing left worth watching.
        """
        active = False
        for process in self.processes.values():
            state = process.poll()
            if state is ProcessState.CRASHED:
                if process.should_restart():
                    process.restart()
                    active = True
            elif state in (ProcessState.RUNNING, ProcessState.STARTING):
                active = True
        return active

    def stop_all(self) -> None:
        """Stop every service, in reverse start order."""
        running = [p for p in self.processes.values() if p.alive]
        if not running:
            return

        self.console.blank()
        self.console.info("Stopping services…")
        for process in reversed(list(self.processes.values())):
            if process.alive:
                self.multiplexer.notice(process.name, "stopping")
                process.stop()
        self.console.success("All services stopped.")

    def _install_signal_handlers(self) -> None:
        """Translate SIGINT/SIGTERM into a clean shutdown.

        Handlers can only be installed on the main thread; when the supervisor
        runs elsewhere (in tests, say) we fall back to relying on
        KeyboardInterrupt.
        """

        def handler(signum, frame):  # noqa: ANN001, ARG001 — signal handler signature
            if self._stop_requested.is_set():
                # A second Ctrl+C means the user wants out now.
                self.console.warning("Forcing shutdown…")
                for process in self.processes.values():
                    process.stop(grace=0.5)
                raise SystemExit(130)
            self._stop_requested.set()

        try:
            signal.signal(signal.SIGINT, handler)
            signal.signal(signal.SIGTERM, handler)
        except ValueError:
            self.console.debug("signal handlers unavailable off the main thread")

    # -- reporting ------------------------------------------------------

    def status(self) -> list[dict]:
        """Describe each supervised service, for ``services status``."""
        rows = []
        for process in self.processes.values():
            health = process.health()
            rows.append(
                {
                    "name": process.name,
                    "state": process.state.value,
                    "pid": process.popen.pid if process.popen else None,
                    "uptime": round(process.uptime, 1),
                    "restarts": process.restarts,
                    "healthy": health,
                    "url": process.definition.url,
                    "command": process.definition.command,
                }
            )
        return rows
