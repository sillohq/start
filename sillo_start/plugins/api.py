"""The plugin API.

A third-party Sillo package extends Sillo Start by exposing a callable under
the ``sillo_start.plugins`` entry point group. That callable receives a
:class:`Plugin` and registers whatever it adds::

    # my_package/sillo_start.py
    from sillo_start.plugins import Plugin, PackageGroup

    def plugin(registry: Plugin) -> None:
        registry.register_package_group(
            PackageGroup(name="search", summary="Full-text search.", ...)
        )

Declared in the plugin's own ``pyproject.toml``::

    [project.entry-points."sillo_start.plugins"]
    my_plugin = "my_package.sillo_start:plugin"

Registration goes through this object rather than letting plugins import the
global registries directly, which keeps one place to validate what is being
added and to attribute a failure to the plugin that caused it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..blueprints.base import Blueprint
from ..blueprints.registry import registry as blueprint_registry
from ..exceptions import PluginError
from ..packages.registry import PackageGroup
from ..packages.registry import registry as package_registry

if TYPE_CHECKING:
    from ..generators.base import Generator
    from ..orchestration.services import ServiceDefinition


@dataclass
class Plugin:
    """The registration surface handed to a plugin.

    Args:
        name: The entry point name, used to attribute errors.
    """

    name: str
    #: Everything this plugin registered, for `sillo-start doctor` to report.
    registered: dict[str, list[str]] = field(default_factory=dict)

    def _record(self, kind: str, item: str) -> None:
        self.registered.setdefault(kind, []).append(item)

    def register_package_group(self, group: PackageGroup) -> None:
        """Add a package group.

        Raises:
            PluginError: If the name collides with an existing group.
        """
        if package_registry.has(group.name):
            raise PluginError(
                f"Plugin '{self.name}' tried to register package group "
                f"'{group.name}', which already exists."
            )
        package_registry.register(group)
        self._record("package_groups", group.name)

    def register_blueprint(self, blueprint: Blueprint) -> None:
        """Add a project blueprint.

        Raises:
            PluginError: If the name collides with an existing blueprint.
        """
        if blueprint_registry.has(blueprint.name):
            raise PluginError(
                f"Plugin '{self.name}' tried to register blueprint "
                f"'{blueprint.name}', which already exists."
            )
        blueprint_registry.register(blueprint)
        self._record("blueprints", blueprint.name)

    def register_generator(self, generator: Generator) -> None:
        """Add a component generator."""
        from ..generators.registry import registry as generator_registry

        generator_registry.register(generator)
        self._record("generators", generator.name)

    def register_service(self, service: ServiceDefinition) -> None:
        """Add a development service the orchestrator can run."""
        from ..orchestration.services import registry as service_registry

        service_registry.register(service)
        self._record("services", service.name)

    def register_doctor_check(self, check: Callable[..., Any]) -> None:
        """Add a diagnostic run by ``sillo-start doctor``."""
        from ..cli.doctor import register_check

        register_check(check)
        self._record("doctor_checks", getattr(check, "__name__", "check"))


#: Entry point group third-party packages publish under.
ENTRY_POINT_GROUP = "sillo_start.plugins"
