"""Migration orchestration.

Sillo Start presents one migration interface regardless of what runs
underneath. That is Tortoise's own migration engine, reached through
``sillo.record.MigrationHelper``.

Commands run *inside the project's environment*, not this one — the project's
models, config and database driver live there — so the backend drives a short
Python program rather than importing the helper directly.

Tortoise 1.0 ships native migrations and aerich itself recommends them over
aerich from that version on. Projects generated before this change carry a
``[tool.aerich]`` block and an ``aerich.models`` entry in ``MODEL_MODULES``;
both are inert once ``apps.models.migrations`` is set, and can be deleted.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ..config.models import SilloManifest
from ..exceptions import CommandError, UsageError
from ..utils.environment import EnvFile
from ..utils.pkgmanagers import PythonPackageManager, detect_python_manager
from ..utils.subprocess import CommandResult, run, tool_exists


@dataclass
class MigrationStatus:
    """A summary of where the project's migrations stand."""

    initialised: bool
    applied: list[str]
    files: list[str]

    @property
    def pending(self) -> list[str]:
        """Migration files with no corresponding applied entry.

        Compared on the file stem, since aerich reports versions by name.
        """
        applied = {Path(name).stem for name in self.applied}
        return [name for name in self.files if Path(name).stem not in applied]


class MigrationBackend(ABC):
    """Runs migrations for a project."""

    name: str

    @abstractmethod
    def initialise(self, root: Path, manifest: SilloManifest) -> CommandResult: ...

    @abstractmethod
    def make(self, root: Path, manifest: SilloManifest, message: str) -> CommandResult: ...

    @abstractmethod
    def upgrade(
        self, root: Path, manifest: SilloManifest, *, fake: bool = False
    ) -> CommandResult: ...

    @abstractmethod
    def downgrade(self, root: Path, manifest: SilloManifest, *, steps: int) -> CommandResult: ...

    @abstractmethod
    def status(self, root: Path, manifest: SilloManifest) -> MigrationStatus: ...


#: Driver program executed inside the project's interpreter.
#:
#: It prefers ``sillo.record.MigrationHelper``; when the installed framework
#: still ships the pre-native helper (which could only migrate aerich's own
#: bookkeeping models) it falls back to Tortoise's CLI entry point directly.
#: Both drive the same engine, so behaviour does not change with the fallback.
_DRIVER = '''
import asyncio, inspect, sys
sys.path.insert(0, ".")
CONFIG, APP = "database.config.TORTOISE_ORM", "models"

def _helper():
    try:
        from sillo.record import MigrationHelper
    except Exception:
        return None
    if "config" not in inspect.signature(MigrationHelper.__init__).parameters:
        return None
    return MigrationHelper(CONFIG, app=APP)

async def _native(*argv):
    from tortoise.cli.cli import run_cli_async
    code = await run_cli_async(["-c", CONFIG, *argv])
    from tortoise import Tortoise
    await Tortoise.close_connections()
    if code:
        raise SystemExit(code)

async def main():
    command, args = sys.argv[1], sys.argv[2:]
    helper = _helper()
    if command == "init":
        await (helper.init() if helper else _native("init"))
    elif command == "make":
        name = args[0] if args else None
        if helper:
            await helper.make(name)
        else:
            await _native("makemigrations", *(["--name", name] if name else []))
    elif command == "upgrade":
        fake = "--fake" in args
        if helper:
            await helper.upgrade(fake=fake)
        else:
            await _native("migrate", *(["--fake"] if fake else []))
    elif command == "downgrade":
        target = args[0]
        await (helper.downgrade(target) if helper else _native("downgrade", APP, target))
    elif command == "applied":
        await _native("history")
    elif command == "bootstrap":
        if helper:
            await helper.init()
            await helper.make("initial")
            await helper.upgrade()
        else:
            await _native("init")
            await _native("makemigrations", "--name", "initial")
            await _native("migrate")
    else:
        raise SystemExit(f"unknown command {command}")

asyncio.run(main())
'''


