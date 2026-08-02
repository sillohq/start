"""Package group definitions and the registry that holds them.

A *package group* is a declarative bundle: the Python and frontend packages a
capability needs, the environment variables and directories it expects, and the
other groups it requires or conflicts with. Nothing here is hard-coded into a
CLI command — commands ask the registry, so a plugin can add a group and have
it appear everywhere without touching Sillo Start.

An important property of the Sillo ecosystem shapes these definitions: most
capabilities live *inside* ``sillo-framework`` rather than in separate
distributions. A group therefore usually contributes framework *extras* (which
become ``sillo-framework[record,jwt]``) rather than new packages, and several
groups legitimately need no dependencies at all because the code is already
first-party in core.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..exceptions import PackageGroupError
from ..utils.environment import EnvVar

if TYPE_CHECKING:
    from ..config.models import SilloManifest
    from ..operations.base import Operation


@dataclass(frozen=True)
class PackageGroup:
    """One installable capability.

    Args:
        name: Identifier used on the command line and in the manifest.
        summary: One-line description for ``package list``.
        description: Longer explanation for ``package info``.
        sillo_extras: Extras added to the ``sillo-framework`` requirement.
        python_packages: Additional PEP 508 requirements.
        dev_packages: Requirements added to the ``dev`` optional group.
        frontend_packages: npm dependencies.
        frontend_dev_packages: npm dev dependencies.
        env_vars: Environment variables written to ``.env`` and ``.env.example``.
        directories: Directories created, relative to the project root.
        requires: Groups that must be installed alongside this one.
        conflicts: Groups that cannot coexist with this one.
        requires_database: The group only makes sense with a database.
        provides: Capability tags other groups can require, which lets several
            groups satisfy the same need.
        plan_hook: Optional callable contributing extra operations at install
            time — for the file scaffolding a group needs beyond its
            directories.
        post_install: Human-readable follow-up steps shown after installing.
    """

    name: str
    summary: str
    description: str = ""
    sillo_extras: tuple[str, ...] = ()
    python_packages: tuple[str, ...] = ()
    dev_packages: tuple[str, ...] = ()
    frontend_packages: tuple[str, ...] = ()
    frontend_dev_packages: tuple[str, ...] = ()
    env_vars: tuple[EnvVar, ...] = ()
    directories: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    requires_database: bool = False
    provides: tuple[str, ...] = ()
    plan_hook: Callable[[SilloManifest], list[Operation]] | None = field(
        default=None, repr=False
    )
    post_install: tuple[str, ...] = ()

    def all_python_packages(self) -> list[str]:
        """Every Python requirement this group contributes, excluding extras.

        The framework extras are applied to the existing ``sillo-framework``
        requirement rather than added as a separate package, so they are not
        included here.
        """
        return list(self.python_packages)

    def compatible_with(self, manifest: SilloManifest) -> tuple[bool, str]:
        """Check this group against a project's current configuration.

        Returns:
            A pair of (compatible, reason). The reason is empty when compatible.
        """
        if self.requires_database and not manifest.database.enabled:
            return False, f"'{self.name}' needs a database, but none is configured"
        for other in self.conflicts:
            if manifest.has_group(other):
                return False, f"'{self.name}' conflicts with the installed '{other}' group"
        return True, ""


class PackageRegistry:
    """Holds every known package group.

    Built-in groups are registered at import; plugins add theirs through
    :meth:`register`. Lookups raise a :class:`PackageGroupError` naming the
    valid options, so a typo produces a useful message rather than a KeyError.
    """

    def __init__(self) -> None:
        self._groups: dict[str, PackageGroup] = {}

    def register(self, group: PackageGroup, *, replace: bool = False) -> None:
        """Add a group to the registry.

        Args:
            group: The group to register.
            replace: Permit overriding an existing name. Off by default so a
                plugin cannot silently redefine a built-in group.

        Raises:
            PackageGroupError: If the name is taken and *replace* is false.
        """
        if group.name in self._groups and not replace:
            raise PackageGroupError(
                f"Package group '{group.name}' is already registered.",
                hint="Pass replace=True if the override is intentional.",
            )
        self._groups[group.name] = group

    def get(self, name: str) -> PackageGroup:
        """Look up a group by name.

        Raises:
            PackageGroupError: If no such group exists.
        """
        try:
            return self._groups[name]
        except KeyError as exc:
            raise PackageGroupError(
                f"Unknown package group: '{name}'",
                hint=f"Available groups: {', '.join(sorted(self._groups))}.",
            ) from exc

    def has(self, name: str) -> bool:
        return name in self._groups

    def names(self) -> list[str]:
        """Every registered group name, sorted."""
        return sorted(self._groups)

    def all(self) -> list[PackageGroup]:
        """Every registered group, sorted by name."""
        return [self._groups[name] for name in self.names()]

    def providers_of(self, capability: str) -> list[PackageGroup]:
        """Groups that advertise *capability* in their ``provides``."""
        return [group for group in self.all() if capability in group.provides]

    def __iter__(self) -> Iterator[PackageGroup]:
        return iter(self.all())

    def __len__(self) -> int:
        return len(self._groups)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._groups


#: The process-wide registry. Populated by ``packages.definitions`` at import
#: and extended by plugins during CLI startup.
registry = PackageRegistry()
