"""Turning resolved package groups into operations.

The installer is the bridge between the declarative registry and the
transactional operation layer: it takes a :class:`~.resolver.Resolution` and
produces the plan that installs it. Nothing here touches the filesystem
directly — that keeps ``--dry-run`` honest and rollback possible.
"""

from __future__ import annotations

from ..config.defaults import (
    DATABASE_DRIVER_PACKAGES,
    SILLO_DISTRIBUTION,
    DatabaseDriver,
)
from ..config.models import SilloManifest
from ..operations.base import Operation
from ..operations.commands import RegisterPackageGroup
from ..operations.dependencies import InstallPythonPackage, UpdateToml
from ..operations.files import CreateDirectory, UpdateEnvironment
from ..operations.transaction import ExecutionPlan
from ..utils.pkgmanagers import PythonPackageManager, detect_python_manager
from .resolver import Resolution


def sillo_requirement(extras: list[str], version_spec: str) -> str:
    """Build the ``sillo-framework`` requirement string.

    Extras accumulate as features are added, so this is regenerated from the
    full set each time rather than appended to.

    >>> sillo_requirement(["record", "jwt"], ">=0.0.1a1")
    'sillo-framework[jwt,record]>=0.0.1a1'
    """
    if not extras:
        return f"{SILLO_DISTRIBUTION}{version_spec}"
    return f"{SILLO_DISTRIBUTION}[{','.join(sorted(set(extras)))}]{version_spec}"


def database_driver_packages(driver: DatabaseDriver | str) -> list[str]:
    """Return the async driver packages for a database backend."""
    key = DatabaseDriver(driver) if isinstance(driver, str) else driver
    return list(DATABASE_DRIVER_PACKAGES.get(key, []))


def build_install_plan(
    resolution: Resolution,
    manifest: SilloManifest,
    *,
    manager: PythonPackageManager | None = None,
    install: bool = True,
    env_files: tuple[str, ...] = (".env", ".env.example"),
    title: str | None = None,
) -> ExecutionPlan:
    """Build the plan that installs every group in *resolution*.

    The order matters and is deliberate: directories exist before files land in
    them, dependencies are declared before anything imports them, and the
    manifest is updated last so a failure leaves the project describing what it
    actually has.

    Args:
        resolution: The resolved, ordered group set.
        manifest: Project manifest, read for the version spec and updated with
            the newly enabled groups.
        manager: Python package manager. Auto-detected when omitted.
        install: Actually run the installer, rather than only declaring.
        env_files: Dotenv files that receive the groups' variables.
        title: Plan heading.

    Returns:
        The execution plan.
    """
    package_manager = manager or detect_python_manager()
    names = ", ".join(resolution.names) or "nothing"
    plan = ExecutionPlan(title or f"Install package groups: {names}")

    for directory in resolution.directories():
        plan.add(CreateDirectory(directory))

    plan.extend(
        _dependency_operations(resolution, manifest, package_manager, install=install)
    )

    variables = resolution.env_vars()
    if variables:
        for env_file in env_files:
            plan.add(
                UpdateEnvironment(env_file, list(variables), section="Feature settings")
            )

    for group in resolution.groups:
        if group.plan_hook is not None:
            plan.extend(group.plan_hook(manifest))

    for group in resolution.groups:
        plan.add(RegisterPackageGroup(group.name))

    return plan


def _dependency_operations(
    resolution: Resolution,
    manifest: SilloManifest,
    manager: PythonPackageManager,
    *,
    install: bool,
) -> list[Operation]:
    """Build the operations that declare and install Python dependencies."""
    operations: list[Operation] = []

    # Framework extras are a property of the single sillo-framework
    # requirement, so they are rewritten wholesale from the union of the
    # already-enabled groups and the new ones. Appending a second
    # `sillo-framework[...]` line would leave pip resolving two requirements
    # for the same distribution.
    extras = _accumulated_extras(resolution, manifest)
    if extras:
        requirement = sillo_requirement(extras, manifest.project.sillo_version)
        operations.append(
            UpdateToml(
                "pyproject.toml",
                remove={"project.dependencies": [SILLO_DISTRIBUTION]},
                append={"project.dependencies": [requirement]},
            )
        )

    packages = resolution.python_packages()
    if packages:
        operations.append(
            InstallPythonPackage(packages, manager=manager, install=install)
        )

    dev_packages = resolution.dev_packages()
    if dev_packages:
        operations.append(
            InstallPythonPackage(
                dev_packages, manager=manager, group="dev", install=install
            )
        )

    return operations


def _accumulated_extras(resolution: Resolution, manifest: SilloManifest) -> list[str]:
    """Union the extras of the new groups with those already enabled.

    Rewriting the requirement from only the incoming groups would drop the
    extras an earlier ``add`` installed.
    """
    from .registry import registry

    extras = set(resolution.sillo_extras())
    for name in manifest.packages.groups:
        if registry.has(name):
            extras.update(registry.get(name).sillo_extras)
    return sorted(extras)


def build_removal_plan(
    group_name: str,
    manifest: SilloManifest,
    *,
    manager: PythonPackageManager | None = None,
) -> ExecutionPlan:
    """Build the plan that removes a package group.

    Removal is deliberately conservative. Dependencies are dropped from
    ``pyproject.toml`` and the group is unregistered, but generated source
    files and directories are left in place: they may have been edited, and
    deleting a developer's controller because they removed a group would be
    exactly the kind of destructive behaviour Sillo Start avoids. The files to
    review are reported instead.

    Args:
        group_name: Group to remove.
        manifest: Project manifest, updated to drop the group.
        manager: Python package manager. Auto-detected when omitted.
    """
    from .registry import registry

    group = registry.get(group_name)
    package_manager = manager or detect_python_manager()
    plan = ExecutionPlan(f"Remove package group: {group_name}")

    if group.python_packages or group.dev_packages:
        plan.add(
            UpdateToml(
                "pyproject.toml",
                remove={
                    "project.dependencies": list(group.python_packages),
                    "project.optional-dependencies.dev": list(group.dev_packages),
                },
            )
        )

    # Recompute the framework extras without this group.
    remaining = [name for name in manifest.packages.groups if name != group_name]
    extras: set[str] = set()
    for name in remaining:
        if registry.has(name):
            extras.update(registry.get(name).sillo_extras)
    requirement = sillo_requirement(sorted(extras), manifest.project.sillo_version)
    plan.add(
        UpdateToml(
            "pyproject.toml",
            remove={"project.dependencies": [SILLO_DISTRIBUTION]},
            append={"project.dependencies": [requirement]},
        )
    )

    from ..operations.commands import UpdateManifest

    plan.add(
        UpdateManifest(
            lambda m: m.remove_group(group_name),
            description=f"disable package group '{group_name}'",
        )
    )
    _ = package_manager  # Reserved for an opt-in uninstall step.
    return plan
