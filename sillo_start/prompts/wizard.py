"""The interactive setup wizard.

The wizard is a funnel, not a questionnaire. The first answer — what kind of
application this is — picks a blueprint that supplies sensible values for
everything else, and later questions are skipped when the answer cannot matter:
no session backend question when there is no authentication, no adapter
question when there is no frontend.

Advanced settings are behind one opt-in question, so the common path stays
short while everything remains reachable.
"""

from __future__ import annotations

from ..blueprints.base import Blueprint
from ..blueprints.registry import registry as blueprint_registry
from ..config.defaults import (
    AppType,
    AuthStrategy,
    CacheDriver,
    DatabaseDriver,
    FrontendPackageManager,
    InertiaAdapter,
    MailDriver,
    QueueDriver,
    SessionDriver,
    StorageDriver,
)
from ..packages.registry import registry as package_registry
from ..project.manifest import ProjectOptions
from ..utils.console import Console
from ..utils.console import console as default_console
from ..utils.naming import is_valid_project_name
from .questions import Answerer, Option

#: Application types, in the order the wizard offers them, mapped to the
#: blueprint each one implies.
APP_TYPE_BLUEPRINTS: dict[AppType, str] = {
    AppType.API: "api",
    AppType.INERTIA: "inertia-react",
    AppType.WEB: "fullstack",
    AppType.WORKER: "worker",
    AppType.MODULAR: "modular-monolith",
    AppType.MINIMAL: "minimal",
    AppType.CUSTOM: "api",
}


