"""Shared fixtures.

Every test that touches the filesystem works inside a temporary directory, so
the suite never writes into a real project and tests cannot see each other's
output.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sillo_start.blueprints.registry import registry as blueprint_registry
from sillo_start.config.models import ProjectSection, SilloManifest
from sillo_start.project.creator import ProjectCreator
from sillo_start.project.manifest import ProjectOptions, build_manifest
from sillo_start.utils.console import console


@pytest.fixture(autouse=True)
def _quiet_console():
    """Silence CLI output during tests, restoring it afterwards."""
    previous = console.quiet
    console.quiet = True
    yield
    console.quiet = previous


@pytest.fixture
def manifest() -> SilloManifest:
    """A minimal valid manifest."""
    return SilloManifest(project=ProjectSection(name="testapp"))


@pytest.fixture
def api_manifest() -> SilloManifest:
    """A manifest built from the API blueprint."""
    blueprint = blueprint_registry.get("api")
    return build_manifest(ProjectOptions(name="testapp", blueprint="api"), blueprint)


@pytest.fixture
def fullstack_manifest() -> SilloManifest:
    """A manifest with a database, auth and the admin panel."""
    blueprint = blueprint_registry.get("fullstack")
    return build_manifest(ProjectOptions(name="testapp", blueprint="fullstack"), blueprint)


@pytest.fixture
def project_factory(tmp_path: Path):
    """Build a generated project on disk and return its root.

    Args:
        The returned callable takes a blueprint name and any ProjectOptions
        overrides.
    """

    def build(blueprint: str = "api", name: str = "testapp", **overrides) -> Path:
        blueprint_obj = blueprint_registry.get(blueprint)
        options = ProjectOptions(name=name, blueprint=blueprint, **overrides)
        built = build_manifest(options, blueprint_obj)
        root = tmp_path / name
        ProjectCreator().create(root, built, blueprint_obj, git=False, install=False)
        return root

    return build


@pytest.fixture
def project(project_factory) -> Path:
    """A generated API project."""
    return project_factory()
