"""Built-in package group definitions.

Each group below was written against the real contents of ``sillo-framework``.
Where a capability is already first-party in core — the API layer, security
middleware, WebSockets — the group contributes configuration and structure but
no dependencies, and says so. Inventing a ``sillo-api`` package to make the
list look symmetrical would produce projects that cannot install.
"""

from __future__ import annotations

from ...utils.environment import EnvVar
from ..registry import PackageGroup, registry

API = PackageGroup(
    name="api",
    summary="REST API defaults: OpenAPI docs, validation, pagination.",
    description=(
        "Routing, Pydantic validation, OpenAPI generation and pagination are "
        "all built into sillo-framework, so this group adds no dependencies. "
        "It switches on the API section of the manifest and scaffolds the "
        "controller, request and resource layout that the generators expect."
    ),
    # Only routes/ is scaffolded. The generators create app/http/... on demand,
    # so shipping those empty would be three directories holding a docstring.
    directories=("routes",),
    provides=("http",),
)

RECORD = PackageGroup(
    name="record",
    summary="Record ORM, migrations and database drivers.",
    description=(
        "sillo.record wraps Tortoise ORM with models, migrations, factories, "
        "seeders and soft deletes. Migrations use Tortoise's own engine, so no "
        "extra migration package is needed; the database driver itself is "
        "added separately according to the configured backend."
    ),
    # Tortoise 1.0+ ships migrations in the box, so the record extra is all
    # that is required. aerich is deliberately not installed.
    sillo_extras=("record",),
    python_packages=("tortoise-orm>=1.0",),
    env_vars=(
        EnvVar("DATABASE_URL", "sqlite://storage/database.db", comment="Database connection URL."),
        EnvVar("DB_POOL_SIZE", "5"),
        EnvVar("DB_ECHO", "false", comment="Log every SQL statement."),
    ),
    # Seeders and factories are generator targets, created on demand.
    directories=("database/migrations", "database/models"),
    provides=("database", "orm"),
    post_install=(
        "After changing database/models/, run `sillo-start migrate make -m <what> --apply` to write and apply a migration.",
    ),
)

AUTH = PackageGroup(
    name="auth",
    summary="Authentication, sessions, password hashing and tokens.",
    description=(
        "sillo.auth provides session, JWT and API-key backends, and sillo.users "
        "provides the user model and manager. Installs the `jwt` extra for "
        "token support and bcrypt for password hashing — without a hashing "
        "backend the framework falls back to pbkdf2_sha256, which works but is "
        "slower to verify."
    ),
    sillo_extras=("jwt", "hashing-bcrypt"),
    # The generated auth schemas validate addresses with pydantic's EmailStr,
    # which raises at import time unless this is installed.
    python_packages=("email-validator>=2.0.0",),
    env_vars=(
        EnvVar("APP_SECRET_KEY", "", comment="Signs sessions and tokens. Keep secret.", secret=True),
        EnvVar("JWT_SECRET", "", comment="Signs JSON Web Tokens.", secret=True),
        EnvVar("JWT_ALGORITHM", "HS256"),
        EnvVar("JWT_EXPIRES_MINUTES", "60"),
    ),
    # app/services is a generator target (`generate service`), made on demand.
    directories=("routes",),
    requires=("record",),
    requires_database=True,
    provides=("authentication",),
    post_install=(
        "The users table comes from the initial migration in database/migrations/.",
    ),
)

ADMIN = PackageGroup(
    name="admin",
    summary="Sillo admin panel with model registration and login.",
    description=(
        "sillo.admin ships its own templates and static assets, and registers "
        "the configured user model plus an activity log automatically. Needs "
        "Jinja2 for template rendering, which comes from the framework's "
        "`templating` extra."
    ),
    sillo_extras=("templating",),
    env_vars=(
        EnvVar("ADMIN_ENABLED", "true"),
        EnvVar("ADMIN_PREFIX", "/admin"),
    ),
    # The panel is one module, app/admin.py — no package directory, which would
    # shadow it on import.
    directories=(),
    requires=("record", "auth"),
    requires_database=True,
    provides=("admin",),
    post_install=(
        "Create your first admin user with `sillo-start admin create-user`.",
    ),
)

