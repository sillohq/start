"""Plugin loading, the wizard, and template rendering."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sillo_start.blueprints.base import Blueprint
from sillo_start.blueprints.registry import BlueprintRegistry
from sillo_start.config.defaults import (
    AppType,
    AuthStrategy,
    DatabaseDriver,
    FrontendPackageManager,
    InertiaAdapter,
)
from sillo_start.exceptions import PluginError
from sillo_start.packages.registry import PackageGroup, PackageRegistry
from sillo_start.plugins.api import Plugin
from sillo_start.plugins.loader import load_plugins, plugin_failures
from sillo_start.prompts.questions import Option, ScriptedAnswerer
from sillo_start.prompts.wizard import SetupWizard
from sillo_start.templating import TemplateEngine, build_context


@dataclass
class FakeEntryPoint:
    """Stands in for an importlib entry point."""

    name: str
    target: object

    def load(self):
        return self.target


class TestPluginApi:
    def test_a_plugin_can_register_a_package_group(self, monkeypatch):
        registry = PackageRegistry()
        monkeypatch.setattr("sillo_start.plugins.api.package_registry", registry)

        plugin = Plugin(name="search-plugin")
        plugin.register_package_group(PackageGroup(name="search", summary="Search."))

        assert registry.has("search")
        assert plugin.registered["package_groups"] == ["search"]

    def test_a_plugin_can_register_a_blueprint(self, monkeypatch):
        registry = BlueprintRegistry()
        monkeypatch.setattr("sillo_start.plugins.api.blueprint_registry", registry)

        plugin = Plugin(name="bp-plugin")
        plugin.register_blueprint(Blueprint(name="cms", summary="A CMS."))

        assert registry.has("cms")

    def test_colliding_with_a_built_in_name_is_refused(self):
        plugin = Plugin(name="bad-plugin")
        with pytest.raises(PluginError) as error:
            plugin.register_package_group(PackageGroup(name="record", summary="Mine."))
        assert "already exists" in str(error.value)


class TestPluginLoading:
    def test_loads_a_working_plugin(self, monkeypatch):
        registered = []

        def factory(plugin: Plugin) -> None:
            registered.append(plugin.name)

        monkeypatch.setattr(
            "sillo_start.plugins.loader._discover",
            lambda: [FakeEntryPoint("good", factory)],
        )
        loaded = load_plugins(reload=True)

        assert "good" in loaded
        assert registered == ["good"]

    def test_a_plugin_that_raises_is_skipped_not_fatal(self, monkeypatch):
        """One broken third-party package must not make the CLI unusable."""

        def broken(plugin: Plugin) -> None:
            raise RuntimeError("kaboom")

        def working(plugin: Plugin) -> None:
            return None

        monkeypatch.setattr(
            "sillo_start.plugins.loader._discover",
            lambda: [FakeEntryPoint("broken", broken), FakeEntryPoint("working", working)],
        )
        loaded = load_plugins(reload=True)

        assert "working" in loaded
        assert "broken" not in loaded
        assert "kaboom" in plugin_failures()["broken"]

    def test_a_plugin_that_cannot_import_is_skipped(self, monkeypatch):
        class Unimportable(FakeEntryPoint):
            def load(self):
                raise ImportError("no such module")

        monkeypatch.setattr(
            "sillo_start.plugins.loader._discover",
            lambda: [Unimportable("missing", None)],
        )
        load_plugins(reload=True)

        assert "missing" in plugin_failures()

    def test_discovery_failure_is_survivable(self, monkeypatch):
        def explode():
            raise RuntimeError("broken environment")

        monkeypatch.setattr("sillo_start.plugins.loader.entry_points", lambda **_: explode())
        assert load_plugins(reload=True) == {}


class TestWizard:
    def test_a_scripted_run_produces_a_coherent_configuration(self):
        answerer = ScriptedAnswerer(
            {
                "Project name": "myshop",
                "What kind of application": AppType.API,
                "Short description": "A shop.",
                "Which database": DatabaseDriver.POSTGRES,
                "How should users authenticate": AuthStrategy.SESSION,
                "authentication features": ["registration", "tests"],
                "sessions be stored": "cookie",
                "authorization scaffolding": [],
                "admin panel": True,
                "Inertia frontend": False,
                "background jobs": False,
                "scheduled tasks": False,
                "advanced options": False,
                "developer tools": ["ruff", "pytest"],
            }
        )
        options, blueprint = SetupWizard(answerer=answerer).run()

        assert options.name == "myshop"
        assert options.database is DatabaseDriver.POSTGRES
        assert options.auth is AuthStrategy.SESSION
        assert options.admin is True
        assert blueprint.name == "api"

    def test_a_supplied_name_skips_the_name_question(self):
        answerer = ScriptedAnswerer({"What kind of application": AppType.MINIMAL})
        options, _ = SetupWizard(answerer=answerer).run("given-name")

        assert options.name == "given-name"
        assert not any("Project name" in question for question in answerer.asked)

    def test_choosing_inertia_asks_for_the_adapter(self):
        answerer = ScriptedAnswerer(
            {
                "Project name": "site",
                "What kind of application": AppType.INERTIA,
                "frontend framework": InertiaAdapter.REACT,
                "Which database": DatabaseDriver.SQLITE,
                "How should users authenticate": AuthStrategy.SESSION,
                "authentication features": [],
                "sessions be stored": "cookie",
                "authorization scaffolding": [],
                "admin panel": False,
                "package manager for the frontend": FrontendPackageManager.NPM,
                "background jobs": False,
                "scheduled tasks": False,
                "advanced options": False,
                "developer tools": ["pytest"],
            }
        )
        _, blueprint = SetupWizard(answerer=answerer).run()

        assert blueprint.name == "inertia-react"

    def test_no_database_means_no_authentication_question(self):
        """Every auth strategy needs somewhere to look a user up."""
        answerer = ScriptedAnswerer(
            {
                "Project name": "tiny",
                "What kind of application": AppType.MINIMAL,
                "Which database": DatabaseDriver.NONE,
                "background jobs": False,
                "scheduled tasks": False,
                "advanced options": False,
                "developer tools": [],
            }
        )
        options, _ = SetupWizard(answerer=answerer).run()

        assert options.auth is AuthStrategy.NONE
        assert not any("authenticate" in question for question in answerer.asked)


class TestTemplating:
    def test_the_context_exposes_the_manifest_and_derived_values(self, fullstack_manifest):
        context = build_context(fullstack_manifest)

        assert context["name"] == "testapp"
        assert context["title"] == "Testapp"
        assert context["uses_record"] is True
        assert context["manifest"] is fullstack_manifest

    def test_every_built_in_template_renders_for_a_full_configuration(self, fullstack_manifest):
        """A template that only renders for some manifests is a latent crash.

        The context is the union of what project creation, the Inertia feature
        and the generators supply, so every template is exercised regardless of
        which subsystem normally renders it.
        """
        engine = TemplateEngine()
        fullstack_manifest.inertia.enabled = True
        fullstack_manifest.queue.enabled = True
        fullstack_manifest.scheduler.enabled = True

        context = build_context(
            fullstack_manifest,
            # Project creation.
            dependencies=["sillo-framework"],
            dev_dependencies=["pytest"],
            database_url="sqlite://test.db",
            secret_key="x" * 50,
            jwt_secret="y" * 50,
            routers=[("api", "api_router", "/api")],
            sillo_manifest="[tool.sillo.project]\nmanifest_version = 1\n",
            # The Inertia feature.
            adapter="react",
            entry="src/main.tsx",
            extension="tsx",
            frontend="frontend",
            # The generators.
            pascal="Post",
            snake="post",
            camel="post",
            kebab="post",
            plural="posts",
            table="posts",
            human="Post",
            fields=[],
            timestamps=True,
            soft_deletes=False,
            needs_decimal=False,
            needs_date=False,
            needs_uuid=False,
        )

        from pathlib import Path

        from sillo_start.templating import TEMPLATE_ROOT

        for path in sorted(Path(TEMPLATE_ROOT).rglob("*.j2")):
            relative = path.relative_to(TEMPLATE_ROOT).as_posix()
            engine.render(relative, context)

    @pytest.mark.parametrize("strategy", ["jwt", "token", "session", "apikey", "none"])
    def test_bootstrap_never_reads_a_config_field_config_does_not_declare(
        self, fullstack_manifest, strategy
    ):
        """Every ``config.X`` in the bootstrap must exist on the settings class.

        These two templates guard their blocks independently, so a field can be
        emitted under one condition and read under another. That renders fine
        and only fails at startup, as an AttributeError from pydantic — which
        is what happened when the session fields were guarded on the auth
        strategy while the session middleware was guarded on session.enabled.
        """
        import ast
        import re

        fullstack_manifest.auth.strategy = strategy
        fullstack_manifest.auth.enabled = strategy != "none"
        # Sessions on regardless of strategy: that is the combination that broke.
        fullstack_manifest.session.enabled = True

        context = build_context(
            fullstack_manifest,
            database_url="sqlite://test.db",
            secret_key="x" * 50,
            jwt_secret="y" * 50,
            routers=[("api", "api_router", "/api")],
        )
        engine = TemplateEngine()
        config_source = engine.render("app/config.py.j2", context)
        bootstrap_source = engine.render("app/bootstrap.py.j2", context)

        declared = {
            node.target.id
            for node in ast.walk(ast.parse(config_source))
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        }
        used = set(re.findall(r"\bconfig\.([a-z_][a-z0-9_]*)", bootstrap_source))

        missing = sorted(used - declared)
        assert not missing, (
            f"auth.strategy={strategy}: bootstrap reads {missing} but "
            f"app/config.py declares {sorted(declared)}"
        )

    def test_admin_is_registered_before_the_middleware_block(self, fullstack_manifest):
        """The admin's auth middleware must end up *inside* the session one.

        ``AdminSite.mount()`` attaches its auth middleware with ``app.use()``,
        and ``use`` makes the newest registration outermost. Registering the
        admin after the middleware block therefore puts its auth ahead of the
        session middleware, and every admin page 500s with "No Session
        Middleware Installed" even though sessions are installed.
        """
        fullstack_manifest.admin.enabled = True
        context = build_context(
            fullstack_manifest,
            database_url="sqlite://test.db",
            secret_key="x" * 50,
            jwt_secret="y" * 50,
            routers=[("api", "api_router", "/api")],
        )
        source = TemplateEngine().render("app/bootstrap.py.j2", context)
        body = source.split("def create_app")[1].split("def _register_middleware")[0]

        admin_at = body.index("_register_admin(application)")
        middleware_at = body.index("_register_middleware(application)")
        assert admin_at < middleware_at, (
            "_register_admin must come before _register_middleware in create_app"
        )

    def test_admin_forces_session_middleware_on(self, fullstack_manifest):
        """Enabling the admin must install sessions even with JWT auth."""
        fullstack_manifest.admin.enabled = True
        fullstack_manifest.session.enabled = False
        fullstack_manifest.auth.enabled = True
        fullstack_manifest.auth.strategy = "jwt"

        assert fullstack_manifest.uses_sessions is True

        context = build_context(
            fullstack_manifest,
            database_url="sqlite://test.db",
            secret_key="x" * 50,
            jwt_secret="y" * 50,
            routers=[],
        )
        engine = TemplateEngine()
        bootstrap = engine.render("app/bootstrap.py.j2", context)
        config_source = engine.render("app/config.py.j2", context)

        assert "from sillo.session import" in bootstrap
        assert "SessionMiddleware(" in bootstrap
        assert "session_cookie_name:" in config_source

    def test_a_missing_template_is_reported_clearly(self):
        from sillo_start.exceptions import GeneratorError

        with pytest.raises(GeneratorError) as error:
            TemplateEngine().render("nope/missing.j2", {})
        assert "not found" in str(error.value)

    def test_naming_filters_are_available(self):
        engine = TemplateEngine()
        rendered = engine.render_string("{{ 'blog_post' | pascal }}", {})
        assert rendered == "BlogPost"

    def test_an_undefined_variable_fails_loudly(self):
        """Silently rendering an empty string produces a file that breaks later."""
        from sillo_start.exceptions import GeneratorError

        with pytest.raises(GeneratorError):
            TemplateEngine().render_string("{{ never_defined }}", {})


class TestOptions:
    def test_an_option_renders_its_description(self):
        choice = Option("value", "Label", "explanation").to_choice()
        assert "explanation" in choice.title
