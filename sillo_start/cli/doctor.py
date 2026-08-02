"""``sillo-start doctor`` — diagnose a project and its environment.

Checks are small functions returning :class:`Finding` objects, registered in a
list. That shape keeps each check independently testable, lets plugins add
their own, and means one failing check reports itself rather than aborting the
whole diagnosis — a doctor that dies on the first problem is not much of a
doctor.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import typer

from ..config.defaults import DatabaseDriver
from ..config.loader import find_manifest, load_manifest
from ..config.models import SilloManifest
from ..packages.registry import registry as package_registry
from ..plugins.loader import plugin_failures
from ..utils.console import console
from ..utils.environment import EnvFile
from ..utils.filesystem import is_writable
from ..utils.ports import can_connect, is_port_in_use
from ..utils.subprocess import run, tool_exists
from .app import app, handle_errors


class Level(str, Enum):
    """How serious a finding is."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class Finding:
    """One diagnostic result.

    Args:
        name: What was checked.
        level: Whether it passed.
        detail: What was found.
        fix: A command or action that would resolve it.
        auto_fix: Callable applying the fix, when ``--fix`` can do it safely.
    """

    name: str
    level: Level
    detail: str = ""
    fix: str = ""
    auto_fix: Callable[[Path, SilloManifest | None], bool] | None = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        return self.level is Level.PASS


@dataclass
class Diagnosis:
    """Context passed to every check."""

    root: Path | None
    manifest: SilloManifest | None

    @property
    def in_project(self) -> bool:
        return self.root is not None and self.manifest is not None


#: Signature every check implements.
Check = Callable[[Diagnosis], "list[Finding] | Finding | None"]

_CHECKS: list[Check] = []


def register_check(check: Check) -> Check:
    """Register a diagnostic. Usable as a decorator."""
    _CHECKS.append(check)
    return check


# -- environment checks -------------------------------------------------


@register_check
def check_python(diagnosis: Diagnosis) -> Finding:
    """The interpreter must satisfy what the project declares it needs.

    Checking against the project's own ``requires-python`` rather than Sillo
    Start's is what makes this worth running: the tool is often installed
    globally on a newer interpreter than the one the project will run under.
    """
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    required = diagnosis.manifest.project.python if diagnosis.in_project else ">=3.11"

    minimum = _parse_minimum_version(required)
    if minimum and sys.version_info[:2] < minimum:
        wanted = ".".join(str(part) for part in minimum)
        return Finding(
            "Python version",
            Level.FAIL,
            f"running {version}, but this project requires {required}",
            fix=f"Install Python {wanted} or newer and re-create the environment.",
        )
    return Finding("Python version", Level.PASS, f"{version} (project requires {required})")


def _parse_minimum_version(specifier: str) -> tuple[int, ...] | None:
    """Extract the minimum ``(major, minor)`` from a ``>=3.11``-style specifier.

    Returns ``None`` for anything this simple parser does not understand,
    which makes the check skip rather than guess.
    """
    import re

    match = re.search(r">=\s*(\d+)\.(\d+)", specifier)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)))


@register_check
def check_package_manager(_: Diagnosis) -> Finding:
    """uv is preferred; pip is an acceptable fallback."""
    if tool_exists("uv"):
        result = run(["uv", "--version"], check=False)
        return Finding("uv", Level.PASS, result.stdout.strip() or "installed")
    if tool_exists("pip"):
        return Finding(
            "uv",
            Level.WARN,
            "not installed — falling back to pip",
            fix="curl -LsSf https://astral.sh/uv/install.sh | sh",
        )
    return Finding(
        "Python package manager",
        Level.FAIL,
        "neither uv nor pip found",
        fix="Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh",
    )


@register_check
def check_sillo_installed(diagnosis: Diagnosis) -> Finding | None:
    """The framework must be importable for the project to run."""
    if not diagnosis.in_project:
        return None
    try:
        import sillo  # noqa: PLC0415 — probing availability is the point
    except ImportError:
        # Sillo Start is often installed globally (via uvx) while the framework
        # lives in the project's own environment, so this is expected rather
        # than broken — worth mentioning, not worth failing over.
        return Finding(
            "sillo-framework",
            Level.WARN,
            "not importable from this interpreter",
            fix="Run project commands inside the environment: `uv run sillo-start ...`",
        )
    return Finding("sillo-framework", Level.PASS, getattr(sillo, "__version__", "unknown"))


