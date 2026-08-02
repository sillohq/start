"""CLI command behaviour, driven through Typer's test runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sillo_start import __version__
from sillo_start.cli import build_cli


def _manifest_text(root: Path) -> str:
    """The manifest file's contents, wherever the project keeps it."""
    from sillo_start.config.loader import require_manifest_path

    return require_manifest_path(root).read_text()


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def cli():
    return build_cli()


@pytest.fixture
def in_project(project: Path, monkeypatch):
    """Run commands from inside a generated project."""
    monkeypatch.chdir(project)
    return project


@pytest.fixture(autouse=True)
def _non_interactive(monkeypatch):
    """Make the CLI treat the test environment as CI, so nothing prompts."""
    monkeypatch.setenv("CI", "1")
    monkeypatch.setenv("NO_COLOR", "1")


@pytest.fixture(autouse=True)
def _loud_console():
    """Undo the global quiet fixture — these tests assert on output."""
    from sillo_start.utils.console import console

    console.quiet = False
    yield


class TestRootCommand:
    def test_help_lists_the_commands(self, runner, cli):
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        for command in ("create", "add", "dev", "doctor", "generate", "migrate", "package"):
            assert command in result.output

    def test_version_prints_the_version(self, runner, cli):
        result = runner.invoke(cli, ["--version"])

        assert result.exit_code == 0
        assert __version__ in result.output

    def test_an_unknown_command_exits_with_a_usage_code(self, runner, cli):
        result = runner.invoke(cli, ["nonsense"])
        assert result.exit_code != 0


class TestCreate:
    def test_creates_a_project_non_interactively(self, runner, cli, tmp_path):
        result = runner.invoke(
            cli,
            ["create", "demo", "--no-interaction", "--no-git", "--directory", str(tmp_path / "demo")],
        )

        assert result.exit_code == 0, result.output
        assert "[tool.sillo" in (tmp_path / "demo" / "pyproject.toml").read_text()
        assert (tmp_path / "demo" / "app" / "main.py").is_file()

    def test_requires_a_name_without_interaction(self, runner, cli):
        result = runner.invoke(cli, ["create", "--no-interaction"])

        assert result.exit_code == 2
        assert "name is required" in result.output

    def test_rejects_an_invalid_name_with_a_clear_message(self, runner, cli, tmp_path):
        result = runner.invoke(
            cli,
            ["create", "1bad", "--no-interaction", "--directory", str(tmp_path / "x")],
        )

        assert result.exit_code != 0
        assert "not a valid project name" in result.output

    def test_flags_are_reflected_in_the_manifest(self, runner, cli, tmp_path):
        target = tmp_path / "shop"
        result = runner.invoke(
            cli,
            [
                "create", "shop",
                "--database", "postgres",
                "--auth", "jwt",
                "--admin",
                "--queue", "redis",
                "--no-interaction", "--no-git",
                "--directory", str(target),
            ],
        )

        assert result.exit_code == 0, result.output
        manifest = (target / "pyproject.toml").read_text()
        assert 'driver = "postgres"' in manifest
        assert 'strategy = "jwt"' in manifest
        assert 'driver = "redis"' in manifest

    def test_dry_run_writes_nothing(self, runner, cli, tmp_path):
        target = tmp_path / "preview"
        result = runner.invoke(
            cli,
            ["create", "preview", "--no-interaction", "--dry-run", "--directory", str(target)],
        )

        assert result.exit_code == 0
        assert "Dry run" in result.output
        assert not target.exists()

    def test_refuses_a_non_empty_directory(self, runner, cli, tmp_path):
        target = tmp_path / "occupied"
        target.mkdir()
        (target / "file.txt").write_text("mine")

        result = runner.invoke(
            cli, ["create", "occupied", "--no-interaction", "--directory", str(target)]
        )

        assert result.exit_code != 0
        assert "not empty" in result.output

    def test_lists_the_blueprints(self, runner, cli):
        result = runner.invoke(cli, ["create", "--list-blueprints"])

        assert result.exit_code == 0
        assert "inertia-react" in result.output
        assert "minimal" in result.output

    def test_an_unknown_blueprint_lists_the_valid_ones(self, runner, cli, tmp_path):
        result = runner.invoke(
            cli,
            ["create", "x", "--blueprint", "nope", "--no-interaction", "--directory", str(tmp_path / "x")],
        )

        assert result.exit_code != 0
        assert "Unknown blueprint" in result.output


