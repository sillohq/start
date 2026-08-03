"""``sillo-start create-app``, through the command line.

Driven with Typer's runner so argument handling, the error rendering and the
exit codes are exercised the way a user meets them. The fetch is stubbed: what
belongs here is what the command does around it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from sillo_start.cli import build_cli
from sillo_start.exceptions import CommandError

runner = CliRunner()


@pytest.fixture
def cli():
    return build_cli()


@pytest.fixture
def no_fetch(monkeypatch, starter_files):
    """Write the starter's files instead of downloading them.

    Returns the list the calls are recorded into, so a test can assert which
    repository and ref were asked for.
    """
    calls: list[tuple[str, str]] = []

    def fake_fetch(template, destination: Path) -> None:
        calls.append((template.slug, template.ref))
        for relative, content in starter_files.items():
            path = destination / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

    monkeypatch.setattr("sillo_start.project.template.fetch", fake_fetch)
    return calls


class TestCreateApp:
    def test_one_argument_is_the_project_name(
        self, cli, no_fetch, tmp_path, monkeypatch
    ):
        """`create-app myapp` should do the obvious thing rather than ask for a starter."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(cli, ["create-app", "myapp", "--no-git"])

        assert result.exit_code == 0, result.output
        assert no_fetch == [("sillohq/starter", "main")]
        assert 'name = "myapp"' in (tmp_path / "myapp" / "pyproject.toml").read_text()

    def test_two_arguments_name_the_starter_and_the_project(
        self, cli, no_fetch, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            cli, ["create-app", "acme/template", "myapp", "--no-git"]
        )

        assert result.exit_code == 0, result.output
        assert no_fetch == [("acme/template", "main")]

    def test_a_ref_can_be_pinned(self, cli, no_fetch, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        runner.invoke(cli, ["create-app", "acme/template@v2", "myapp", "--no-git"])

        assert no_fetch == [("acme/template", "v2")]

    def test_the_directory_can_be_chosen(self, cli, no_fetch, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        elsewhere = tmp_path / "somewhere" / "else"

        result = runner.invoke(
            cli, ["create-app", "myapp", "--directory", str(elsewhere), "--no-git"]
        )

        assert result.exit_code == 0, result.output
        assert (elsewhere / "pyproject.toml").is_file()

    def test_no_name_is_a_usage_error_with_a_hint(self, cli, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(cli, ["create-app"])

        assert result.exit_code == 2
        assert "create-app myapp" in result.output

    @pytest.mark.parametrize("name", ["9lives", "my app", "import", "my/app"])
    def test_an_unusable_name_is_refused_before_anything_is_fetched(
        self, cli, no_fetch, tmp_path, monkeypatch, name
    ):
        """It becomes a package name and a directory; catching it later means half a project."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(cli, ["create-app", name])

        assert result.exit_code == 2
        assert no_fetch == []

    def test_a_non_empty_directory_is_refused(
        self, cli, no_fetch, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "myapp").mkdir()
        (tmp_path / "myapp" / "mine.txt").write_text("do not overwrite me")

        result = runner.invoke(cli, ["create-app", "myapp"])

        assert result.exit_code == 2
        assert "--force" in result.output
        assert no_fetch == []

    def test_force_allows_it(self, cli, no_fetch, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "myapp").mkdir()
        (tmp_path / "myapp" / "mine.txt").write_text("kept")

        result = runner.invoke(cli, ["create-app", "myapp", "--force", "--no-git"])

        assert result.exit_code == 0, result.output
        assert (tmp_path / "myapp" / "mine.txt").read_text() == "kept"

    def test_a_fetch_failure_is_a_message_not_a_traceback(
        self, cli, tmp_path, monkeypatch
    ):
        def fail(*_a, **_k):
            raise CommandError("Could not find acme/nope.", hint="Check the name.")

        monkeypatch.setattr("sillo_start.project.template.fetch", fail)
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(cli, ["create-app", "acme/nope", "myapp"])

        assert result.exit_code == 1
        assert "Could not find acme/nope." in result.output
        assert "Traceback" not in result.output

    def test_nothing_is_installed_unless_asked(
        self, cli, no_fetch, tmp_path, monkeypatch
    ):
        """Fetching should not spend two minutes resolving dependencies by default."""
        called = []
        monkeypatch.setattr(
            "sillo_start.utils.pkgmanagers.detect_python_manager",
            lambda *a, **k: called.append(True),
        )
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(cli, ["create-app", "myapp", "--no-git"])

        assert result.exit_code == 0, result.output
        assert called == []
        assert "make setup" in result.output

    def test_git_is_initialised_by_default(self, cli, no_fetch, tmp_path, monkeypatch):
        commands: list[list[str]] = []
        monkeypatch.setattr(
            "sillo_start.utils.subprocess.run",
            lambda argv, **kwargs: commands.append(argv),
        )
        monkeypatch.setattr(
            "sillo_start.utils.subprocess.tool_exists", lambda _name: True
        )
        monkeypatch.chdir(tmp_path)

        runner.invoke(cli, ["create-app", "myapp"])

        assert ["git", "init", "--quiet"] in commands


class TestTopLevel:
    def test_the_version_is_reported(self, cli, monkeypatch):
        from sillo_start import __version__
        from sillo_start.utils.console import console

        # The autouse fixture silences the console; --version is the one thing
        # that has to come out, so this test opts back in.
        monkeypatch.setattr(console, "quiet", False)

        result = runner.invoke(cli, ["--version"])

        assert result.exit_code == 0
        assert __version__ in result.output

    def test_bare_invocation_shows_help(self, cli):
        result = runner.invoke(cli, [])

        assert "create-app" in result.output

    def test_create_app_is_the_only_command(self, cli):
        """The tool creates projects. Anything else belongs to the project itself."""
        result = runner.invoke(cli, ["--help"])

        assert "create-app" in result.output
        for gone in ("doctor", "generate", "migrate", "add ", "package"):
            assert gone not in result.output
