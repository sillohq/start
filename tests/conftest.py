"""Shared fixtures.

Every test that touches the filesystem works inside a temporary directory, so
the suite never writes into a real project and tests cannot see each other's
output.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from sillo_start.utils.console import console


@pytest.fixture(autouse=True)
def _quiet_console():
    """Silence CLI output during tests, restoring it afterwards."""
    previous = console.quiet
    console.quiet = True
    yield
    console.quiet = previous


@pytest.fixture
def starter_files() -> dict[str, str]:
    """The parts of a starter repository that personalisation touches."""
    return {
        "pyproject.toml": '[project]\nname = "starter"\nversion = "0.1.0"\n',
        "app/config.py": (
            '"""Typed settings for Starter."""\n\n'
            'app_name: str = "Starter"\n'
            'database_url: str = "sqlite://storage/starter.db"\n'
        ),
        ".env.example": (
            "# Starter environment.\n"
            "APP_NAME=Starter\n"
            "SECRET_KEY=generate-me\n"
            "DATABASE_URL=sqlite://storage/starter.db\n"
        ),
        "uv.lock": 'version = 1\n\n[[package]]\nname = "starter"\n',
        "README.md": "# Sillo Starter\n\nProse mentioning starter is left alone.\n",
    }


@pytest.fixture
def unpacked(tmp_path: Path, starter_files: dict[str, str]) -> Path:
    """A starter already on disk, as :func:`fetch` would have left it."""
    root = tmp_path / "myapp"
    for relative, content in starter_files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return root


@pytest.fixture
def tarball(starter_files: dict[str, str]):
    """Build a GitHub-shaped tarball: everything under one top-level directory.

    The returned callable takes extra members as ``{path: content}``, so a test
    can add a path the extractor is expected to refuse.
    """

    def build(
        extra: dict[str, str] | None = None, prefix: str = "starter-main"
    ) -> bytes:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            for relative, content in {**starter_files, **(extra or {})}.items():
                payload = content.encode()
                info = tarfile.TarInfo(f"{prefix}/{relative}")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
        return buffer.getvalue()

    return build