@register_check
def check_node(diagnosis: Diagnosis) -> Finding | None:
    """A frontend project needs a JavaScript runtime."""
    if not diagnosis.in_project or not diagnosis.manifest.inertia.enabled:
        return None
    for tool in ("bun", "node"):
        if tool_exists(tool):
            result = run([tool, "--version"], check=False)
            return Finding(f"{tool}", Level.PASS, result.stdout.strip())
    return Finding(
        "Node.js or Bun",
        Level.FAIL,
        "neither found, but this project has a frontend",
        fix="Install Node.js 20+ (https://nodejs.org) or Bun (https://bun.sh).",
    )


@register_check
def check_docker(diagnosis: Diagnosis) -> Finding | None:
    """Docker is only relevant when the project generated compose files."""
    if not diagnosis.in_project or not diagnosis.manifest.tooling.compose:
        return None
    if tool_exists("docker"):
        return Finding("Docker", Level.PASS, "available")
    return Finding(
        "Docker",
        Level.WARN,
        "not found, but this project ships a compose file",
        fix="Install Docker Desktop, or start the services yourself.",
    )


# -- project checks -----------------------------------------------------


@register_check
def check_manifest(diagnosis: Diagnosis) -> Finding:
    """The manifest must exist and validate."""
    if not diagnosis.in_project:
        return Finding(
            "Project manifest",
            Level.WARN,
            "not inside a Sillo project",
            fix="cd into a project, or create one with `sillo-start create <name>`.",
        )
    return Finding("Project manifest", Level.PASS, str(diagnosis.root / "sillo.toml"))


@register_check
def check_env_file(diagnosis: Diagnosis) -> list[Finding]:
    """``.env`` must exist and cover what ``.env.example`` declares."""
    if not diagnosis.in_project:
        return []

    env_path = diagnosis.root / ".env"
    example_path = diagnosis.root / ".env.example"

    if not env_path.exists():
        return [
            Finding(
                ".env",
                Level.FAIL,
                "missing",
                fix="cp .env.example .env",
                auto_fix=_copy_env_example,
            )
        ]

    findings = [Finding(".env", Level.PASS, "present")]
    if example_path.exists():
        env = EnvFile.load(env_path)
        example = EnvFile.load(example_path)
        missing = [key for key in example.keys() if not env.has(key)]
        if missing:
            findings.append(
                Finding(
                    ".env completeness",
                    Level.WARN,
                    f"missing {len(missing)} key(s): {', '.join(missing[:5])}"
                    + ("…" if len(missing) > 5 else ""),
                    fix="Copy the missing keys from .env.example.",
                    auto_fix=_merge_env_example,
                )
            )
    return findings


@register_check
def check_secrets(diagnosis: Diagnosis) -> list[Finding]:
    """Secrets must not still hold their placeholder values."""
    if not diagnosis.in_project:
        return []
    env_path = diagnosis.root / ".env"
    if not env_path.exists():
        return []

    env = EnvFile.load(env_path)
    weak = []
    for key in ("SECRET_KEY", "JWT_SECRET", "APP_SECRET_KEY"):
        value = env.get(key)
        if value is not None and (value in ("", "change-me") or len(value) < 32):
            weak.append(key)

    if weak:
        return [
            Finding(
                "Secrets",
                Level.WARN,
                f"{', '.join(weak)} look weak or unset",
                fix="Generate a strong value for each before deploying.",
            )
        ]
    return [Finding("Secrets", Level.PASS, "set")]


@register_check
def check_storage_writable(diagnosis: Diagnosis) -> list[Finding]:
    """The runtime directories must be writable."""
    if not diagnosis.in_project:
        return []
    findings = []
    # Only directories a project actually gets. Missing ones are skipped below,
    # so a project without file storage configured reports nothing here.
    for name in ("storage", "storage/app"):
        path = diagnosis.root / name
        if not path.exists():
            continue
        if not is_writable(path):
            findings.append(
                Finding(f"{name} writable", Level.FAIL, "not writable", fix=f"chmod u+w {path}")
            )
    if not findings and (diagnosis.root / "storage").exists():
        findings.append(Finding("Storage directories", Level.PASS, "writable"))
    return findings


