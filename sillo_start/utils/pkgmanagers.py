"""Package manager abstractions for Python and frontend dependencies.

Sillo Start prefers ``uv`` and, on the frontend, whichever manager the project
selected — but it must never *require* one. Each manager is a small adapter
that knows how to phrase add/remove/install/run for its tool, so calling code
expresses intent ("add these packages") and never branches on which tool is in
use.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path

from ..exceptions import ToolNotFoundError
from .subprocess import CommandResult, run, tool_exists


class PythonPackageManager(ABC):
    """Adds and removes Python dependencies for a generated project."""

    #: Executable name, also the manifest value.
    name: str

    @abstractmethod
    def add_command(self, packages: Sequence[str], *, group: str | None = None) -> list[str]:
        """Build the command that adds *packages*."""

    @abstractmethod
    def remove_command(self, packages: Sequence[str]) -> list[str]:
        """Build the command that removes *packages*."""

    @abstractmethod
    def sync_command(self) -> list[str]:
        """Build the command that installs the project's declared dependencies."""

    @abstractmethod
    def run_prefix(self) -> list[str]:
        """Prefix that runs a command inside the project environment."""

    def available(self) -> bool:
        """Report whether the tool is installed."""
        return tool_exists(self.name)

    def add(self, packages: Sequence[str], *, cwd: Path, group: str | None = None) -> CommandResult:
        return run(self.add_command(packages, group=group), cwd=cwd)

    def remove(self, packages: Sequence[str], *, cwd: Path) -> CommandResult:
        return run(self.remove_command(packages), cwd=cwd)

    def sync(self, *, cwd: Path) -> CommandResult:
        return run(self.sync_command(), cwd=cwd)


class UvManager(PythonPackageManager):
    """``uv`` — the preferred manager.

    ``uv add`` edits ``pyproject.toml`` and the lockfile itself, so Sillo Start
    does not also write the dependency into the file: doing both would produce
    a duplicate entry.
    """

    name = "uv"

    def add_command(self, packages: Sequence[str], *, group: str | None = None) -> list[str]:
        command = ["uv", "add", *packages]
        if group:
            command.extend(["--group", group])
        return command

    def remove_command(self, packages: Sequence[str]) -> list[str]:
        return ["uv", "remove", *packages]

    def sync_command(self) -> list[str]:
        return ["uv", "sync"]

    def run_prefix(self) -> list[str]:
        return ["uv", "run"]


class PipManager(PythonPackageManager):
    """``pip`` fallback.

    pip does not record dependencies in ``pyproject.toml``, so when this
    manager is selected the installer writes the requirement into the file
    itself before installing.
    """

    name = "pip"
    #: Signals to the installer that it owns writing the manifest entry.
    writes_manifest = False

    def add_command(self, packages: Sequence[str], *, group: str | None = None) -> list[str]:
        return ["pip", "install", *packages]

    def remove_command(self, packages: Sequence[str]) -> list[str]:
        return ["pip", "uninstall", "-y", *packages]

    def sync_command(self) -> list[str]:
        return ["pip", "install", "-e", "."]

    def run_prefix(self) -> list[str]:
        return []


class FrontendPackageManager(ABC):
    """Installs frontend dependencies and runs package scripts."""

    name: str
    #: Lockfile that identifies a project already using this manager.
    lockfile: str

    @abstractmethod
    def install_command(self) -> list[str]:
        """Install everything declared in ``package.json``."""

    @abstractmethod
    def add_command(self, packages: Sequence[str], *, dev: bool = False) -> list[str]:
        """Add packages, optionally as dev dependencies."""

    @abstractmethod
    def remove_command(self, packages: Sequence[str]) -> list[str]:
        """Remove packages."""

    @abstractmethod
    def run_command(self, script: str) -> list[str]:
        """Run a script defined in ``package.json``."""

    def available(self) -> bool:
        return tool_exists(self.name)

    def install(self, *, cwd: Path) -> CommandResult:
        return run(self.install_command(), cwd=cwd)

    def add(self, packages: Sequence[str], *, cwd: Path, dev: bool = False) -> CommandResult:
        return run(self.add_command(packages, dev=dev), cwd=cwd)