class TestInspect:
    def test_reports_the_configuration(self, runner, cli, in_project):
        result = runner.invoke(cli, ["inspect"])

        assert result.exit_code == 0
        assert "testapp" in result.output
        assert "Package groups" in result.output

    def test_json_output_is_machine_readable(self, runner, cli, in_project):
        result = runner.invoke(cli, ["inspect", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["project"]["name"] == "testapp"

    def test_a_single_section_can_be_requested(self, runner, cli, in_project):
        result = runner.invoke(cli, ["inspect", "--json", "--section", "application"])

        assert result.exit_code == 0
        assert json.loads(result.stdout)["entrypoint"] == "app.main:app"

    def test_outside_a_project_it_explains_itself(self, runner, cli, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["inspect"])

        assert result.exit_code != 0
        assert "No sillo.toml" in result.output


class TestPackage:
    def test_lists_groups_and_marks_the_installed_ones(self, runner, cli, in_project):
        result = runner.invoke(cli, ["package", "list"])

        assert result.exit_code == 0
        assert "record" in result.output
        assert "inertia" in result.output

    def test_json_output_reports_installed_state(self, runner, cli, in_project):
        result = runner.invoke(cli, ["package", "list", "--json"])

        assert result.exit_code == 0
        groups = {entry["name"]: entry for entry in json.loads(result.stdout)}
        assert groups["api"]["installed"] is True
        assert groups["inertia"]["installed"] is False

    def test_info_describes_a_group(self, runner, cli, in_project):
        result = runner.invoke(cli, ["package", "info", "record"])

        assert result.exit_code == 0
        assert "Tortoise" in result.output
        assert "DATABASE_URL" in result.output
        # Migrations are Tortoise-native now; aerich must not come back as a
        # dependency of the record group.
        assert "aerich" not in result.output.lower()

    def test_info_on_an_unknown_group_suggests_alternatives(self, runner, cli, in_project):
        result = runner.invoke(cli, ["package", "info", "nope"])

        assert result.exit_code != 0
        assert "Available groups" in result.output

    def test_add_dry_run_shows_the_plan_without_applying(self, runner, cli, in_project):
        before = _manifest_text(in_project)
        result = runner.invoke(cli, ["package", "add", "monitoring", "--dry-run", "--no-install"])

        assert result.exit_code == 0
        assert "Dry run" in result.output
        assert _manifest_text(in_project) == before

    def test_add_enables_the_group(self, runner, cli, in_project):
        result = runner.invoke(cli, ["package", "add", "monitoring", "--no-install"])

        assert result.exit_code == 0, result.output
        assert "monitoring" in _manifest_text(in_project)

    def test_removing_a_depended_on_group_is_refused(self, runner, cli, project_factory, monkeypatch):
        root = project_factory(blueprint="fullstack", name="shop")
        monkeypatch.chdir(root)

        result = runner.invoke(cli, ["package", "remove", "record", "--yes"])

        assert result.exit_code != 0
        assert "required by" in result.output


class TestGenerate:
    def test_lists_the_generators_when_called_bare(self, runner, cli, in_project):
        result = runner.invoke(cli, ["generate"])

        assert result.exit_code == 0
        assert "controller" in result.output
        assert "model" in result.output

    def test_generates_a_service(self, runner, cli, in_project):
        result = runner.invoke(cli, ["generate", "service", "Billing"])

        assert result.exit_code == 0, result.output
        assert (in_project / "app/services/billing_service.py").is_file()

    def test_a_generator_needing_a_database_is_refused_without_one(self, runner, cli, in_project):
        result = runner.invoke(cli, ["generate", "model", "Post"])

        assert result.exit_code != 0
        assert "uses_record" in result.output

    def test_generates_a_model_with_fields(self, runner, cli, project_factory, monkeypatch):
        root = project_factory(blueprint="fullstack", name="shop")
        monkeypatch.chdir(root)

        result = runner.invoke(
            cli,
            ["generate", "model", "Post", "-f", "title:str:unique", "-f", "body:text:null"],
        )

        assert result.exit_code == 0, result.output
        source = (root / "database/models/post.py").read_text()
        assert "class Post(" in source
        assert "unique=True" in source
        assert "null=True" in source

    def test_a_generated_model_is_registered_in_the_package(self, runner, cli, project_factory, monkeypatch):
        root = project_factory(blueprint="fullstack", name="shop")
        monkeypatch.chdir(root)
        runner.invoke(cli, ["generate", "model", "Post", "-f", "title:str"])

        source = (root / "database/models/__init__.py").read_text()
        assert "from database.models.post import Post" in source
        assert source.count("__models__") == 1, "the registry must not be duplicated"

    def test_an_unknown_field_type_lists_the_valid_ones(self, runner, cli, project_factory, monkeypatch):
        root = project_factory(blueprint="fullstack", name="shop")
        monkeypatch.chdir(root)

        result = runner.invoke(cli, ["generate", "model", "Post", "-f", "title:wat"])

        assert result.exit_code != 0
        assert "Valid types" in result.output

    def test_existing_files_are_not_overwritten(self, runner, cli, in_project):
        runner.invoke(cli, ["generate", "service", "Billing"])
        target = in_project / "app/services/billing_service.py"
        target.write_text("# my own code\n")

        result = runner.invoke(cli, ["generate", "service", "Billing"])

        assert result.exit_code == 0
        assert target.read_text() == "# my own code\n"


class TestDoctor:
    def test_reports_findings_and_exits_zero_when_healthy(self, runner, cli, in_project):
        result = runner.invoke(cli, ["doctor"])

        assert "Diagnosis" in result.output
        assert "Python version" in result.output

    def test_json_output_is_machine_readable(self, runner, cli, in_project):
        result = runner.invoke(cli, ["doctor", "--json"])

        payload = json.loads(result.stdout)
        assert isinstance(payload["findings"], list)
        assert all("level" in finding for finding in payload["findings"])

    def test_a_missing_env_file_is_an_error_that_fix_resolves(self, runner, cli, in_project):
        (in_project / ".env").unlink()

        result = runner.invoke(cli, ["doctor", "--json"])
        findings = {f["name"]: f for f in json.loads(result.stdout)["findings"]}
        assert findings[".env"]["level"] == "fail"

        runner.invoke(cli, ["doctor", "--fix"])
        assert (in_project / ".env").is_file()

    def test_it_works_outside_a_project(self, runner, cli, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["doctor"])

        assert "not inside a Sillo project" in result.output


class TestServices:
    def test_lists_the_configured_services(self, runner, cli, in_project):
        result = runner.invoke(cli, ["services", "list"])

        assert result.exit_code == 0
        assert "backend" in result.output
        assert "uvicorn" in result.output

    def test_json_output_describes_each_service(self, runner, cli, in_project):
        result = runner.invoke(cli, ["services", "list", "--json"])

        services = {entry["name"]: entry for entry in json.loads(result.stdout)}
        assert services["backend"]["port"] == 8000

    def test_dev_can_list_without_starting_anything(self, runner, cli, in_project):
        result = runner.invoke(cli, ["dev", "--list"])

        assert result.exit_code == 0
        assert "backend" in result.output

    def test_an_unknown_service_selection_is_rejected(self, runner, cli, in_project):
        result = runner.invoke(cli, ["dev", "--only", "nonsense"])

        assert result.exit_code != 0
        assert "Unknown service" in result.output


class TestAdd:
    def test_lists_the_features_when_called_bare(self, runner, cli, in_project):
        result = runner.invoke(cli, ["add"])

        assert result.exit_code == 0
        assert "auth" in result.output
        assert "inertia" in result.output

    def test_an_unknown_feature_lists_the_valid_ones(self, runner, cli, in_project):
        result = runner.invoke(cli, ["add", "nonsense"])

        assert result.exit_code == 2
        assert "Available" in result.output

    def test_adding_auth_updates_the_manifest(self, runner, cli, in_project):
        result = runner.invoke(cli, ["add", "auth", "--strategy", "jwt", "--no-install"])

        assert result.exit_code == 0, result.output
        manifest = _manifest_text(in_project)
        assert 'strategy = "jwt"' in manifest

    def test_dry_run_leaves_the_project_untouched(self, runner, cli, in_project):
        before = _manifest_text(in_project)
        result = runner.invoke(cli, ["add", "queue", "--dry-run", "--no-install"])

        assert result.exit_code == 0
        assert _manifest_text(in_project) == before


class TestMigrate:
    def test_status_reports_an_uninitialised_project(self, runner, cli, project_factory, monkeypatch):
        root = project_factory(blueprint="fullstack", name="shop")
        monkeypatch.chdir(root)

        result = runner.invoke(cli, ["migrate", "status", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["applied"] == []

    def test_make_with_apply_also_upgrades(self, runner, cli, project_factory, monkeypatch):
        """`migrate make --apply` must write the migration *and* apply it.

        Without --apply the two steps are separate commands, which is a papercut
        every time you change a model.
        """
        import sillo_start.cli.migrate as migrate_cli

        root = project_factory(blueprint="fullstack", name="shop")
        monkeypatch.chdir(root)

        calls = []

        class FakeResult:
            ok = True
            output = "Created models.0002_thing"
            stdout = output

        class FakeBackend:
            def status(self, root, manifest):
                from sillo_start.project.migrations import MigrationStatus
                return MigrationStatus(initialised=True, applied=[], files=[])

            def initialise(self, root, manifest):
                calls.append("initialise"); return FakeResult()

            def make(self, root, manifest, message):
                calls.append(f"make:{message}"); return FakeResult()

            def upgrade(self, root, manifest, *, fake=False):
                calls.append(f"upgrade:fake={fake}"); return FakeResult()

        monkeypatch.setattr(migrate_cli, "get_backend", lambda manifest: FakeBackend())
        monkeypatch.setattr(migrate_cli, "ensure_driver_installed", lambda manifest: None)

        result = runner.invoke(cli, ["migrate", "make", "-m", "thing", "--apply"])

        assert result.exit_code == 0, result.output
        assert calls == ["make:thing", "upgrade:fake=False"]

    def test_make_without_apply_does_not_upgrade(self, runner, cli, project_factory, monkeypatch):
        import sillo_start.cli.migrate as migrate_cli

        root = project_factory(blueprint="fullstack", name="shop")
        monkeypatch.chdir(root)

        calls = []

        class FakeResult:
            ok = True
            output = "Created models.0002_thing"
            stdout = output

        class FakeBackend:
            def status(self, root, manifest):
                from sillo_start.project.migrations import MigrationStatus
                return MigrationStatus(initialised=True, applied=[], files=[])

            def initialise(self, root, manifest):
                calls.append("initialise"); return FakeResult()

            def make(self, root, manifest, message):
                calls.append("make"); return FakeResult()

            def upgrade(self, root, manifest, *, fake=False):
                calls.append("upgrade"); return FakeResult()

        monkeypatch.setattr(migrate_cli, "get_backend", lambda manifest: FakeBackend())
        monkeypatch.setattr(migrate_cli, "ensure_driver_installed", lambda manifest: None)

        result = runner.invoke(cli, ["migrate", "make", "-m", "thing"])

        assert result.exit_code == 0, result.output
        assert calls == ["make"]

    def test_migrating_without_a_database_is_refused(self, runner, cli, in_project):
        result = runner.invoke(cli, ["migrate", "status"])

        assert result.exit_code != 0
        assert "no database" in result.output.lower()
