"""A single supervised child process.

Each process gets one reader thread that pumps its combined output into the log
multiplexer. Reading in a thread rather than polling means output appears as
the child produces it, and a chatty service cannot starve a quiet one.

Shutdown is staged — SIGTERM to the whole process group, then SIGKILL if the
child ignores it. Signalling the group matters: ``uvicorn --reload`` and
``vite`` both spawn children of their own, and terminating only the parent
leaves those orphaned and holding their ports.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .logging import LogMultiplexer
from .services import ServiceDefinition


class ProcessState(str, Enum):
    """Where a supervised process is in its lifecycle."""

    PENDING = "pending"
    STARTING = "starting"
    RUNNING = "running"
    UNHEALTHY = "unhealthy"
    STOPPING = "stopping"
    STOPPED = "stopped"
    CRASHED = "crashed"
    FAILED = "failed"


#: Seconds to wait after SIGTERM before escalating to SIGKILL.
GRACE_PERIOD = 5.0
#: Restarts allowed inside RESTART_WINDOW before we stop trying.
MAX_RESTARTS = 3
RESTART_WINDOW = 60.0


@dataclass
class ManagedProcess:
    """One child process under supervision.

    Args:
        definition: What to run.
        project_root: Directory the service's ``cwd`` is relative to.
        multiplexer: Where output goes.
    """

    definition: ServiceDefinition
    project_root: Path
    multiplexer: LogMultiplexer
    state: ProcessState = ProcessState.PENDING
    popen: subprocess.Popen | None = field(default=None, repr=False)
    started_at: float = 0.0
    exit_code: int | None = None
    restarts: int = 0
    _restart_times: list[float] = field(default_factory=list, repr=False)
    _reader: threading.Thread | None = field(default=None, repr=False)
    _stopping: bool = field(default=False, repr=False)

    @property
    def name(self) -> str:
        return self.definition.name

    @property
    def alive(self) -> bool:
        """Whether the child is still running."""
        return self.popen is not None and self.popen.poll() is None

    @property
    def uptime(self) -> float:
        """Seconds since the process started, or 0 when not running."""
        return time.monotonic() - self.started_at if self.alive else 0.0

    def start(self) -> None:
        """Launch the process and begin pumping its output."""
        self.state = ProcessState.STARTING
        self._stopping = False
        argv = self.definition.argv()
        cwd = self.definition.working_directory(self.project_root)

        env = {
            **os.environ,
            **self.definition.env,
            # Unbuffered output, or the child's logs arrive in chunks minutes late.
            "PYTHONUNBUFFERED": "1",
            "FORCE_COLOR": "1",
        }

        try:
            self.popen = subprocess.Popen(  # noqa: S603 — argv list, never shell=True
                argv,
                cwd=str(cwd),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                **_process_group_kwargs(),
            )
        except FileNotFoundError:
            self.state = ProcessState.FAILED
            self.multiplexer.notice(
                self.name, f"command not found: {argv[0]} — is it installed and on PATH?"
            )
            return
        except OSError as exc:
            self.state = ProcessState.FAILED
            self.multiplexer.notice(self.name, f"could not start: {exc}")
            return

        self.started_at = time.monotonic()
        self.state = ProcessState.RUNNING
        self._reader = threading.Thread(target=self._pump, name=f"log-{self.name}", daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        """Forward the child's output until the stream closes."""
        stream = self.popen.stdout if self.popen else None
        if stream is None:
            return
        try:
            for line in stream:
                self.multiplexer.write(self.name, line)
        except (ValueError, OSError):
            # The pipe was closed while we were reading, which is what happens
            # on shutdown. Nothing to report.
            pass

    def poll(self) -> ProcessState:
        """Check the child and update its state.

        Returns:
            The current state. A process that exited on its own becomes
            ``CRASHED`` unless we asked it to stop.
        """
        if self.popen is None or self.state in (ProcessState.FAILED, ProcessState.STOPPED):
            return self.state
        code = self.popen.poll()
        if code is None:
            return self.state

        self.exit_code = code
        if self._stopping or code in (0, -signal.SIGTERM, -signal.SIGINT):
            self.state = ProcessState.STOPPED
        else:
            self.state = ProcessState.CRASHED
            self.multiplexer.notice(self.name, f"exited unexpectedly with code {code}")
        return self.state

    def should_restart(self) -> bool:
        """Decide whether a crashed process is worth restarting.

        A service that crashes repeatedly in a short window is misconfigured,
        not flaky. Restarting it forever would bury the error in a scroll of
        identical tracebacks, so we give up and say so.
        """
        if not self.definition.restart or self._stopping:
            return False

        now = time.monotonic()
        self._restart_times = [t for t in self._restart_times if now - t < RESTART_WINDOW]
        if len(self._restart_times) >= MAX_RESTARTS:
            self.multiplexer.notice(
                self.name,
                f"crashed {MAX_RESTARTS} times in {int(RESTART_WINDOW)}s — not restarting again",
            )
            self.state = ProcessState.FAILED
            return False

        self._restart_times.append(now)
        self.restarts += 1
        return True

    def restart(self) -> None:
        """Stop the process if needed and start it again."""
        self.multiplexer.notice(self.name, "restarting…")
        self.stop()
        self.start()

    def stop(self, *, grace: float = GRACE_PERIOD) -> None:
        """Stop the process, escalating to SIGKILL if it does not exit."""
        if self.popen is None or self.popen.poll() is not None:
            self.state = ProcessState.STOPPED
            return

        self._stopping = True
        self.state = ProcessState.STOPPING
        _signal_group(self.popen, signal.SIGTERM)

        try:
            self.popen.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            self.multiplexer.notice(self.name, "did not stop in time — killing")
            _signal_group(self.popen, signal.SIGKILL)
            try:
                self.popen.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self.multiplexer.notice(self.name, "could not be killed; it may still be running")

        self.state = ProcessState.STOPPED

    def health(self) -> bool | None:
        """Run the service's health check.

        Returns:
            True or False when a check is configured, ``None`` when there is
            nothing to check — which is not the same as unhealthy.
        """
        if self.definition.health is None:
            return None
        return self.definition.health.check()


def _process_group_kwargs() -> dict:
    """Platform-specific arguments that put the child in its own group.

    A new group is what lets us signal the child *and its children* together.
    On Windows there are no process groups in the POSIX sense, so a new console
    group is used instead.
    """
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _signal_group(popen: subprocess.Popen, sig: int) -> None:
    """Send *sig* to the child's whole process group, falling back to the child.

    The fallback matters: the group may already be gone if the child exited
    between our poll and this call, and on Windows there is no group to signal.
    """
    try:
        if sys.platform == "win32":
            popen.terminate() if sig == signal.SIGTERM else popen.kill()
            return
        os.killpg(os.getpgid(popen.pid), sig)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            popen.terminate() if sig == signal.SIGTERM else popen.kill()
        except OSError:
            pass