@register_check
def check_database(diagnosis: Diagnosis) -> list[Finding]:
    """The database driver must be installed and the server reachable."""
    if not diagnosis.in_project or not diagnosis.manifest.database.enabled:
        return []

    manifest = diagnosis.manifest
    driver = DatabaseDriver(manifest.database.driver)
    findings: list[Finding] = []

    modules = {
        DatabaseDriver.POSTGRES: ("asyncpg", "asyncpg"),
        DatabaseDriver.MYSQL: ("aiomysql", "aiomysql"),
        DatabaseDriver.SQLITE: ("aiosqlite", "aiosqlite"),
    }
    if driver in modules:
        module, package = modules[driver]
        try:
            __import__(module)
            findings.append(Finding(f"{driver} driver", Level.PASS, f"{module} installed"))
        except ImportError:
            # Sillo Start is often installed globally while the project has its
            # own environment, so "not importable here" is not the same as
            # "missing". A declared-but-unimportable driver is a note about how
            # the command was run; an undeclared one is a real problem.
            if _declared_in_pyproject(diagnosis.root, package):
                findings.append(
                    Finding(
                        f"{driver} driver",
                        Level.PASS,
                        f"{package} is declared (not importable from this interpreter)",
                    )
                )
            else:
                findings.append(
                    Finding(
                        f"{driver} driver",
                        Level.FAIL,
                        f"{package} is neither declared in pyproject.toml nor installed",
                        fix=f"uv add {package}",
                    )
                )

    if driver in (DatabaseDriver.POSTGRES, DatabaseDriver.MYSQL):
        host, port = _database_endpoint(diagnosis.root, driver)
        if can_connect(host, port):
            findings.append(Finding("Database server", Level.PASS, f"reachable at {host}:{port}"))
        else:
            findings.append(
                Finding(
                    "Database server",
                    Level.FAIL,
                    f"nothing listening at {host}:{port}",
                    fix="Start the database, or `docker compose up -d db` if you generated one.",
                )
            )
    return findings


@register_check
def check_redis(diagnosis: Diagnosis) -> Finding | None:
    """Redis must be reachable when a feature depends on it."""
    if not diagnosis.in_project or not diagnosis.manifest.needs_redis:
        return None
    env = EnvFile.load(diagnosis.root / ".env")
    url = env.get("REDIS_URL") or "redis://localhost:6379/0"
    host, port = _parse_host_port(url, default_port=6379)
    if can_connect(host, port):
        return Finding("Redis", Level.PASS, f"reachable at {host}:{port}")
    return Finding(
        "Redis",
        Level.FAIL,
        f"nothing listening at {host}:{port}",
        fix="Start Redis, or switch the queue/cache driver in sillo.toml.",
    )


@register_check
def check_migrations(diagnosis: Diagnosis) -> Finding | None:
    """A project using Record should have its migrations initialised."""
    if not diagnosis.in_project or not diagnosis.manifest.uses_record:
        return None
    migrations = diagnosis.root / diagnosis.manifest.database.migrations_path
    if not migrations.exists():
        return Finding(
            "Migrations",
            Level.WARN,
            "no migrations directory",
            fix="sillo-start migrate init",
        )
    files = [p for p in migrations.rglob("*.py") if p.name != "__init__.py"]
    if not files:
        return Finding(
            "Migrations",
            Level.WARN,
            "initialised but empty",
            fix="sillo-start migrate make -m 'initial'",
        )
    return Finding("Migrations", Level.PASS, f"{len(files)} migration file(s)")


@register_check
def check_frontend(diagnosis: Diagnosis) -> list[Finding]:
    """Frontend dependencies must be installed for the dev server to start."""
    if not diagnosis.in_project or not diagnosis.manifest.inertia.enabled:
        return []

    frontend = diagnosis.root / diagnosis.manifest.inertia.frontend_path
    findings = []

    if not (frontend / "package.json").exists():
        return [
            Finding(
                "Frontend",
                Level.FAIL,
                f"no package.json in {diagnosis.manifest.inertia.frontend_path}/",
                fix="sillo-start add inertia --adapter " + str(diagnosis.manifest.inertia.adapter),
            )
        ]

    if not (frontend / "node_modules").exists():
        findings.append(
            Finding(
                "Frontend dependencies",
                Level.WARN,
                "node_modules is missing",
                fix=f"cd {diagnosis.manifest.inertia.frontend_path} && "
                f"{diagnosis.manifest.inertia.package_manager} install",
            )
        )
    else:
        findings.append(Finding("Frontend dependencies", Level.PASS, "installed"))

    if not any((frontend / f"vite.config.{ext}").exists() for ext in ("ts", "js", "mjs")):
        findings.append(
            Finding("Vite config", Level.WARN, "no vite.config found", fix="Re-run `sillo-start add inertia`.")
        )
    return findings


