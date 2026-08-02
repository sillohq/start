"""Computing a project's directory layout.

Only the directories a project's enabled features actually need are created.
A minimal API does not get ``app/jobs/`` it will never fill, and the layout is
still predictable: the same feature always lands in the same place, so someone
moving between two Sillo projects knows where to look.
"""

from __future__ import annotations

from pathlib import Path

from ..config.defaults import DatabaseDriver
from ..config.models import SilloManifest

#: Directories that must be importable Python packages, and so need an
#: ``__init__.py``. Directories holding data or assets deliberately do not.
PACKAGE_DIRECTORIES = {
    "app",
    "app/jobs",
    "app/tasks",
    "database",
    "database/models",
    "routes",
    "tests",
}

#: Directories that should survive a fresh clone despite being empty, because
#: the application writes into them at runtime and will not create them itself.
#:
#: Nothing else is scaffolded empty. Generators create their own target
#: directories on demand (``fs.write_text`` makes parents), so shipping an
#: ``app/http/controllers/`` holding one docstring only invites the question of
#: what it is for.
KEEP_EMPTY = {
    "storage/app",
}


def package_directories(directories: list[str]) -> list[str]:
    """Select the directories that need an ``__init__.py``.

    Parent packages are included even when only a subdirectory was requested,
    since ``database/models`` is not importable without ``database``.
    """
    needed: set[str] = set()
    for directory in directories:
        normalised = directory.replace("\\", "/").strip("/")
        parts = normalised.split("/")
        for index in range(1, len(parts) + 1):
            candidate = "/".join(parts[:index])
            if candidate in PACKAGE_DIRECTORIES:
                needed.add(candidate)
    return sorted(needed)


def directories_for(manifest: SilloManifest, extra: list[str] | None = None) -> list[str]:
    """Compute every directory a project needs.

    Args:
        manifest: The project configuration.
        extra: Additional directories, typically from the blueprint and the
            resolved package groups.

    Returns:
        Directory paths relative to the project root, deduplicated and sorted
        so parents are created before children.
    """
    directories: list[str] = ["app", "routes"]

    if manifest.uses_record:
        directories += ["database", "database/models", manifest.database.migrations_path]
        # SQLite writes its file into storage/, and the driver will not create
        # the directory itself — a missing storage/ is "unable to open database
        # file" on the first query.
        if manifest.database.driver == DatabaseDriver.SQLITE:
            directories.append("storage")
    if manifest.tooling.pytest:
        directories.append("tests")
    # The admin panel is generated as the single module app/admin.py. Creating
    # an app/admin/ package as well would shadow it on import.
    if manifest.queue.enabled:
        directories.append("app/jobs")
    if manifest.scheduler.enabled:
        directories.append("app/tasks")
    if manifest.storage.enabled:
        directories.append(manifest.storage.path)
    if manifest.inertia.enabled:
        directories += [
            "templates",
            f"{manifest.inertia.frontend_path}/src/pages",
            f"{manifest.inertia.frontend_path}/src/layouts",
            f"{manifest.inertia.frontend_path}/src/components",
            f"{manifest.inertia.frontend_path}/public",
        ]
    if manifest.tooling.docker or manifest.tooling.compose:
        directories.append("docker")

    directories.extend(extra or [])

    # Sorting puts parents ahead of children, which matters because each
    # directory is created as its own operation.
    return sorted(dict.fromkeys(d.replace("\\", "/").strip("/") for d in directories if d))


def init_file_content(package: str) -> str:
    """Return the body of a generated ``__init__.py``.

    Naming the package in a one-line docstring is more useful than an empty
    file when the module shows up in a traceback or an editor's outline.
    """
    label = package.replace("/", ".")
    return f'"""{label} package."""\n'


def should_keep_empty(directory: str) -> bool:
    """Report whether *directory* needs a ``.gitkeep``."""
    return directory in KEEP_EMPTY


def describe_tree(root: Path, manifest: SilloManifest) -> list[str]:
    """List the project's directories relative to *root*, for reporting."""
    return [
        str(path.relative_to(root))
        for path in sorted(root.rglob("*"))
        if path.is_dir() and not _is_noise(path)
    ]


def _is_noise(path: Path) -> bool:
    """Filter out directories nobody wants listed in a summary."""
    noisy = {"__pycache__", ".git", "node_modules", ".venv", ".pytest_cache", ".ruff_cache"}
    return any(part in noisy for part in path.parts)
