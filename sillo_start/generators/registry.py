"""The generator registry and the built-in generators."""

from __future__ import annotations

from collections.abc import Iterator

from ..exceptions import GeneratorError
from .base import Generator, GeneratorTarget
from .model import ModelGenerator


class GeneratorRegistry:
    """Holds every registered generator."""

    def __init__(self) -> None:
        self._generators: dict[str, Generator] = {}

    def register(self, generator: Generator, *, replace: bool = False) -> None:
        """Add a generator.

        Raises:
            GeneratorError: If the name is taken and *replace* is false.
        """
        if generator.name in self._generators and not replace:
            raise GeneratorError(f"Generator '{generator.name}' is already registered.")
        self._generators[generator.name] = generator

    def get(self, name: str) -> Generator:
        """Look up a generator.

        Raises:
            GeneratorError: If no such generator exists.
        """
        try:
            return self._generators[name]
        except KeyError as exc:
            raise GeneratorError(
                f"Unknown generator: '{name}'",
                hint=f"Available: {', '.join(self.names())}.",
            ) from exc

    def has(self, name: str) -> bool:
        return name in self._generators

    def names(self) -> list[str]:
        return sorted(self._generators)

    def all(self) -> list[Generator]:
        return [self._generators[name] for name in self.names()]

    def __iter__(self) -> Iterator[Generator]:
        return iter(self.all())

    def __len__(self) -> int:
        return len(self._generators)


registry = GeneratorRegistry()


#: The built-in generators. Everything except the model generator is a plain
#: template mapping — which is the point of the declarative shape.
BUILTIN_GENERATORS = (
    ModelGenerator(),
    Generator(
        name="controller",
        summary="An HTTP controller class.",
        suffix="Controller",
        targets=(
            GeneratorTarget(
                "generators/controller.py.j2", "app/http/controllers/{snake}.py"
            ),
        ),
    ),
    Generator(
        name="service",
        summary="A service class for business logic.",
        suffix="Service",
        targets=(GeneratorTarget("generators/service.py.j2", "app/services/{snake}.py"),),
    ),
    Generator(
        name="repository",
        summary="A repository wrapping data access for one model.",
        suffix="Repository",
        requires=("uses_record",),
        targets=(
            GeneratorTarget("generators/repository.py.j2", "app/repositories/{snake}.py"),
        ),
    ),
    Generator(
        name="policy",
        summary="An authorization policy for one model.",
        suffix="Policy",
        targets=(GeneratorTarget("generators/policy.py.j2", "app/policies/{snake}.py"),),
    ),
    Generator(
        name="middleware",
        summary="A request/response middleware.",
        suffix="Middleware",
        targets=(
            GeneratorTarget("generators/middleware.py.j2", "app/http/middleware/{snake}.py"),
        ),
    ),
    Generator(
        name="request",
        summary="A Pydantic model validating a request body.",
        suffix="Request",
        targets=(GeneratorTarget("generators/schema.py.j2", "app/http/requests/{snake}.py"),),
    ),
    Generator(
        name="resource",
        summary="A response transformer for one model.",
        suffix="Resource",
        targets=(
            GeneratorTarget("generators/resource.py.j2", "app/http/resources/{snake}.py"),
        ),
    ),
    Generator(
        name="job",
        summary="A queued background job.",
        suffix="Job",
        requires=("queue.enabled",),
        targets=(GeneratorTarget("generators/job.py.j2", "app/jobs/{snake}.py"),),
    ),
    Generator(
        name="task",
        summary="A scheduled task.",
        suffix="Task",
        requires=("scheduler.enabled",),
        targets=(GeneratorTarget("generators/task.py.j2", "app/tasks/{snake}.py"),),
    ),
    Generator(
        name="event",
        summary="A domain event.",
        targets=(GeneratorTarget("generators/event.py.j2", "app/events/{snake}.py"),),
    ),
    Generator(
        name="listener",
        summary="A handler reacting to a domain event.",
        suffix="Listener",
        targets=(GeneratorTarget("generators/listener.py.j2", "app/listeners/{snake}.py"),),
    ),
    Generator(
        name="seeder",
        summary="A database seeder.",
        suffix="Seeder",
        requires=("uses_record",),
        targets=(GeneratorTarget("generators/seeder.py.j2", "database/seeders/{snake}.py"),),
    ),
    Generator(
        name="factory",
        summary="A model factory for tests.",
        suffix="Factory",
        requires=("uses_record",),
        targets=(
            GeneratorTarget("generators/factory.py.j2", "database/factories/{snake}.py"),
        ),
    ),
    Generator(
        name="test",
        summary="A test module.",
        targets=(GeneratorTarget("generators/test.py.j2", "tests/unit/test_{snake}.py"),),
    ),
    Generator(
        name="page",
        summary="An Inertia page component.",
        requires=("inertia.enabled",),
        targets=(),  # Rendered by the Inertia feature, which knows the adapter.
    ),
)


def register_builtins(target: GeneratorRegistry = registry) -> None:
    """Register every built-in generator."""
    for generator in BUILTIN_GENERATORS:
        target.register(generator, replace=True)


register_builtins()