@register_check
def check_package_groups(diagnosis: Diagnosis) -> list[Finding]:
    """Enabled groups must exist and not conflict."""
    if not diagnosis.in_project:
        return []

    manifest = diagnosis.manifest
    findings: list[Finding] = []

    unknown = [name for name in manifest.packages.groups if not package_registry.has(name)]
    if unknown:
        findings.append(
            Finding(
                "Package groups",
                Level.WARN,
                f"unknown group(s): {', '.join(unknown)}",
                fix="Remove them from sillo.toml, or install the plugin that provides them.",
            )
        )

    enabled = set(manifest.packages.groups)
    for name in manifest.packages.groups:
        if not package_registry.has(name):
            continue
        group = package_registry.get(name)
        clashes = enabled & set(group.conflicts)
        if clashes:
            findings.append(
                Finding(
                    "Package groups",
                    Level.FAIL,
                    f"'{name}' conflicts with {', '.join(sorted(clashes))}",
                    fix=f"sillo-start package remove {sorted(clashes)[0]}",
                )
            )
        missing = [r for r in group.requires if r not in enabled]
        if missing:
            findings.append(
                Finding(
                    "Package groups",
                    Level.WARN,
                    f"'{name}' requires {', '.join(missing)}, which are not enabled",
                    fix=f"sillo-start package add {' '.join(missing)}",
                )
            )

    if not findings and manifest.packages.groups:
        findings.append(
            Finding("Package groups", Level.PASS, f"{len(manifest.packages.groups)} enabled, consistent")
        )
    return findings


@register_check
def check_ports(diagnosis: Diagnosis) -> list[Finding]:
    """Report ports already taken by something else."""
    if not diagnosis.in_project:
        return []
    findings = []
    ports = [("application", diagnosis.manifest.application.port)]
    if diagnosis.manifest.inertia.enabled:
        ports.append(("frontend", diagnosis.manifest.inertia.port))

    for label, port in ports:
        if is_port_in_use(port):
            findings.append(
                Finding(
                    f"Port {port}",
                    Level.WARN,
                    f"in use — the {label} may not start",
                    fix=f"Stop whatever holds port {port}, or change it in sillo.toml.",
                )
            )
    return findings


@register_check
def check_plugins(_: Diagnosis) -> Finding | None:
    """Report plugins that failed to load."""
    failures = plugin_failures()
    if not failures:
        return None
    return Finding(
        "Plugins",
        Level.WARN,
        "; ".join(f"{name} {reason}" for name, reason in failures.items()),
        fix="Update or uninstall the failing plugin.",
    )


# -- auto-fixes ---------------------------------------------------------


def _copy_env_example(root: Path, _: SilloManifest | None) -> bool:
    """Create ``.env`` from ``.env.example``."""
    example = root / ".env.example"
    target = root / ".env"
    if not example.exists() or target.exists():
        return False
    target.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    return True


def _merge_env_example(root: Path, _: SilloManifest | None) -> bool:
    """Add keys present in ``.env.example`` but missing from ``.env``.

    Existing values are never touched — only absent keys are appended.
    """
    example_path = root / ".env.example"
    env_path = root / ".env"
    if not example_path.exists() or not env_path.exists():
        return False

    example = EnvFile.load(example_path)
    env = EnvFile.load(env_path)
    added = False
    for key in example.keys():
        if not env.has(key):
            env.set(key, example.get(key) or "")
            added = True
    if added:
        env.save(env_path)
    return added


# -- command ------------------------------------------------------------


@app.command()
@handle_errors
def doctor(
    fix: bool = typer.Option(False, "--fix", help="Apply the fixes that are safe to automate."),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    strict: bool = typer.Option(False, "--strict", help="Treat warnings as failures."),
) -> None:
    """Check the project and the environment it needs.

    Reports what passed, what deserves attention, and what is broken — each
    with the command that resolves it. Exits non-zero when anything failed, so
    it can gate a CI pipeline.
    """
    manifest_path = find_manifest()
    root = manifest_path.parent if manifest_path else None
    manifest = None
    if manifest_path:
        try:
            manifest = load_manifest(manifest_path)
        except Exception as exc:  # noqa: BLE001 — an invalid manifest is itself a finding
            manifest = None
            console.debug(f"manifest failed to load: {exc}")

    diagnosis = Diagnosis(root=root, manifest=manifest)
    findings = _collect(diagnosis)

    if fix:
        findings = _apply_fixes(findings, diagnosis)

    if as_json:
        print(
            json.dumps(
                {
                    "root": str(root) if root else None,
                    "findings": [
                        {"name": f.name, "level": f.level.value, "detail": f.detail, "fix": f.fix}
                        for f in findings
                    ],
                },
                indent=2,
            )
        )
    else:
        _render(findings, root)

    failures = [f for f in findings if f.level is Level.FAIL]
    warnings = [f for f in findings if f.level is Level.WARN]
    if failures or (strict and warnings):
        raise typer.Exit(code=1)