INERTIA = PackageGroup(
    name="inertia",
    summary="Inertia.js adapter with Vite and a React, Vue or Svelte frontend.",
    description=(
        "sillo-inertia is a separate distribution that renders Inertia pages "
        "from Sillo handlers and injects Vite tags. The frontend packages "
        "depend on the adapter chosen during setup and are added by the "
        "Inertia feature installer rather than being fixed here."
    ),
    python_packages=("sillo-inertia>=0.1.0",),
    sillo_extras=("templating",),
    env_vars=(
        EnvVar("VITE_DEV_SERVER", "http://localhost:5173"),
        EnvVar("INERTIA_SSR", "false"),
    ),
    directories=("templates",),
    conflicts=(),
    provides=("frontend",),
    post_install=(
        "Install frontend dependencies with `sillo-start build --frontend`, then start everything with `sillo-start dev`.",
    ),
)

WORK = PackageGroup(
    name="work",
    summary="Queues, workers, scheduled tasks and failed-job handling.",
    description=(
        "sillo.work provides the queue subsystem, worker pool and cron "
        "scheduler in core. Redis is only required when the Redis queue driver "
        "is selected; the memory and database drivers need nothing extra."
    ),
    sillo_extras=("cache",),
    # app/tasks is created by the scheduler flag rather than here, so a
    # queue-only project does not get an empty tasks package.
    directories=("app/jobs",),
    provides=("queue", "scheduler"),
    post_install=(
        "Run the worker alongside the app with `sillo-start dev`, or on its own with `python scripts/worker.py`.",
    ),
)

REALTIME = PackageGroup(
    name="realtime",
    summary="WebSockets, broadcasting and Redis channels.",
    description=(
        "WebSocket routing is built into sillo-framework. This group adds the "
        "`events` extra so broadcasts can fan out through Redis across "
        "multiple processes, and scaffolds a channels route module."
    ),
    sillo_extras=("events",),
    env_vars=(
        EnvVar("REDIS_URL", "redis://localhost:6379/0", comment="Broadcasting backend."),
    ),
    directories=("app/events", "app/listeners"),
    provides=("websockets", "broadcasting"),
)

MONITORING = PackageGroup(
    name="monitoring",
    summary="Structured logging, health checks and error reporting.",
    description=(
        "sillo.logging provides the logging primitives. This group configures "
        "JSON-structured output, adds health-check endpoints, and installs "
        "structlog for ergonomic structured logs. Tracing and metrics exporters "
        "are intentionally left out — pick an OpenTelemetry distribution that "
        "matches your backend rather than inheriting one."
    ),
    python_packages=("structlog>=24.1.0",),
    env_vars=(
        EnvVar("LOG_LEVEL", "info"),
        EnvVar("LOG_FORMAT", "json", comment="'json' in production, 'console' locally."),
    ),
    provides=("observability",),
)

SECURITY = PackageGroup(
    name="security",
    summary="CSRF, CORS, rate limiting and secure headers.",
    description=(
        "sillo.security ships CORS, CSRF, rate limiting and shield middleware "
        "in core, so this group adds no dependencies. It enables the "
        "corresponding manifest flags and wires the middleware in bootstrap."
    ),
    env_vars=(
        EnvVar("CORS_ALLOW_ORIGINS", "http://localhost:5173"),
        EnvVar("RATE_LIMIT_PER_MINUTE", "120"),
    ),
    provides=("security",),
)

TESTING = PackageGroup(
    name="testing",
    summary="pytest, async testing, factories and coverage.",
    description=(
        "sillo.testclient provides the test client in core. This group adds "
        "pytest with async support and coverage, and scaffolds the test layout "
        "with fixtures wired to the application."
    ),
    dev_packages=(
        "pytest>=8.3.5",
        "pytest-asyncio>=0.25.3",
        "httpx>=0.28.1",
        "coverage[toml]>=7.4.0",
    ),
    # `generate ... --tests` writes into tests/unit/ and creates it then.
    directories=("tests",),
    provides=("testing",),
)

BUILTIN_GROUPS = (
    API,
    RECORD,
    AUTH,
    ADMIN,
    INERTIA,
    WORK,
    REALTIME,
    MONITORING,
    SECURITY,
    TESTING,
)


def register_builtins(target=registry) -> None:
    """Register every built-in group, replacing existing entries.

    Replacement is enabled so that re-importing during tests, or reloading
    after a plugin error, cannot leave the registry half-populated.
    """
    for group in BUILTIN_GROUPS:
        target.register(group, replace=True)


register_builtins()

__all__ = [
    "API",
    "RECORD",
    "AUTH",
    "ADMIN",
    "INERTIA",
    "WORK",
    "REALTIME",
    "MONITORING",
    "SECURITY",
    "TESTING",
    "BUILTIN_GROUPS",
    "register_builtins",
]
