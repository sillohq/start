"""The built-in blueprints.

Each one is a stance on what a project of that shape should start with. They
stay small on purpose: a blueprint that enables everything is not a starting
point, it is a project the developer has to dismantle.
"""

from __future__ import annotations

from ..config.defaults import (
    ORM,
    AppType,
    AuthStrategy,
    CacheDriver,
    DatabaseDriver,
    InertiaAdapter,
    QueueDriver,
)
from ..config.models import SilloManifest
from .base import Blueprint, FileSpec

MINIMAL = Blueprint(
    name="minimal",
    summary="A bare application with one route and a test.",
    description=(
        "Routing and configuration, nothing else. The right starting point "
        "when you want to add pieces deliberately rather than remove them."
    ),
    app_type=AppType.MINIMAL,
    groups=(),
)

API = Blueprint(
    name="api",
    summary="A REST API with OpenAPI docs, health checks and tests.",
    description=(
        "The API layout: routers under routes/, controllers and resources "
        "under app/http/, OpenAPI served at /docs, and a health endpoint the "
        "orchestrator and your load balancer can both use."
    ),
    app_type=AppType.API,
    groups=("api", "testing"),
    extra_directories=(),
)

FULLSTACK = Blueprint(
    name="fullstack",
    summary="Server-rendered pages with a database, auth and admin.",
    description=(
        "A classic server-rendered application: Record models, session "
        "authentication, and the admin panel mounted at /admin."
    ),
    app_type=AppType.WEB,
    groups=("api", "record", "auth", "admin", "testing"),
    extra_directories=("templates", "static"),
)


def _inertia_blueprint(adapter: InertiaAdapter) -> Blueprint:
    """Build the Inertia blueprint for a frontend adapter.

    The three adapters differ only in which frontend packages and page files
    they produce, so they share one definition rather than three near-copies.
    """
    return Blueprint(
        name=f"inertia-{adapter.value}",
        summary=f"Inertia.js full-stack application with {adapter.value.title()} and Vite.",
        description=(
            f"A single-page {adapter.value.title()} frontend served by Sillo through "
            "Inertia.js, with Vite for development and builds. `sillo-start dev` "
            "runs the API and the Vite server together."
        ),
        app_type=AppType.INERTIA,
        groups=("api", "record", "auth", "inertia", "testing"),
        extra_directories=(),
    )


INERTIA_REACT = _inertia_blueprint(InertiaAdapter.REACT)
INERTIA_VUE = _inertia_blueprint(InertiaAdapter.VUE)
INERTIA_SVELTE = _inertia_blueprint(InertiaAdapter.SVELTE)

WORKER = Blueprint(
    name="worker",
    summary="A background worker application with queues and a scheduler.",
    description=(
        "For services whose job is processing rather than serving. Ships the "
        "queue worker and scheduler entrypoints; the HTTP surface is limited "
        "to a health endpoint so the process can be probed."
    ),
    app_type=AppType.WORKER,
    groups=("record", "work", "testing"),
    extra_directories=("app/jobs", "app/tasks"),
)

MODULAR = Blueprint(
    name="modular-monolith",
    summary="A monolith split into self-contained feature modules.",
    description=(
        "Each module under app/modules/ owns its routes, models and services, "
        "and is mounted independently — so a module can later be extracted "
        "into its own service without untangling it first."
    ),
    app_type=AppType.MODULAR,
    groups=("api", "record", "auth", "testing"),
    extra_directories=("app/modules", "app/shared"),
)

ENTERPRISE = Blueprint(
    name="enterprise",
    summary="Everything on: database, auth, admin, queues, monitoring, Docker.",
    description=(
        "The full stack for a production service — Record with migrations, "
        "session auth, the admin panel, Redis-backed queues and scheduling, "
        "structured logging, security middleware and container tooling."
    ),
    app_type=AppType.MODULAR,
    groups=("api", "record", "auth", "admin", "work", "monitoring", "security", "testing"),
    extra_directories=(
        "app/repositories",
        "app/policies",
        "app/jobs",
        "app/tasks",
        "docker",
    ),
)