class SetupWizard:
    """Collects project choices interactively."""

    def __init__(
        self,
        answerer: Answerer | None = None,
        console: Console | None = None,
    ) -> None:
        self.ask = answerer or Answerer()
        self.console = console or default_console

    def run(self, name: str | None = None) -> tuple[ProjectOptions, Blueprint]:
        """Run the wizard.

        Args:
            name: Project name supplied on the command line, which skips the
                first question.

        Returns:
            The collected options and the blueprint they imply.
        """
        self.console.header(
            "Create a Sillo application",
            "Answer a few questions — everything can be changed later with `sillo-start add`.",
        )

        project_name = name or self._ask_name()
        app_type = self._ask_app_type()
        blueprint = self._resolve_blueprint(app_type)

        options = ProjectOptions(name=project_name, blueprint=blueprint.name)
        options.description = self.ask.text("Short description (optional)", default="")

        self._ask_database(options, app_type)
        self._ask_auth(options)
        self._ask_admin(options)
        self._ask_frontend(options, app_type)
        self._ask_background(options, app_type)

        if self.ask.confirm("Configure advanced options (cache, mail, storage, API features)?", default=False):
            self._ask_cache(options)
            self._ask_mail(options)
            self._ask_storage(options)
            self._ask_api_features(options)
            self._ask_package_groups(options)

        self._ask_tooling(options)
        return options, blueprint

    # -- individual questions -------------------------------------------

    def _ask_name(self) -> str:
        def validate(value: str) -> bool | str:
            value = value.strip()
            if not value:
                return "Please enter a name."
            if not is_valid_project_name(value):
                return "Use a letter followed by letters, digits, dashes or underscores."
            return True

        return self.ask.text("Project name", default="myapp", validate=validate)

    def _ask_app_type(self) -> AppType:
        return self.ask.select(
            "What kind of application is this?",
            [
                Option(AppType.API, "API only", "JSON REST API with OpenAPI docs"),
                Option(AppType.INERTIA, "Full-stack (Inertia)", "React, Vue or Svelte served by Sillo"),
                Option(AppType.WEB, "Server-rendered", "HTML pages, sessions, admin panel"),
                Option(AppType.WORKER, "Background worker", "queues and scheduled tasks"),
                Option(AppType.MODULAR, "Modular monolith", "feature modules that can be split later"),
                Option(AppType.MINIMAL, "Minimal", "routing and config only"),
                Option(AppType.CUSTOM, "Custom", "start from the API shape and choose everything"),
            ],
            default=AppType.API,
        )

    def _resolve_blueprint(self, app_type: AppType) -> Blueprint:
        """Pick the blueprint for an application type.

        The Inertia blueprints differ only by adapter, so the adapter question
        is asked here rather than leaving the user to choose between three
        near-identical blueprint names.
        """
        if app_type is AppType.INERTIA:
            adapter = self.ask.select(
                "Which frontend framework?",
                [
                    Option(InertiaAdapter.REACT, "React", "@inertiajs/react"),
                    Option(InertiaAdapter.VUE, "Vue", "@inertiajs/vue3"),
                    Option(InertiaAdapter.SVELTE, "Svelte", "@inertiajs/svelte"),
                ],
                default=InertiaAdapter.REACT,
            )
            return blueprint_registry.get(f"inertia-{adapter.value}")
        return blueprint_registry.get(APP_TYPE_BLUEPRINTS[app_type])

    def _ask_database(self, options: ProjectOptions, app_type: AppType) -> None:
        options.database = self.ask.select(
            "Which database?",
            [
                Option(DatabaseDriver.SQLITE, "SQLite", "zero setup, great for getting started"),
                Option(DatabaseDriver.POSTGRES, "PostgreSQL", "recommended for production"),
                Option(DatabaseDriver.MYSQL, "MySQL / MariaDB", ""),
                Option(DatabaseDriver.NONE, "No database", ""),
            ],
            default=DatabaseDriver.SQLITE if app_type is not AppType.MINIMAL else DatabaseDriver.NONE,
        )

    def _ask_auth(self, options: ProjectOptions) -> None:
        if options.database is DatabaseDriver.NONE:
            # Every strategy needs somewhere to look a user up.
            options.auth = AuthStrategy.NONE
            return

        options.auth = self.ask.select(
            "How should users authenticate?",
            [
                Option(AuthStrategy.SESSION, "Session cookies", "best for server-rendered and Inertia apps"),
                Option(AuthStrategy.JWT, "JWT tokens", "best for APIs and mobile clients"),
                Option(AuthStrategy.APIKEY, "API keys", "machine-to-machine access"),
                Option(AuthStrategy.NONE, "No authentication", ""),
            ],
            default=AuthStrategy.SESSION,
        )
        if options.auth is AuthStrategy.NONE:
            return

        features = self.ask.multiselect(
            "Which authentication features?",
            [
                Option("registration", "Registration", "sign-up endpoint"),
                Option("password_reset", "Password reset", "request and confirm a reset"),
                Option("email_verification", "Email verification", ""),
                Option("remember_me", "Remember me", "long-lived sessions"),
                Option("tests", "Tests", "cover the auth flow"),
            ],
            default=["registration", "tests"],
        )
        for feature in ("registration", "password_reset", "email_verification", "remember_me", "tests"):
            options.toggles[f"auth.{feature}"] = feature in features

        if options.auth is AuthStrategy.SESSION:
            options.session = self.ask.select(
                "Where should sessions be stored?",
                [
                    Option(SessionDriver.COOKIE, "Signed cookie", "no server state"),
                    Option(SessionDriver.REDIS, "Redis", "shared across processes"),
                    Option(SessionDriver.DATABASE, "Database", ""),
                    Option(SessionDriver.FILE, "Filesystem", ""),
                ],
                default=SessionDriver.COOKIE,
            )

        authorization = self.ask.multiselect(
            "Add authorization scaffolding?",
            [
                Option("roles", "Roles", "a role column and role checks"),
                Option("permissions", "Permissions", "fine-grained grants"),
                Option("policies", "Policies", "per-model authorization classes"),
                Option("ownership", "Ownership checks", "'is this row mine?'"),
            ],
            default=[],
        )
        options.toggles["authorization.enabled"] = bool(authorization)
        for feature in ("roles", "permissions", "policies", "ownership"):
            options.toggles[f"authorization.{feature}"] = feature in authorization

    def _ask_admin(self, options: ProjectOptions) -> None:
        if options.database is DatabaseDriver.NONE:
            options.admin = False
            return
        options.admin = self.ask.confirm("Include the admin panel?", default=False)

    def _ask_frontend(self, options: ProjectOptions, app_type: AppType) -> None:
        if app_type is not AppType.INERTIA:
            if app_type in (AppType.WORKER, AppType.MINIMAL):
                return
            if not self.ask.confirm("Add an Inertia frontend?", default=False):
                return
            options.inertia = self.ask.select(
                "Which frontend framework?",
                [
                    Option(InertiaAdapter.REACT, "React", ""),
                    Option(InertiaAdapter.VUE, "Vue", ""),
                    Option(InertiaAdapter.SVELTE, "Svelte", ""),
                ],
                default=InertiaAdapter.REACT,
            )

        options.frontend_manager = self.ask.select(
            "Which package manager for the frontend?",
            [
                Option(FrontendPackageManager.NPM, "npm", "always available with Node"),
                Option(FrontendPackageManager.BUN, "bun", "fastest, if installed"),
                Option(FrontendPackageManager.PNPM, "pnpm", ""),
                Option(FrontendPackageManager.YARN, "yarn", ""),
            ],
            default=FrontendPackageManager.NPM,
        )

    def _ask_background(self, options: ProjectOptions, app_type: AppType) -> None:
        wants_queue = app_type is AppType.WORKER or self.ask.confirm(
            "Add background jobs?", default=app_type is AppType.WORKER
        )
        if wants_queue:
            options.queue = self.ask.select(
                "Which queue backend?",
                [
                    Option(QueueDriver.REDIS, "Redis", "recommended for production"),
                    Option(QueueDriver.DATABASE, "Database", "no extra service"),
                    Option(QueueDriver.MEMORY, "In-memory", "development only"),
                ],
                default=QueueDriver.REDIS,
            )
        else:
            options.queue = QueueDriver.NONE

        options.scheduler = self.ask.confirm("Add scheduled tasks?", default=wants_queue)

    def _ask_cache(self, options: ProjectOptions) -> None:
        options.cache = self.ask.select(
            "Cache backend?",
            [
                Option(CacheDriver.NONE, "None", ""),
                Option(CacheDriver.MEMORY, "In-memory", "per-process"),
                Option(CacheDriver.REDIS, "Redis", "shared"),
                Option(CacheDriver.FILE, "Filesystem", ""),
            ],
            default=CacheDriver.NONE,
        )

    def _ask_mail(self, options: ProjectOptions) -> None:
        options.mail = self.ask.select(
            "Mail transport?",
            [
                Option(MailDriver.NONE, "None", ""),
                Option(MailDriver.CONSOLE, "Console", "print messages during development"),
                Option(MailDriver.SMTP, "SMTP", "a real mail server"),
                Option(MailDriver.MAILPIT, "Mailpit", "local SMTP capture with a web UI"),
            ],
            default=MailDriver.NONE,
        )

    def _ask_storage(self, options: ProjectOptions) -> None:
        options.storage = self.ask.select(
            "File storage?",
            [
                Option(StorageDriver.NONE, "None", ""),
                Option(StorageDriver.LOCAL, "Local filesystem", "storage/app"),
                Option(StorageDriver.S3, "S3-compatible", "AWS S3, R2, MinIO"),
            ],
            default=StorageDriver.NONE,
        )

    def _ask_api_features(self, options: ProjectOptions) -> None:
        features = self.ask.multiselect(
            "Which API features?",
            [
                Option("openapi", "OpenAPI docs", "/docs and /redoc"),
                Option("cors", "CORS", "cross-origin requests"),
                Option("csrf", "CSRF protection", "for cookie-based auth"),
                Option("rate_limiting", "Rate limiting", ""),
                Option("pagination", "Pagination helpers", ""),
                Option("request_id", "Request IDs", "correlate logs across services"),
                Option("structured_logging", "Structured logging", "JSON logs"),
                Option("health_checks", "Health checks", "/health for probes"),
            ],
            default=["openapi", "health_checks"],
        )
        for feature in (
            "openapi",
            "cors",
            "csrf",
            "rate_limiting",
            "pagination",
            "request_id",
            "structured_logging",
            "health_checks",
        ):
            options.toggles[f"api.{feature}"] = feature in features

    def _ask_package_groups(self, options: ProjectOptions) -> None:
        chosen = self.ask.multiselect(
            "Enable any additional package groups?",
            [
                Option(group.name, group.name, group.summary)
                for group in package_registry.all()
            ],
            default=list(options.package_groups),
        )
        options.package_groups = list(chosen)

    def _ask_tooling(self, options: ProjectOptions) -> None:
        tools = self.ask.multiselect(
            "Which developer tools?",
            [
                Option("ruff", "Ruff", "linting and formatting"),
                Option("pytest", "pytest", "tests, with fixtures wired up"),
                Option("mypy", "Mypy", "static type checking"),
                Option("coverage", "Coverage", ""),
                Option("docker", "Dockerfile", ""),
                Option("compose", "Docker Compose", "database and Redis services"),
                Option("github_actions", "GitHub Actions", "CI workflow"),
                Option("pre_commit", "pre-commit", ""),
                Option("makefile", "Makefile", "shortcuts for common commands"),
                Option("editorconfig", ".editorconfig", ""),
            ],
            default=["ruff", "pytest", "editorconfig"],
        )
        for tool in (
            "ruff",
            "pytest",
            "mypy",
            "coverage",
            "docker",
            "compose",
            "github_actions",
            "pre_commit",
            "makefile",
            "editorconfig",
        ):
            options.toggles[f"tooling.{tool}"] = tool in tools


def confirm_summary(
    options: ProjectOptions,
    blueprint: Blueprint,
    answerer: Answerer,
    console: Console | None = None,
) -> bool:
    """Show what will be created and ask for confirmation.

    Returns:
        True when the user wants to proceed.
    """
    out = console or default_console
    out.blank()
    out.print("[bold]Ready to create:[/bold]")

    rows = [
        ("Name", options.name),
        ("Blueprint", f"{blueprint.name} — {blueprint.summary}"),
        ("Database", str(options.database or "none")),
        ("Auth", str(options.auth or "none")),
        ("Admin", "yes" if options.admin else "no"),
        ("Frontend", str(options.inertia) if options.inertia else "none"),
        ("Queue", str(options.queue or "none")),
        ("Scheduler", "yes" if options.scheduler else "no"),
    ]
    out.table(["", ""], rows)
    out.blank()
    return answerer.confirm("Create this project?", default=True)