class TortoiseBackend(MigrationBackend):
    """Drives Tortoise's native migration engine via ``sillo.record``.

    Commands run with the project root on ``PYTHONPATH`` and the project's
    ``.env`` loaded, because ``database.config`` is imported to find
    ``TORTOISE_ORM`` and that module reads ``DATABASE_URL``.
    """

    name = "tortoise"

    def __init__(self, manager: PythonPackageManager | None = None) -> None:
        self.manager = manager or detect_python_manager()

    def _argv(self, *args: str) -> list[str]:
        """Build the invocation, preferring the project environment.

        ``uv run`` guarantees the project's dependencies are importable even
        when Sillo Start itself was installed globally with uvx.
        """
        program = ["python", "-c", _DRIVER, *args]
        if self.manager.name == "uv" and tool_exists("uv"):
            return ["uv", "run", *program]
        return program

    def _environment(self, root: Path) -> dict[str, str]:
        """Build the environment for a migration run.

        The project root is prepended to ``PYTHONPATH`` so ``database.config``
        resolves, and ``.env`` is loaded so ``DATABASE_URL`` is the same one
        the application uses.
        """
        env: dict[str, str] = {}
        env_file = EnvFile.load(root / ".env")
        for key in env_file.keys():
            value = env_file.get(key)
            if value is not None:
                env[key] = value

        existing = os.environ.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{root}{os.pathsep}{existing}" if existing else str(root)
        return env

    def _run(self, root: Path, args: list[str], *, check: bool = True) -> CommandResult:
        """Run one migration command inside the project."""
        return run(
            self._argv(*args), cwd=root, env=self._environment(root), check=check, timeout=300
        )

    def initialise(self, root: Path, manifest: SilloManifest) -> CommandResult:
        """Create the migration package and the first migration.

        ``init`` only creates the package; without a generated migration there
        is nothing for ``upgrade`` to apply, which is why the initial migration
        is written here rather than left to the first ``migrate make``.
        """
        self._run(root, ["init"], check=False)
        return self._run(root, ["make", "initial"], check=False)

    def bootstrap_argv(self) -> list[str]:
        """Command that records the schema as migration 0001 and applies it.

        Run once at project creation. Without it the first tables exist with no
        migration history behind them, so the first `migrate make` reports every
        table as new and `migrate run` then fails with "table already exists".
        """
        return self._argv("bootstrap")

    def make(self, root: Path, manifest: SilloManifest, message: str) -> CommandResult:
        return self._run(root, ["make", message])

    def upgrade(
        self, root: Path, manifest: SilloManifest, *, fake: bool = False
    ) -> CommandResult:
        args = ["upgrade", "--fake"] if fake else ["upgrade"]
        return self._run(root, args, check=False)

    def downgrade(self, root: Path, manifest: SilloManifest, *, steps: int) -> CommandResult:
        """Roll back *steps* migrations.

        Tortoise rolls back *to a named migration* rather than by a count, so
        the target is resolved from the files on disk. Rolling back everything
        targets ``zero``.
        """
        files = self._migration_files(root, manifest)
        index = len(files) - steps
        target = Path(files[index - 1]).stem if index > 0 else "zero"
        return self._run(root, ["downgrade", target], check=False)

    @staticmethod
    def _migration_files(root: Path, manifest: SilloManifest) -> list[str]:
        """Migration files on disk, in application order."""
        migrations_dir = root / manifest.database.migrations_path
        if not migrations_dir.exists():
            return []
        return sorted(
            path.name
            for path in migrations_dir.rglob("*.py")
            if path.name != "__init__.py"
        )

    def status(self, root: Path, manifest: SilloManifest) -> MigrationStatus:
        """Report which migrations exist and which have been applied."""
        files = self._migration_files(root, manifest)
        initialised = bool(files)

        applied: list[str] = []
        result = self._run(root, ["applied"], check=False)
        if result.ok:
            # Applied migrations are reported as "  - <app> <name>"; on-disk
            # heads use "<app>.<name>", so match on the trailing name only.
            recorded = {
                line.strip().lstrip("- ").split()[-1]
                for line in result.stdout.splitlines()
                if line.strip().startswith("-")
            }
            applied = [name for name in files if Path(name).stem in recorded]
        else:
            initialised = False

        return MigrationStatus(initialised=initialised, applied=applied, files=files)


def get_backend(manifest: SilloManifest) -> MigrationBackend:
    """Return the migration backend for a project.

    Raises:
        UsageError: If the project has no ORM configured.
    """
    if not manifest.uses_record:
        raise UsageError(
            "This project has no database configured.",
            hint="Add one with `sillo-start package add record`.",
        )
    return TortoiseBackend()


def ensure_driver_installed(manifest: SilloManifest) -> None:
    """Check the database driver is importable before running migrations.

    Raises:
        CommandError: If the driver is missing, naming the package to install.
    """
    from ..config.defaults import DatabaseDriver

    modules = {
        DatabaseDriver.POSTGRES: ("asyncpg", "asyncpg"),
        DatabaseDriver.MYSQL: ("aiomysql", "aiomysql"),
        DatabaseDriver.SQLITE: ("aiosqlite", "aiosqlite"),
    }
    entry = modules.get(DatabaseDriver(manifest.database.driver))
    if entry is None:
        return
    module, package = entry
    try:
        __import__(module)
    except ImportError as exc:
        raise CommandError(
            f"The {manifest.database.driver} driver ({module}) is not installed.",
            hint=f"uv add {package}",
        ) from exc