#: Manifest defaults each blueprint applies beyond its package groups. Kept as
#: data rather than as ``configure`` overrides so the effect of choosing a
#: blueprint can be listed by ``sillo-start create --list-blueprints``.
BLUEPRINT_DEFAULTS: dict[str, dict[str, object]] = {
    "minimal": {
        "api.enabled": False,
        "api.health_checks": False,
        "tooling.pytest": True,
    },
    "api": {
        "api.enabled": True,
        "api.openapi": True,
        "api.cors": True,
        "api.health_checks": True,
    },
    "fullstack": {
        "database.enabled": True,
        "database.driver": DatabaseDriver.SQLITE,
        "database.orm": ORM.RECORD,
        "auth.enabled": True,
        "auth.strategy": AuthStrategy.SESSION,
        "session.enabled": True,
        "admin.enabled": True,
        "api.csrf": True,
    },
    "inertia-react": {
        "database.enabled": True,
        "database.driver": DatabaseDriver.SQLITE,
        "database.orm": ORM.RECORD,
        "auth.enabled": True,
        "auth.strategy": AuthStrategy.SESSION,
        "session.enabled": True,
        "inertia.enabled": True,
        "inertia.adapter": InertiaAdapter.REACT,
        "api.cors": True,
    },
    "inertia-vue": {
        "database.enabled": True,
        "database.driver": DatabaseDriver.SQLITE,
        "database.orm": ORM.RECORD,
        "auth.enabled": True,
        "auth.strategy": AuthStrategy.SESSION,
        "session.enabled": True,
        "inertia.enabled": True,
        "inertia.adapter": InertiaAdapter.VUE,
        "api.cors": True,
    },
    "inertia-svelte": {
        "database.enabled": True,
        "database.driver": DatabaseDriver.SQLITE,
        "database.orm": ORM.RECORD,
        "auth.enabled": True,
        "auth.strategy": AuthStrategy.SESSION,
        "session.enabled": True,
        "inertia.enabled": True,
        "inertia.adapter": InertiaAdapter.SVELTE,
        "api.cors": True,
    },
    "worker": {
        "database.enabled": True,
        "database.driver": DatabaseDriver.SQLITE,
        "database.orm": ORM.RECORD,
        "queue.enabled": True,
        "queue.driver": QueueDriver.REDIS,
        "scheduler.enabled": True,
        "api.openapi": False,
    },
    "modular-monolith": {
        "database.enabled": True,
        "database.driver": DatabaseDriver.POSTGRES,
        "database.orm": ORM.RECORD,
        "auth.enabled": True,
        "auth.strategy": AuthStrategy.SESSION,
        "session.enabled": True,
    },
    "enterprise": {
        "database.enabled": True,
        "database.driver": DatabaseDriver.POSTGRES,
        "database.orm": ORM.RECORD,
        "auth.enabled": True,
        "auth.strategy": AuthStrategy.SESSION,
        "authorization.enabled": True,
        "authorization.roles": True,
        "authorization.permissions": True,
        "authorization.policies": True,
        "session.enabled": True,
        "admin.enabled": True,
        "queue.enabled": True,
        "queue.driver": QueueDriver.REDIS,
        "scheduler.enabled": True,
        "cache.enabled": True,
        "cache.driver": CacheDriver.REDIS,
        "api.cors": True,
        "api.csrf": True,
        "api.rate_limiting": True,
        "api.request_id": True,
        "api.structured_logging": True,
        "tooling.docker": True,
        "tooling.compose": True,
        "tooling.mypy": True,
        "tooling.coverage": True,
        "tooling.github_actions": True,
    },
}


def apply_defaults(blueprint: Blueprint, manifest: SilloManifest) -> None:
    """Apply a blueprint's manifest defaults.

    Values are written with dotted paths so the defaults table above stays
    readable next to the blueprint it belongs to.
    """
    blueprint.configure(manifest)
    for dotted, value in BLUEPRINT_DEFAULTS.get(blueprint.name, {}).items():
        section_name, _, field_name = dotted.rpartition(".")
        section = manifest
        for part in section_name.split("."):
            section = getattr(section, part)
        setattr(section, field_name, value)


BUILTIN_BLUEPRINTS = (
    MINIMAL,
    API,
    FULLSTACK,
    INERTIA_REACT,
    INERTIA_VUE,
    INERTIA_SVELTE,
    WORKER,
    MODULAR,
    ENTERPRISE,
)

__all__ = [
    "MINIMAL",
    "API",
    "FULLSTACK",
    "INERTIA_REACT",
    "INERTIA_VUE",
    "INERTIA_SVELTE",
    "WORKER",
    "MODULAR",
    "ENTERPRISE",
    "BUILTIN_BLUEPRINTS",
    "BLUEPRINT_DEFAULTS",
    "apply_defaults",
    "Blueprint",
    "FileSpec",
]
