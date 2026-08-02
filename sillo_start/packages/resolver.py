"""Resolving package groups into an ordered, conflict-free install set.

Groups depend on other groups (``admin`` needs ``auth``, which needs
``record``) and can declare conflicts. The resolver expands the requested set
transitively, rejects contradictions, and returns an order in which every
group comes after the ones it requires — so the admin scaffolding can assume
the user model already exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..exceptions import DependencyResolutionError
from .registry import PackageGroup, PackageRegistry
from .registry import registry as default_registry


@dataclass
class Resolution:
    """The outcome of resolving a set of requested groups."""

    #: Groups in install order: dependencies before dependents.
    groups: list[PackageGroup] = field(default_factory=list)
    #: Groups that were pulled in transitively rather than requested directly.
    implied: list[str] = field(default_factory=list)
    #: Groups already installed, so they were not re-added.
    already_present: list[str] = field(default_factory=list)

    @property
    def names(self) -> list[str]:
        return [group.name for group in self.groups]

    def sillo_extras(self) -> list[str]:
        """Every framework extra the resolved groups need, deduplicated."""
        extras: list[str] = []
        for group in self.groups:
            for extra in group.sillo_extras:
                if extra not in extras:
                    extras.append(extra)
        return sorted(extras)

    def python_packages(self) -> list[str]:
        """Every additional Python requirement, deduplicated in group order."""
        packages: list[str] = []
        for group in self.groups:
            for package in group.python_packages:
                if package not in packages:
                    packages.append(package)
        return packages

    def dev_packages(self) -> list[str]:
        packages: list[str] = []
        for group in self.groups:
            for package in group.dev_packages:
                if package not in packages:
                    packages.append(package)
        return packages

    def directories(self) -> list[str]:
        """Every directory the resolved groups expect, deduplicated."""
        directories: list[str] = []
        for group in self.groups:
            for directory in group.directories:
                if directory not in directories:
                    directories.append(directory)
        return directories

    def env_vars(self):
        """Every environment variable, first definition winning on conflict."""
        seen: set[str] = set()
        variables = []
        for group in self.groups:
            for var in group.env_vars:
                if var.key not in seen:
                    seen.add(var.key)
                    variables.append(var)
        return variables

    def post_install_notes(self) -> list[str]:
        notes: list[str] = []
        for group in self.groups:
            notes.extend(group.post_install)
        return notes


def resolve(
    requested: list[str],
    *,
    installed: list[str] | None = None,
    registry: PackageRegistry | None = None,
    include_installed: bool = False,
) -> Resolution:
    """Expand *requested* into a complete, ordered install set.

    Args:
        requested: Group names the user asked for.
        installed: Groups already present in the project. Their dependencies
            are assumed satisfied, and they are not reinstalled.
        registry: Registry to look groups up in. Defaults to the global one.
        include_installed: Return already-installed groups in the result too,
            which project creation wants (it is installing everything at once)
            and ``add`` does not.

    Returns:
        A :class:`Resolution` whose ``groups`` are ordered dependencies-first.

    Raises:
        DependencyResolutionError: On an unknown group, a conflict between two
            groups in the final set, or a dependency cycle.
    """
    source = registry or default_registry
    present = set(installed or [])

    ordered: list[PackageGroup] = []
    seen: set[str] = set()
    implied: list[str] = []
    # Names on the current DFS path, which is how a cycle is detected.
    visiting: set[str] = set()

    def visit(name: str, *, direct: bool, path: tuple[str, ...]) -> None:
        if name in seen:
            return
        if name in visiting:
            cycle = " → ".join([*path, name])
            raise DependencyResolutionError(
                f"Package groups form a dependency cycle: {cycle}",
                hint="Break the cycle by removing one of the `requires` entries.",
            )

        group = source.get(name)
        visiting.add(name)
        for requirement in group.requires:
            if requirement not in present or include_installed:
                visit(requirement, direct=False, path=(*path, name))
        visiting.discard(name)

        seen.add(name)
        if name in present and not include_installed:
            return
        if not direct and name not in present:
            implied.append(name)
        ordered.append(group)

    for name in requested:
        visit(name, direct=True, path=())

    _check_conflicts(ordered, present, include_installed=include_installed)

    return Resolution(
        groups=ordered,
        implied=implied,
        already_present=sorted(present & set(requested)),
    )


def _check_conflicts(
    resolved: list[PackageGroup],
    installed: set[str],
    *,
    include_installed: bool,
) -> None:
    """Reject a set containing groups that declared each other incompatible.

    Raises:
        DependencyResolutionError: On the first conflict found.
    """
    final = {group.name for group in resolved}
    if not include_installed:
        final |= installed

    for group in resolved:
        for other in group.conflicts:
            if other in final:
                raise DependencyResolutionError(
                    f"Package group '{group.name}' conflicts with '{other}'.",
                    hint=f"Remove one of them: `sillo-start package remove {other}`.",
                )


def dependents_of(
    name: str,
    *,
    installed: list[str],
    registry: PackageRegistry | None = None,
) -> list[str]:
    """List installed groups that require *name*.

    Used by ``package remove`` to refuse pulling a group out from under the
    ones that depend on it.
    """
    source = registry or default_registry
    dependents = []
    for candidate in installed:
        if candidate == name or not source.has(candidate):
            continue
        if name in source.get(candidate).requires:
            dependents.append(candidate)
    return sorted(dependents)


def validate_selection(
    names: list[str],
    *,
    registry: PackageRegistry | None = None,
) -> list[str]:
    """Check that every name is a known group, returning them unchanged.

    Raises:
        DependencyResolutionError: Listing every unknown name at once, rather
            than failing on the first, so a typo in a long ``--package-group``
            list is fixed in one pass.
    """
    source = registry or default_registry
    unknown = [name for name in names if not source.has(name)]
    if unknown:
        raise DependencyResolutionError(
            f"Unknown package group(s): {', '.join(unknown)}",
            hint=f"Available groups: {', '.join(source.names())}.",
        )
    return names