def _collect(diagnosis: Diagnosis) -> list[Finding]:
    """Run every registered check, isolating failures.

    A check that raises becomes a finding of its own rather than aborting the
    run — the remaining diagnostics are usually what the user needs.
    """
    findings: list[Finding] = []
    for check in _CHECKS:
        try:
            result = check(diagnosis)
        except Exception as exc:  # noqa: BLE001
            findings.append(
                Finding(
                    getattr(check, "__name__", "check"),
                    Level.WARN,
                    f"the check itself failed: {exc}",
                )
            )
            continue
        if result is None:
            continue
        findings.extend(result if isinstance(result, list) else [result])
    return findings


def _apply_fixes(findings: list[Finding], diagnosis: Diagnosis) -> list[Finding]:
    """Apply the automatable fixes and re-run the checks."""
    fixable = [f for f in findings if f.auto_fix and not f.ok]
    if not fixable or diagnosis.root is None:
        return findings

    console.header("Applying fixes")
    for finding in fixable:
        try:
            if finding.auto_fix(diagnosis.root, diagnosis.manifest):
                console.success(f"{finding.name}: {finding.fix}")
            else:
                console.step(f"{finding.name}: nothing to do")
        except Exception as exc:  # noqa: BLE001
            console.failure(f"{finding.name}: fix failed — {exc}")

    return _collect(diagnosis)


def _render(findings: list[Finding], root: Path | None) -> None:
    """Print the findings grouped by severity."""
    console.header("Diagnosis", str(root) if root else "no project found")

    groups = [
        (Level.FAIL, "Errors", "red", "✗"),
        (Level.WARN, "Warnings", "yellow", "!"),
        (Level.PASS, "Passed", "green", "✓"),
    ]

    for level, title, colour, marker in groups:
        selected = [f for f in findings if f.level is level]
        if not selected:
            continue
        console.print(f"[bold]{title}[/bold]")
        for finding in selected:
            detail = f" — {finding.detail}" if finding.detail else ""
            console.print(f"  [{colour}]{marker}[/{colour}] {finding.name}{detail}")
            if finding.fix and level is not Level.PASS:
                console.hint(f"  {finding.fix}")
        console.blank()

    failures = sum(1 for f in findings if f.level is Level.FAIL)
    warnings = sum(1 for f in findings if f.level is Level.WARN)
    passed = sum(1 for f in findings if f.level is Level.PASS)

    summary = f"{passed} passed, {warnings} warning(s), {failures} error(s)"
    if failures:
        console.failure(summary)
    elif warnings:
        console.warning(summary)
        console.hint("Run `sillo-start doctor --fix` to apply the automatic fixes.")
    else:
        console.success(f"{summary} — everything looks good.")


def _declared_in_pyproject(root: Path | None, package: str) -> bool:
    """Report whether *package* appears in the project's declared dependencies.

    Compared on the bare distribution name so ``asyncpg>=0.29`` matches
    ``asyncpg``.
    """
    if root is None:
        return False
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        return False

    from ..utils import toml_io

    try:
        document = toml_io.load(pyproject)
    except Exception:  # noqa: BLE001 — an unreadable pyproject is its own finding
        return False

    declared: list[str] = list(toml_io.get_path(document, "project.dependencies", []) or [])
    optional = toml_io.get_path(document, "project.optional-dependencies", {}) or {}
    for group in optional.values():
        declared.extend(group)

    target = package.lower().replace("_", "-")
    for requirement in declared:
        name = str(requirement).lower()
        for separator in ("[", ";", "=", ">", "<", "!", "~", " "):
            index = name.find(separator)
            if index > 0:
                name = name[:index]
        if name.strip().replace("_", "-") == target:
            return True
    return False


def _database_endpoint(root: Path | None, driver: DatabaseDriver) -> tuple[str, int]:
    """Work out where the database should be listening."""
    default_port = 5432 if driver is DatabaseDriver.POSTGRES else 3306
    if root is None:
        return "localhost", default_port
    url = EnvFile.load(root / ".env").get("DATABASE_URL") or ""
    return _parse_host_port(url, default_port=default_port)


def _parse_host_port(url: str, *, default_port: int) -> tuple[str, int]:
    """Extract host and port from a connection URL, tolerating odd shapes."""
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        return parsed.hostname or "localhost", parsed.port or default_port
    except ValueError:
        return "localhost", default_port
