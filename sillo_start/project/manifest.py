"""Building a manifest from a blueprint and user choices.

Precedence is the point of this module: blueprint defaults are applied first,
then explicit choices override them, then coherence rules run last. That order
is what lets ``--blueprint fullstack --database postgres`` mean "the fullstack
shape, but on Postgres" rather than silently keeping the blueprint's SQLite.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..blueprints.base import Blueprint
from ..blueprints.builtins import apply_defaults
from ..config.defaults import (
    ORM,
    SILLO_VERSION_SPEC,
    AppType,
    AuthStrategy,
    CacheDriver,
    DatabaseDriver,
    FrontendPackageManager,
    InertiaAdapter,
    MailDriver,
    PythonPackageManager,
    QueueDriver,
    SessionDriver,
    StorageDriver,
)
from ..config.models import ProjectSection, SilloManifest
from ..utils import naming


@dataclass
class ProjectOptions:
    """Explicit choices, from CLI flags or the wizard.

    Every field defaults to ``None`` meaning "not specified", so the builder
    can tell an explicit ``--auth none`` apart from an omitted flag.
    """

    name: str
    blueprint: str = "api"
    description: str = ""
    version: str = "0.1.0"

    database: DatabaseDriver | None = None
    orm: ORM | None = None
    auth: AuthStrategy | None = None
    admin: bool | None = None
    inertia: InertiaAdapter | None = None
    queue: QueueDriver | None = None
    scheduler: bool | None = None
    cache: CacheDriver | None = None
    session: SessionDriver | None = None
    mail: MailDriver | None = None
    storage: StorageDriver | None = None

    package_groups: list[str] = field(default_factory=list)
    python_manager: PythonPackageManager = PythonPackageManager.UV
    frontend_manager: FrontendPackageManager | None = None

    #: Individual feature toggles, applied as dotted manifest paths. The wizard
    #: uses this for the long tail of yes/no questions rather than growing a
    #: field per switch.
    toggles: dict[str, bool] = field(default_factory=dict)

    sillo_version: str = SILLO_VERSION_SPEC


def build_manifest(options: ProjectOptions, blueprint: Blueprint) -> SilloManifest:
    """Assemble the manifest for a new project.

    Args:
        options: The explicit choices.
        blueprint: The chosen archetype.

    Returns:
        A validated manifest with coherent sections.
    """
    manifest = SilloManifest(
        project=ProjectSection(
            name=options.name,
            version=options.version,
            description=options.description,
            sillo_version=options.sillo_version,
        )
    )

    apply_defaults(blueprint, manifest)
    _apply_choices(manifest, options)
    _apply_toggles(manifest, options.toggles)
    _reconcile(manifest)
    _sync_groups(manifest)
    _sync_development_commands(manifest)
    return manifest


def _apply_choices(manifest: SilloManifest, options: ProjectOptions) -> None:
    """Layer the explicit choices over the blueprint defaults."""
    if options.database is not None:
        manifest.database.enabled = options.database != DatabaseDriver.NONE
        manifest.database.driver = options.database
        if manifest.database.enabled:
            manifest.database.orm = options.orm or ORM.RECORD
    if options.orm is not None:
        manifest.database.orm = options.orm

    if options.auth is not None:
        manifest.auth.enabled = options.auth != AuthStrategy.NONE
        manifest.auth.strategy = options.auth

    if options.admin is not None:
        manifest.admin.enabled = options.admin

    if options.inertia is not None:
        manifest.inertia.enabled = True
        manifest.inertia.adapter = options.inertia
        manifest.application.type = AppType.INERTIA

    if options.queue is not None:
        manifest.queue.enabled = options.queue != QueueDriver.NONE
        manifest.queue.driver = options.queue

    if options.scheduler is not None:
        manifest.scheduler.enabled = options.scheduler

    if options.cache is not None:
        manifest.cache.enabled = options.cache != CacheDriver.NONE
        manifest.cache.driver = options.cache

    if options.session is not None:
        manifest.session.enabled = True
        manifest.session.driver = options.session

    if options.mail is not None:
        manifest.mail.enabled = options.mail != MailDriver.NONE
        manifest.mail.driver = options.mail

    if options.storage is not None:
        manifest.storage.enabled = options.storage != StorageDriver.NONE
        manifest.storage.driver = options.storage

    manifest.tooling.package_manager = options.python_manager
    if options.frontend_manager is not None:
        manifest.inertia.package_manager = options.frontend_manager

    for group in options.package_groups:
        manifest.add_group(group)


def _apply_toggles(manifest: SilloManifest, toggles: dict[str, bool]) -> None:
    """Apply dotted-path boolean switches, ignoring unknown paths.

    Unknown paths are skipped rather than raising: a toggle may belong to a
    plugin section that is not installed, and refusing to build the project
    over it would be worse than ignoring it.
    """
    for dotted, value in toggles.items():
        section_name, _, field_name = dotted.rpartition(".")
        if not section_name:
            continue
        section = manifest
        for part in section_name.split("."):
            section = getattr(section, part, None)
            if section is None:
                break
        if section is not None and hasattr(section, field_name):
            setattr(section, field_name, value)


def _reconcile(manifest: SilloManifest) -> None:
    """Resolve implications between features so the manifest is coherent.

    These are the rules a developer would otherwise hit as a runtime error:
    session auth without session middleware, admin without a database, Inertia
    without templates.
    """
    if manifest.auth.enabled:
        # Every auth strategy needs somewhere to look users up.
        if not manifest.database.enabled:
            manifest.database.enabled = True
            manifest.database.driver = DatabaseDriver.SQLITE
        if manifest.database.orm == ORM.NONE:
            manifest.database.orm = ORM.RECORD
        if manifest.auth.strategy == AuthStrategy.SESSION and not manifest.session.enabled:
            manifest.session.enabled = True
            manifest.session.driver = SessionDriver.COOKIE

    if manifest.admin.enabled:
        # The admin panel browses models and authenticates against a user table.
        if not manifest.database.enabled:
            manifest.database.enabled = True
            manifest.database.driver = DatabaseDriver.SQLITE
            manifest.database.orm = ORM.RECORD
        if not manifest.auth.enabled:
            manifest.auth.enabled = True
            manifest.auth.strategy = AuthStrategy.SESSION
            manifest.session.enabled = True
        if not manifest.admin.title:
            manifest.admin.title = f"{naming.to_title(manifest.project.name)} Admin"

    if manifest.inertia.enabled:
        # Inertia renders a root HTML view, so the templating extra is required.
        manifest.application.type = AppType.INERTIA

    if manifest.application.type == AppType.WORKER and not manifest.queue.enabled:
        manifest.queue.enabled = True
        manifest.queue.driver = QueueDriver.MEMORY

    if manifest.database.enabled and manifest.database.orm == ORM.NONE:
        manifest.database.orm = ORM.RECORD


def _sync_groups(manifest: SilloManifest) -> None:
    """Enable the package groups implied by the manifest's features.

    A developer who passes ``--admin`` should not also have to remember
    ``--package-group admin``.
    """
    implied = {
        "record": manifest.uses_record,
        "auth": manifest.auth.enabled,
        "admin": manifest.admin.enabled,
        "inertia": manifest.inertia.enabled,
        "work": manifest.queue.enabled or manifest.scheduler.enabled,
        "api": manifest.api.enabled,
        "testing": manifest.tooling.pytest,
        "security": manifest.api.csrf or manifest.api.rate_limiting,
        "monitoring": manifest.api.structured_logging,
    }
    for group, enabled in implied.items():
        if enabled:
            manifest.add_group(group)


def _sync_development_commands(manifest: SilloManifest) -> None:
    """Fill in the commands ``sillo-start dev`` runs.

    The framework ships no CLI of its own, so these are real commands: uvicorn
    for the backend, the frontend package manager's dev script, and the worker
    and scheduler scripts Sillo Start generates.
    """
    development = manifest.development
    if not development.backend_command:
        development.backend_command = f"uvicorn {manifest.application.entrypoint} --reload"

    if manifest.inertia.enabled and not development.frontend_command:
        manager = FrontendPackageManager(manifest.inertia.package_manager)
        development.frontend_command = f"{manager.value} run dev"
    elif not manifest.inertia.enabled:
        development.frontend_command = ""

    if manifest.queue.enabled and not development.worker_command:
        development.worker_command = "python scripts/worker.py"
    elif not manifest.queue.enabled:
        development.worker_command = ""

    if manifest.scheduler.enabled and not development.scheduler_command:
        development.scheduler_command = "python scripts/scheduler.py"
    elif not manifest.scheduler.enabled:
        development.scheduler_command = ""
