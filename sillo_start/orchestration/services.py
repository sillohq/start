"""Development service definitions.

A service is a named long-running process the orchestrator can start: the
backend, the Vite dev server, a queue worker. Definitions are declarative and
built from the manifest, so ``sillo-start dev`` runs exactly what the project
says it needs — and a plugin can contribute a service without the orchestrator
knowing anything about it.
"""

from __future__ import annotations

import shlex
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from ..config.models import SilloManifest
from ..exceptions import UsageError
from .health import HealthCheck, PortCheck, http_check

#: Colours cycled through when prefixing interleaved output, so each service is
#: visually distinct in a combined log.
SERVICE_COLOURS = ("cyan", "magenta", "green", "yellow", "blue", "red")


@dataclass
class ServiceDefinition:
    """A process the development orchestrator can run.

    Args:
        name: Identifier used with ``--only`` and ``--without``.
        command: Shell-style command string, split with :mod:`shlex`.
        cwd: Working directory relative to the project root.
        env: Extra environment variables for the child.
        port: Port the service listens on, for conflict detection.
        url: URL to advertise once running.
        health: Check that reports whether the service is actually up.
        restart: Restart the process if it exits unexpectedly.
        depends_on: Services that should be started first.
        optional: A missing executable is a warning rather than an error.
        description: Shown in ``services status``.
    """

    name: str
    command: str
    cwd: str = "."
    env: dict[str, str] = field(default_factory=dict)
    port: int | None = None
    url: str | None = None
    health: HealthCheck | None = None
    restart: bool = True
    depends_on: tuple[str, ...] = ()
    optional: bool = False
    description: str = ""

    def argv(self) -> list[str]:
        """Split the command into an argument list.

        Raises:
            UsageError: If the command string cannot be parsed.
        """
        try:
            parts = shlex.split(self.command)
        except ValueError as exc:
            raise UsageError(
                f"Service '{self.name}' has an unparsable command: {self.command}",
                hint="Check the quoting in [development] in sillo.toml.",
            ) from exc
        if not parts:
            raise UsageError(f"Service '{self.name}' has an empty command.")
        return parts

    def working_directory(self, project_root: Path) -> Path:
        """Resolve the working directory against the project root."""
        return (project_root / self.cwd).resolve()


class ServiceRegistry:
    """Holds service definitions, in start order."""

    def __init__(self) -> None:
        self._services: dict[str, ServiceDefinition] = {}

    def register(self, service: ServiceDefinition, *, replace: bool = True) -> None:
        """Add or replace a service definition."""
        if service.name in self._services and not replace:
            raise UsageError(f"Service '{service.name}' is already registered.")
        self._services[service.name] = service

    def get(self, name: str) -> ServiceDefinition:
        """Look up a service.

        Raises:
            UsageError: If no such service is defined for this project.
        """
        try:
            return self._services[name]
        except KeyError as exc:
            raise UsageError(
                f"Unknown service: '{name}'",
                hint=f"This project defines: {', '.join(self.names()) or 'none'}.",
            ) from exc

    def names(self) -> list[str]:
        return list(self._services)

    def all(self) -> list[ServiceDefinition]:
        """Every service, ordered so dependencies come first."""
        return _in_dependency_order(list(self._services.values()))

    def select(
        self,
        *,
        only: list[str] | None = None,
        without: list[str] | None = None,
    ) -> list[ServiceDefinition]:
        """Filter the services to run.

        Args:
            only: Run just these, plus anything they depend on.
            without: Run everything except these.

        Returns:
            The services to start, in dependency order.
        """
        selected = self.all()

        if only:
            wanted: set[str] = set()
            for name in only:
                self.get(name)  # validates the name
                wanted.add(name)
                wanted.update(self._dependencies_of(name))
            selected = [s for s in selected if s.name in wanted]

        if without:
            for name in without:
                self.get(name)
            excluded = set(without)
            selected = [s for s in selected if s.name not in excluded]

        return selected

    def _dependencies_of(self, name: str) -> set[str]:
        """Transitively collect the dependencies of *name*."""
        found: set[str] = set()
        stack = [name]
        while stack:
            current = stack.pop()
            for dependency in self._services[current].depends_on:
                if dependency not in found and dependency in self._services:
                    found.add(dependency)
                    stack.append(dependency)
        return found

    def __iter__(self) -> Iterator[ServiceDefinition]:
        return iter(self.all())

    def __len__(self) -> int:
        return len(self._services)


def _in_dependency_order(services: list[ServiceDefinition]) -> list[ServiceDefinition]:
    """Sort services so each comes after the ones it depends on.

    Unknown dependencies are ignored rather than raising: a service may depend
    on one that was filtered out, and refusing to start anything because of
    that would be unhelpful.
    """
    by_name = {service.name: service for service in services}
    ordered: list[ServiceDefinition] = []
    placed: set[str] = set()

    def place(service: ServiceDefinition, seen: frozenset[str]) -> None:
        if service.name in placed or service.name in seen:
            return
        for dependency in service.depends_on:
            if dependency in by_name:
                place(by_name[dependency], seen | {service.name})
        if service.name not in placed:
            placed.add(service.name)
            ordered.append(service)

    for service in services:
        place(service, frozenset())
    return ordered


def build_registry(manifest: SilloManifest) -> ServiceRegistry:
    """Build the service registry for a project from its manifest."""
    registry = ServiceRegistry()
    development = manifest.development
    host = manifest.application.host
    port = manifest.application.port

    if development.backend_command:
        registry.register(
            ServiceDefinition(
                name="backend",
                command=development.backend_command,
                port=port,
                url=f"http://localhost:{port}",
                health=http_check(f"http://{host}:{port}/", expect_below=500),
                description="Sillo application server",
            )
        )

    if manifest.inertia.enabled and development.frontend_command:
        registry.register(
            ServiceDefinition(
                name="frontend",
                command=development.frontend_command,
                cwd=manifest.inertia.frontend_path,
                port=manifest.inertia.port,
                url=f"http://localhost:{manifest.inertia.port}",
                health=PortCheck(manifest.inertia.port),
                description=f"Vite dev server ({manifest.inertia.adapter})",
            )
        )

    if manifest.queue.enabled and development.worker_command:
        registry.register(
            ServiceDefinition(
                name="worker",
                command=development.worker_command,
                depends_on=("backend",) if development.backend_command else (),
                description=f"queue worker ({manifest.queue.driver})",
            )
        )

    if manifest.scheduler.enabled and development.scheduler_command:
        registry.register(
            ServiceDefinition(
                name="scheduler",
                command=development.scheduler_command,
                description="scheduled task runner",
            )
        )

    for name, command in development.extra_services.items():
        registry.register(ServiceDefinition(name=name, command=command, description="custom service"))

    return registry


#: Process-wide registry for services contributed by plugins. Project services
#: are built per-invocation by :func:`build_registry`.
registry = ServiceRegistry()
