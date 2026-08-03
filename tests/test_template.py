"""Fetching a starter repository and making it someone's project.

The network is stubbed at ``urlopen``: what matters here is what the tool does
with an archive, not that GitHub serves one.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path

import pytest

from sillo_start.exceptions import CommandError
from sillo_start.project.template import (
    DEFAULT_TEMPLATE,
    Template,
    fetch,
    generate_secret_key,
    personalise,
)


class _Response:
    """The context-manager shape ``urlopen`` returns."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exc) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


class TestParse:
    def test_owner_and_repo(self):
        template = Template.parse("sillohq/starter")

        assert (template.owner, template.repo, template.ref) == (
            "sillohq",
            "starter",
            "main",
        )

    def test_a_ref_after_an_at_sign(self):
        assert Template.parse("sillohq/starter@v1.2").ref == "v1.2"

    def test_an_explicit_ref_wins(self):
        """--ref is the later, more specific instruction."""
        assert Template.parse("sillohq/starter@v1.2", ref="develop").ref == "develop"

    @pytest.mark.parametrize(
        "value",
        [
            "https://github.com/sillohq/starter",
            "http://www.github.com/sillohq/starter",
            "github.com/sillohq/starter.git",
            "sillohq/starter/",
        ],
    )
    def test_urls_and_suffixes_are_accepted(self, value):
        """People paste what is in their address bar."""
        assert Template.parse(value).slug == "sillohq/starter"

    @pytest.mark.parametrize("value", ["starter", "a/b/c", "", "   "])
    def test_anything_else_is_refused_with_a_hint(self, value):
        with pytest.raises(CommandError) as caught:
            Template.parse(value)

        assert "owner/repo" in (caught.value.hint or "")

    def test_the_url_is_the_tarball_not_the_repository_page(self):
        """Fetching an archive needs no git on the machine."""
        assert Template.parse("sillohq/starter@v1").url == (
            "https://codeload.github.com/sillohq/starter/tar.gz/v1"
        )


class TestFetch:
    def test_the_top_level_directory_is_stripped(self, tmp_path, tarball, monkeypatch):
        """GitHub wraps everything in <repo>-<ref>/; the project's files belong at the root."""
        monkeypatch.setattr(
            urllib.request, "urlopen", lambda *a, **k: _Response(tarball())
        )
        root = tmp_path / "myapp"

        fetch(Template.parse("sillohq/starter"), root)

        assert (root / "pyproject.toml").is_file()
        assert (root / "app" / "config.py").is_file()
        assert not (root / "starter-main").exists()

    def test_a_path_escaping_the_destination_is_refused(
        self, tmp_path, tarball, monkeypatch
    ):
        """An archive that writes outside its target is how it overwrites your files."""
        payload = tarball(extra={"../escaped.txt": "no"})
        monkeypatch.setattr(
            urllib.request, "urlopen", lambda *a, **k: _Response(payload)
        )

        with pytest.raises(CommandError, match="unsafe path"):
            fetch(Template.parse("sillohq/starter"), tmp_path / "myapp")

        assert not (tmp_path / "escaped.txt").exists()

    def test_a_missing_repository_says_which_ref(self, tmp_path, monkeypatch):
        def raise_404(*_a, **_k):
            raise urllib.error.HTTPError("url", 404, "Not Found", {}, None)

        monkeypatch.setattr(urllib.request, "urlopen", raise_404)

        with pytest.raises(CommandError) as caught:
            fetch(Template.parse("sillohq/nope@v9"), tmp_path / "myapp")

        assert "sillohq/nope" in caught.value.message and "v9" in caught.value.message

    def test_no_network_is_reported_as_no_network(self, tmp_path, monkeypatch):
        """Not as a missing repository, which is what people would go and check."""

        def raise_urlerror(*_a, **_k):
            raise urllib.error.URLError("nodename nor servname provided")

        monkeypatch.setattr(urllib.request, "urlopen", raise_urlerror)

        with pytest.raises(CommandError) as caught:
            fetch(Template.parse("sillohq/starter"), tmp_path / "myapp")

        assert "reach GitHub" in caught.value.message


class TestPersonalise:
    def test_the_project_takes_its_new_name(self, unpacked: Path):
        personalise(unpacked, "myapp")

        assert 'name = "myapp"' in (unpacked / "pyproject.toml").read_text()
        assert 'app_name: str = "Myapp"' in (unpacked / "app" / "config.py").read_text()
        assert "APP_NAME=Myapp" in (unpacked / ".env.example").read_text()
        assert "sqlite://storage/myapp.db" in (unpacked / ".env.example").read_text()

    def test_prose_is_left_alone(self, unpacked: Path):
        """A blanket find-and-replace would rewrite the README's sentences too."""
        personalise(unpacked, "myapp")

        assert "starter" in (unpacked / "README.md").read_text()

    def test_the_lock_file_follows_the_rename(self, unpacked: Path):
        """It names the project as a member of its own workspace; `uv sync` fails if they disagree."""
        personalise(unpacked, "myapp")

        assert 'name = "myapp"' in (unpacked / "uv.lock").read_text()

    def test_the_files_it_changed_are_reported(self, unpacked: Path):
        changed = personalise(unpacked, "myapp")

        assert set(changed) >= {
            "pyproject.toml",
            "app/config.py",
            ".env.example",
            "uv.lock",
        }

    def test_an_env_is_written_with_a_real_secret(self, unpacked: Path):
        """The starter's placeholder must not survive into a project someone deploys."""
        personalise(unpacked, "myapp")

        env = (unpacked / ".env").read_text()
        assert "generate-me" not in env
        assert len(_value(env, "SECRET_KEY")) > 40
        assert "APP_NAME=Myapp" in env

    def test_an_existing_env_is_never_replaced(self, unpacked: Path):
        """It may hold real credentials."""
        (unpacked / ".env").write_text("SECRET_KEY=mine\n")

        changed = personalise(unpacked, "myapp")

        assert (unpacked / ".env").read_text() == "SECRET_KEY=mine\n"
        assert ".env" not in changed

    def test_a_missing_file_is_skipped_rather_than_failing(self, unpacked: Path):
        """A starter need not have every file the rename rules know about."""
        (unpacked / "app" / "config.py").unlink()

        assert "app/config.py" not in personalise(unpacked, "myapp")


class TestSecretKey:
    def test_two_calls_differ(self):
        assert generate_secret_key() != generate_secret_key()

    def test_the_length_is_respected(self):
        assert len(generate_secret_key(32)) == 32


def test_the_default_starter_is_the_published_one():
    assert DEFAULT_TEMPLATE == "sillohq/starter"


def _value(env: str, key: str) -> str:
    """Read one variable out of an env file's text."""
    for line in env.splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() == key:
            return value
    raise AssertionError(f"{key} is not in the env file")
