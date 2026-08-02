"""Manifest building, blueprints, structure and project creation."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sillo_start.blueprints.registry import registry as blueprint_registry
from sillo_start.config.defaults import (
    ORM,
    AuthStrategy,
    DatabaseDriver,
    QueueDriver,
)
from sillo_start.config.loader import load_manifest, require_manifest_path
from sillo_start.exceptions import ProjectExistsError
from sillo_start.project.creator import ProjectCreator
from sillo_start.project.manifest import ProjectOptions, build_manifest
from sillo_start.project.structure import directories_for, package_directories


class TestBlueprints:
    def test_every_expected_blueprint_is_registered(self):
        for name in ("minimal", "api", "fullstack", "inertia-react", "worker", "enterprise"):
            assert blueprint_registry.has(name)

    def test_the_api_blueprint_enables_the_api_group(self, api_manifest):
        assert "api" in api_manifest.packages.groups

    def test_the_fullstack_blueprint_wires_database_auth_and_admin(self, fullstack_manifest):
        assert fullstack_manifest.uses_record
        assert fullstack_manifest.auth.enabled
        assert fullstack_manifest.admin.enabled
        assert fullstack_manifest.session.enabled

    def test_the_minimal_blueprint_stays_minimal(self):
        blueprint = blueprint_registry.get("minimal")
        manifest = build_manifest(ProjectOptions(name="tiny", blueprint="minimal"), blueprint)

        assert manifest.database.enabled is False
        assert manifest.auth.enabled is False
        assert manifest.admin.enabled is False

    @pytest.mark.parametrize(
        ("blueprint", "adapter"),
        [("inertia-react", "react"), ("inertia-vue", "vue"), ("inertia-svelte", "svelte")],
    )
    def test_each_inertia_blueprint_selects_its_adapter(self, blueprint, adapter):
        obj = blueprint_registry.get(blueprint)
        manifest = build_manifest(ProjectOptions(name="app", blueprint=blueprint), obj)

        assert manifest.inertia.enabled
        assert manifest.inertia.adapter == adapter


class TestManifestBuilding:
    def test_explicit_choices_override_blueprint_defaults(self):
        blueprint = blueprint_registry.get("fullstack")
        options = ProjectOptions(
            name="app", blueprint="fullstack", database=DatabaseDriver.POSTGRES
        )
        manifest = build_manifest(options, blueprint)

        assert manifest.database.driver == DatabaseDriver.POSTGRES

    def test_auth_implies_a_database(self):
        blueprint = blueprint_registry.get("minimal")
        options = ProjectOptions(name="app", blueprint="minimal", auth=AuthStrategy.JWT)
        manifest = build_manifest(options, blueprint)

        assert manifest.database.enabled is True
        assert manifest.database.orm == ORM.RECORD

    def test_the_admin_panel_implies_auth_and_a_database(self):
        blueprint = blueprint_registry.get("minimal")
        options = ProjectOptions(name="app", blueprint="minimal", admin=True)
        manifest = build_manifest(options, blueprint)

        assert manifest.auth.enabled is True
        assert manifest.database.enabled is True
        assert manifest.admin.title

    def test_session_auth_enables_session_storage(self):
        blueprint = blueprint_registry.get("api")
        options = ProjectOptions(name="app", blueprint="api", auth=AuthStrategy.SESSION)
        manifest = build_manifest(options, blueprint)

        assert manifest.session.enabled is True

    def test_features_imply_their_package_groups(self):
        blueprint = blueprint_registry.get("minimal")
        options = ProjectOptions(
            name="app", blueprint="minimal", admin=True, queue=QueueDriver.REDIS
        )
        manifest = build_manifest(options, blueprint)

        assert {"record", "auth", "admin", "work"} <= set(manifest.packages.groups)

    def test_development_commands_use_real_executables(self, fullstack_manifest):
        """The framework ships no CLI, so the commands must be real ones."""
        assert fullstack_manifest.development.backend_command.startswith("uvicorn")
        assert "sillo run" not in fullstack_manifest.development.backend_command

    def test_a_queue_project_gets_a_worker_command(self):
        blueprint = blueprint_registry.get("api")
        options = ProjectOptions(name="app", blueprint="api", queue=QueueDriver.REDIS)
        manifest = build_manifest(options, blueprint)

        assert manifest.development.worker_command == "python scripts/worker.py"

    def test_toggles_are_applied_by_dotted_path(self):
        blueprint = blueprint_registry.get("api")
        options = ProjectOptions(name="app", blueprint="api", toggles={"api.cors": False})
        manifest = build_manifest(options, blueprint)

        assert manifest.api.cors is False

    def test_an_unknown_toggle_is_ignored_rather_than_fatal(self):
        blueprint = blueprint_registry.get("api")
        options = ProjectOptions(name="app", blueprint="api", toggles={"nope.nothing": True})
        build_manifest(options, blueprint)  # must not raise


class TestStructure:
    def test_only_the_needed_directories_are_planned(self, manifest):
        directories = directories_for(manifest)

        assert "app" in directories
        assert "app/jobs" not in directories
        assert "frontend/src/pages" not in directories

    def test_enabling_a_feature_adds_its_directories(self, manifest):
        manifest.queue.enabled = True
        assert "app/jobs" in directories_for(manifest)

    def test_parent_packages_are_included(self):
        packages = package_directories(["database/models"])
        assert "database" in packages
        assert "database/models" in packages

    def test_data_directories_are_not_packages(self):
        assert package_directories(["storage/logs"]) == []


class TestCreation:
    def test_generates_the_expected_files(self, project: Path):
        for relative in (
            "pyproject.toml",
            "pyproject.toml",
            "README.md",
            ".gitignore",
            ".env",
            ".env.example",
            "app/main.py",
            "app/bootstrap.py",
            "app/config.py",
            "routes/api.py",
        ):
            assert (project / relative).is_file(), f"missing {relative}"

    def test_every_generated_python_file_parses(self, project: Path):
        """Generated code must at minimum be syntactically valid Python."""
        for path in project.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            try:
                ast.parse(source)
            except SyntaxError as error:  # pragma: no cover - failure detail
                pytest.fail(f"{path.relative_to(project)} is not valid Python: {error}")

    def test_the_manifest_round_trips(self, project: Path):
        manifest = load_manifest(require_manifest_path(project))
        assert manifest.project.name == "testapp"
        assert manifest.project.created_with

    def test_secrets_are_generated_rather_than_placeheld(self, project: Path):
        """A new project must never be born with a shipped secret."""
        blueprint = blueprint_registry.get("fullstack")
        options = ProjectOptions(name="withauth", blueprint="fullstack")
        manifest = build_manifest(options, blueprint)
        root = project.parent / "withauth"
        ProjectCreator().create(root, manifest, blueprint, git=False)

        env = (root / ".env").read_text()
        secret_line = next(line for line in env.splitlines() if line.startswith("SECRET_KEY="))
        value = secret_line.split("=", 1)[1]

        assert value not in ("", "change-me")
        assert len(value) >= 32

    def test_refuses_to_generate_into_a_non_empty_directory(self, tmp_path, manifest):
        root = tmp_path / "occupied"
        root.mkdir()
        (root / "existing.py").write_text("mine")

        with pytest.raises(ProjectExistsError):
            ProjectCreator().create(root, manifest, blueprint_registry.get("api"), git=False)

    def test_force_allows_generating_into_a_non_empty_directory(self, tmp_path, manifest):
        root = tmp_path / "occupied"
        root.mkdir()
        (root / "existing.py").write_text("mine")

        ProjectCreator().create(
            root, manifest, blueprint_registry.get("api"), git=False, force=True
        )

        assert (root / "existing.py").read_text() == "mine"
        assert require_manifest_path(root).exists()

    def test_dry_run_writes_nothing(self, tmp_path, manifest):
        root = tmp_path / "preview"
        blueprint = blueprint_registry.get("api")
        creator = ProjectCreator()
        resolution = creator._resolve_groups(manifest)
        plan = creator.build_plan(root, manifest, blueprint, resolution)

        from sillo_start.operations.base import ExecutionContext
        from sillo_start.operations.transaction import execute_plan

        execute_plan(
            plan,
            ExecutionContext(project_root=root, manifest=manifest, dry_run=True),
            show_progress=False,
        )

        assert not root.exists() or not any(root.iterdir())

    def test_a_minimal_project_has_no_database_scaffolding(self, project_factory):
        root = project_factory(blueprint="minimal", name="tiny")
        assert not (root / "database").exists()
        assert not (root / "app/admin.py").exists()

    def test_a_fullstack_project_has_auth_and_admin(self, project_factory):
        root = project_factory(blueprint="fullstack", name="shop")

        assert (root / "database/models/user.py").is_file()
        assert (root / "routes/auth.py").is_file()
        assert (root / "app/admin.py").is_file()
        # A package directory here would shadow app/admin.py on import.
        assert not (root / "app/admin").is_dir()

    def test_the_models_package_imports_its_models(self, project_factory):
        """A model the package does not import is invisible to the ORM."""
        root = project_factory(blueprint="fullstack", name="shop")
        source = (root / "database/models/__init__.py").read_text()

        assert "from database.models.user import User" in source
        assert "__models__" in source

    def test_the_user_model_binds_its_manager(self, project_factory):
        """Without this the manager falls back to a model we do not register."""
        root = project_factory(blueprint="fullstack", name="shop")
        source = (root / "database/models/user.py").read_text()

        assert "contribute_to_class" in source

    def test_routers_are_mounted_most_specific_first(self, project_factory):
        """Mounting /api before /api/auth would make every auth route 404."""
        root = project_factory(blueprint="fullstack", name="shop")
        source = (root / "app/bootstrap.py").read_text()

        assert source.index("routes.auth") < source.index("routes.api")

    def test_authentication_middleware_is_registered_before_sessions(self, project_factory):
        """`use()` runs last-registered first, so sessions must come after."""
        root = project_factory(blueprint="fullstack", name="shop")
        source = (root / "app/bootstrap.py").read_text()

        assert source.index("AuthenticationMiddleware(") < source.index("SessionMiddleware(")

    def test_the_admin_project_registers_the_admin_models_module(self, project_factory):
        """The panel needs its own tables for the activity log and roles."""
        root = project_factory(blueprint="fullstack", name="shop")
        source = (root / "app/bootstrap.py").read_text()

        assert "sillo.admin.models" in source

    def test_sillo_users_is_never_added_to_the_model_modules(self, project_factory):
        """It would displace the project's own User and drop its columns.

        The list is read from the syntax tree rather than by searching the
        text, so the comment explaining this constraint does not itself trip
        the assertion.
        """
        root = project_factory(blueprint="fullstack", name="shop")
        tree = ast.parse((root / "app/bootstrap.py").read_text())

        modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "model_modules":
                modules = [
                    element.value
                    for element in node.value.elts  # type: ignore[attr-defined]
                    if isinstance(element, ast.Constant)
                ]

        assert modules, "bootstrap.py should pass model_modules to setup_record"
        assert "sillo.users" not in modules
        assert "database.models" in modules

    def test_the_pyproject_declares_one_framework_requirement(self, project_factory):
        root = project_factory(blueprint="fullstack", name="shop")
        source = (root / "pyproject.toml").read_text()

        assert source.count("sillo-framework") == 1
        assert "sillo-framework[" in source

    def test_a_queue_project_gets_a_worker_script(self, project_factory):
        root = project_factory(blueprint="worker", name="jobs")
        assert (root / "scripts/worker.py").is_file()

    def test_an_inertia_project_gets_its_frontend(self, project_factory):
        root = project_factory(blueprint="inertia-react", name="site")

        assert (root / "frontend/package.json").is_file()
        assert (root / "frontend/src/main.tsx").is_file()
        assert (root / "frontend/src/pages/Home.tsx").is_file()
        assert (root / "templates/app.html").is_file()
        assert (root / "routes/web.py").is_file()

    def test_the_root_view_keeps_the_placeholders_inertia_substitutes(self, project_factory):
        root = project_factory(blueprint="inertia-vue", name="site")
        html = (root / "templates/app.html").read_text()

        assert "{{ inertia }}" in html
        assert "{{ inertia_head }}" in html
        assert "{{ root_id }}" in html

    def test_next_steps_reflect_the_enabled_features(self, tmp_path):
        blueprint = blueprint_registry.get("fullstack")
        manifest = build_manifest(ProjectOptions(name="shop", blueprint="fullstack"), blueprint)
        result = ProjectCreator().create(tmp_path / "shop", manifest, blueprint, git=False)

        joined = " ".join(result.next_steps)
        assert "migrate run" in joined
        assert "admin create-user" in joined
        assert "Admin" in result.urls
