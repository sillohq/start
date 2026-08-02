"""The blueprint registry."""

from __future__ import annotations

from collections.abc import Iterator

from ..exceptions import BlueprintError
from .base import Blueprint


class BlueprintRegistry:
    """Holds every known blueprint, built-in and plugin-supplied."""

    def __init__(self) -> None:
        self._blueprints: dict[str, Blueprint] = {}

    def register(self, blueprint: Blueprint, *, replace: bool = False) -> None:
        """Add a blueprint.

        Raises:
            BlueprintError: If the name is taken and *replace* is false.
        """
        if blueprint.name in self._blueprints and not replace:
            raise BlueprintError(
                f"Blueprint '{blueprint.name}' is already registered.",
                hint="Pass replace=True if the override is intentional.",
            )
        self._blueprints[blueprint.name] = blueprint

    def get(self, name: str) -> Blueprint:
        """Look up a blueprint.

        Raises:
            BlueprintError: If no such blueprint exists.
        """
        try:
            return self._blueprints[name]
        except KeyError as exc:
            raise BlueprintError(
                f"Unknown blueprint: '{name}'",
                hint=f"Available blueprints: {', '.join(self.names())}.",
            ) from exc

    def has(self, name: str) -> bool:
        return name in self._blueprints

    def names(self) -> list[str]:
        return sorted(self._blueprints)

    def all(self) -> list[Blueprint]:
        return [self._blueprints[name] for name in self.names()]

    def __iter__(self) -> Iterator[Blueprint]:
        return iter(self.all())

    def __len__(self) -> int:
        return len(self._blueprints)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._blueprints


#: The process-wide blueprint registry.
registry = BlueprintRegistry()


def register_builtins(target: BlueprintRegistry = registry) -> None:
    """Register every built-in blueprint."""
    from .builtins import BUILTIN_BLUEPRINTS

    for blueprint in BUILTIN_BLUEPRINTS:
        target.register(blueprint, replace=True)


register_builtins()
