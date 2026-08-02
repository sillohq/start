"""Enumerated choices and baseline defaults for the project manifest.

Every option the wizard offers and every value the manifest accepts is declared
here as a string enum. Keeping them in one module means the CLI flags, the
wizard prompts, the manifest schema and the package registry all validate
against the same list, so a new database backend cannot be half-added.
"""

from __future__ import annotations

from enum import Enum

#: The Sillo framework release generated projects are pinned against. Sillo is
#: pre-1.0, so generated projects get a floor rather than a caret range.
#:
#: 0.0.1a3 is the floor because generated apps pass
#: ``DatabaseConfig(generate_schemas=False)``; on 0.0.1a2 that is a TypeError
#: at startup, and on anything older every process races to run DDL.
SILLO_VERSION_SPEC = ">=0.0.1a3"
SILLO_INERTIA_VERSION_SPEC = ">=0.0.1a2"

#: Distribution names. The import name (``sillo``) differs from the PyPI name.
SILLO_DISTRIBUTION = "sillo-framework"
SILLO_INERTIA_DISTRIBUTION = "sillo-inertia"

#: Extras every generated project needs, whatever features it enables.
#:
#: ``record`` is here because ``import sillo`` currently fails without
#: ``tortoise-orm``: the package's ``__init__`` reaches ``sillo.users.base``,
#: which imports ``tortoise.fields`` unconditionally. So although the framework
#: declares ``record`` as optional, a project installed without it cannot start
#: at all — including a minimal project with no database.
#:
#: TODO(sillo): drop this once the framework guards that import, at which point
#: a database-free project can install a genuinely minimal dependency set.
REQUIRED_SILLO_EXTRAS = ("record",)

DEFAULT_BACKEND_PORT = 8000
DEFAULT_FRONTEND_PORT = 5173


class StrEnum(str, Enum):
    """String enum whose members render as their value.

    Python 3.11 ships ``enum.StrEnum``, but defining our own keeps the
    ``str``-subclass behaviour explicit at the point of use and makes the TOML
    round-trip obvious.
    """

    def __str__(self) -> str:
        return self.value


class AppType(StrEnum):
    """The shape of the application, which drives the default blueprint."""

    MINIMAL = "minimal"
    API = "api"
    WEB = "web"
    INERTIA = "inertia"
    WORKER = "worker"
    MODULAR = "modular"
    CUSTOM = "custom"


class DatabaseDriver(StrEnum):
    POSTGRES = "postgres"
    MYSQL = "mysql"
    SQLITE = "sqlite"
    NONE = "none"


class ORM(StrEnum):
    RECORD = "record"
    NONE = "none"


class AuthStrategy(StrEnum):
    SESSION = "session"
    JWT = "jwt"
    TOKEN = "token"
    APIKEY = "apikey"
    NONE = "none"


class InertiaAdapter(StrEnum):
    REACT = "react"
    VUE = "vue"
    SVELTE = "svelte"


class QueueDriver(StrEnum):
    REDIS = "redis"
    DATABASE = "database"
    MEMORY = "memory"
    NONE = "none"


class CacheDriver(StrEnum):
    REDIS = "redis"
    MEMORY = "memory"
    DATABASE = "database"
    FILE = "file"
    NONE = "none"


class SessionDriver(StrEnum):
    COOKIE = "cookie"
    REDIS = "redis"
    DATABASE = "database"
    FILE = "file"
    MEMORY = "memory"


class MailDriver(StrEnum):
    SMTP = "smtp"
    CONSOLE = "console"
    MAILPIT = "mailpit"
    NONE = "none"


class StorageDriver(StrEnum):
    LOCAL = "local"
    S3 = "s3"
    NONE = "none"


class PythonPackageManager(StrEnum):
    UV = "uv"
    PIP = "pip"


class FrontendPackageManager(StrEnum):
    BUN = "bun"
    NPM = "npm"
    PNPM = "pnpm"
    YARN = "yarn"


#: Database drivers that need a server process, and so a Docker service and a
#: connectivity health check.
SERVER_DATABASES = {DatabaseDriver.POSTGRES, DatabaseDriver.MYSQL}

#: Python driver packages each database backend needs. Record wraps Tortoise,
#: which delegates to these.
DATABASE_DRIVER_PACKAGES: dict[DatabaseDriver, list[str]] = {
    DatabaseDriver.POSTGRES: ["asyncpg>=0.29.0"],
    DatabaseDriver.MYSQL: ["aiomysql>=0.2.0"],
    DatabaseDriver.SQLITE: ["aiosqlite>=0.19.0"],
    DatabaseDriver.NONE: [],
}

#: Default connection URLs written into ``.env.example``.
DATABASE_URL_TEMPLATES: dict[DatabaseDriver, str] = {
    DatabaseDriver.POSTGRES: "postgres://postgres:postgres@localhost:5432/{name}",
    DatabaseDriver.MYSQL: "mysql://root:root@localhost:3306/{name}",
    DatabaseDriver.SQLITE: "sqlite://storage/{name}.db",
    DatabaseDriver.NONE: "",
}

#: Default ports, used for conflict detection and for the compose file.
DATABASE_PORTS: dict[DatabaseDriver, int] = {
    DatabaseDriver.POSTGRES: 5432,
    DatabaseDriver.MYSQL: 3306,
}

#: Frontend dependencies per Inertia adapter. Verified against the Inertia.js
#: v2 package names.
INERTIA_FRONTEND_PACKAGES: dict[InertiaAdapter, dict[str, list[str]]] = {
    InertiaAdapter.REACT: {
        "dependencies": ["@inertiajs/react", "react", "react-dom"],
        "devDependencies": [
            "@vitejs/plugin-react",
            "vite",
            "typescript",
            "@types/react",
            "@types/react-dom",
        ],
    },
    InertiaAdapter.VUE: {
        "dependencies": ["@inertiajs/vue3", "vue"],
        "devDependencies": ["@vitejs/plugin-vue", "vite", "typescript", "vue-tsc"],
    },
    InertiaAdapter.SVELTE: {
        "dependencies": ["@inertiajs/svelte", "svelte"],
        "devDependencies": [
            "@sveltejs/vite-plugin-svelte",
            "vite",
            "typescript",
            "svelte-check",
        ],
    },
}

#: The entry file Vite builds, per adapter. Referenced by the generated
#: ``vite.config`` and passed to ``vite_react()`` / ``vite_vue()``.
INERTIA_ENTRY_FILES: dict[InertiaAdapter, str] = {
    InertiaAdapter.REACT: "src/main.tsx",
    InertiaAdapter.VUE: "src/main.ts",
    InertiaAdapter.SVELTE: "src/main.ts",
}

#: File extension for generated page components, per adapter.
INERTIA_PAGE_EXTENSIONS: dict[InertiaAdapter, str] = {
    InertiaAdapter.REACT: "tsx",
    InertiaAdapter.VUE: "vue",
    InertiaAdapter.SVELTE: "svelte",
}