class BunManager(FrontendPackageManager):
    name = "bun"
    lockfile = "bun.lockb"

    def install_command(self) -> list[str]:
        return ["bun", "install"]

    def add_command(self, packages: Sequence[str], *, dev: bool = False) -> list[str]:
        return ["bun", "add", *(["-d"] if dev else []), *packages]

    def remove_command(self, packages: Sequence[str]) -> list[str]:
        return ["bun", "remove", *packages]

    def run_command(self, script: str) -> list[str]:
        return ["bun", "run", script]


class NpmManager(FrontendPackageManager):
    name = "npm"
    lockfile = "package-lock.json"

    def install_command(self) -> list[str]:
        return ["npm", "install"]

    def add_command(self, packages: Sequence[str], *, dev: bool = False) -> list[str]:
        return ["npm", "install", *(["--save-dev"] if dev else []), *packages]

    def remove_command(self, packages: Sequence[str]) -> list[str]:
        return ["npm", "uninstall", *packages]

    def run_command(self, script: str) -> list[str]:
        return ["npm", "run", script]


class PnpmManager(FrontendPackageManager):
    name = "pnpm"
    lockfile = "pnpm-lock.yaml"

    def install_command(self) -> list[str]:
        return ["pnpm", "install"]

    def add_command(self, packages: Sequence[str], *, dev: bool = False) -> list[str]:
        return ["pnpm", "add", *(["-D"] if dev else []), *packages]

    def remove_command(self, packages: Sequence[str]) -> list[str]:
        return ["pnpm", "remove", *packages]

    def run_command(self, script: str) -> list[str]:
        return ["pnpm", "run", script]


class YarnManager(FrontendPackageManager):
    name = "yarn"
    lockfile = "yarn.lock"

    def install_command(self) -> list[str]:
        return ["yarn", "install"]

    def add_command(self, packages: Sequence[str], *, dev: bool = False) -> list[str]:
        return ["yarn", "add", *(["--dev"] if dev else []), *packages]

    def remove_command(self, packages: Sequence[str]) -> list[str]:
        return ["yarn", "remove", *packages]

    def run_command(self, script: str) -> list[str]:
        return ["yarn", "run", script]


_PYTHON_MANAGERS: dict[str, type[PythonPackageManager]] = {
    "uv": UvManager,
    "pip": PipManager,
}

_FRONTEND_MANAGERS: dict[str, type[FrontendPackageManager]] = {
    "bun": BunManager,
    "npm": NpmManager,
    "pnpm": PnpmManager,
    "yarn": YarnManager,
}


def python_manager(name: str) -> PythonPackageManager:
    """Build the Python package manager adapter called *name*.

    Raises:
        ToolNotFoundError: If the name is not a manager Sillo Start knows.
    """
    try:
        return _PYTHON_MANAGERS[name]()
    except KeyError as exc:
        known = ", ".join(sorted(_PYTHON_MANAGERS))
        raise ToolNotFoundError(f"Unknown Python package manager '{name}'. Known: {known}.") from exc


def frontend_manager(name: str) -> FrontendPackageManager:
    """Build the frontend package manager adapter called *name*.

    Raises:
        ToolNotFoundError: If the name is not a manager Sillo Start knows.
    """
    try:
        return _FRONTEND_MANAGERS[name]()
    except KeyError as exc:
        known = ", ".join(sorted(_FRONTEND_MANAGERS))
        raise ToolNotFoundError(f"Unknown frontend package manager '{name}'. Known: {known}.") from exc


def detect_python_manager() -> PythonPackageManager:
    """Pick the best available Python manager, preferring ``uv``."""
    uv = UvManager()
    return uv if uv.available() else PipManager()


def detect_frontend_manager(project_dir: Path | None = None) -> FrontendPackageManager:
    """Pick a frontend manager, honouring an existing lockfile.

    A project that already has ``pnpm-lock.yaml`` should keep using pnpm even
    if bun happens to be installed, so an existing lockfile wins over
    preference order.
    """
    if project_dir is not None:
        for manager_cls in _FRONTEND_MANAGERS.values():
            manager = manager_cls()
            if (project_dir / manager.lockfile).exists():
                return manager
    for name in ("bun", "pnpm", "npm", "yarn"):
        manager = _FRONTEND_MANAGERS[name]()
        if manager.available():
            return manager
    return NpmManager()
