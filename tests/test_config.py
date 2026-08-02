"""Manifest models, loading and writing."""

from __future__ import annotations

import pytest

from sillo_start.config.defaults import ORM, AuthStrategy, DatabaseDriver
from sillo_start.config.loader import find_manifest, load_manifest, load_project
from sillo_start.config.models import ProjectSection
from sillo_start.config.writer import render_manifest, save_manifest
from sillo_start.exceptions import ManifestError, ManifestNotFoundError


class TestProjectSection:
    def test_derives_the_package_name_from_the_project_name(self):
        section = ProjectSection(name="my-cool-app")
        assert section.package == "my_cool_app"

    def test_keeps_an_explicit_package_name(self):
        section = ProjectSection(name="my-cool-app", package="custom")
        assert section.package == "custom"

    @pytest.mark.parametrize("name", ["", "1app", "my app", "class", "-leading"])
    def test_rejects_unusable_names(self, name):
        with pytest.raises(ValueError):
            ProjectSection(name=name)

    @pytest.mark.parametrize("name", ["app", "my-app", "my_app", "App2"])
    def test_accepts_usable_names(self, name):
        assert ProjectSection(name=name).name == name


class TestCoherence:
    def test_disabling_the_database_clears_the_driver(self, manifest):
        manifest.database.enabled = True
        manifest.database.driver = DatabaseDriver.POSTGRES
        manifest.database.enabled = False
        assert manifest.database.driver == DatabaseDriver.NONE

    def test_enabling_the_database_without_a_driver_defaults_to_sqlite(self, manifest):
        manifest.database.enabled = True
        assert manifest.database.driver == DatabaseDriver.SQLITE

    def test_enabling_auth_without_a_strategy_defaults_to_session(self, manifest):
        manifest.auth.enabled = True
        assert manifest.auth.strategy == AuthStrategy.SESSION

    def test_auth_switches_survive_being_enabled_after_construction(self, manifest):
        """Regression: flipping `enabled` must not clear the sub-switches.

        Blueprints and feature implications turn auth on after the section is
        built, and a validator that zeroed the switches on the first pass left
        the project with no auth routes at all.
        """
        assert manifest.auth.enabled is False
        manifest.auth.enabled = True
        assert manifest.auth.routes is True
        assert manifest.auth.registration is True

    def test_the_admin_prefix_is_normalised(self, manifest):
        manifest.admin.prefix = "admin/"
        assert manifest.admin.prefix == "/admin"


class TestDerivedProperties:
    def test_uses_record_requires_both_a_database_and_the_orm(self, manifest):
        assert manifest.uses_record is False
        manifest.database.enabled = True
        manifest.database.orm = ORM.RECORD
        assert manifest.uses_record is True

    def test_needs_redis_when_any_feature_uses_it(self, manifest):
        assert manifest.needs_redis is False
        manifest.queue.enabled = True
        manifest.queue.driver = "redis"
        assert manifest.needs_redis is True

    def test_needs_web_routes_for_inertia_or_a_non_api_project(self, manifest):
        manifest.api.enabled = True
        assert manifest.needs_web_routes is False
        manifest.inertia.enabled = True
        assert manifest.needs_web_routes is True

    def test_package_groups_are_deduplicated_and_ordered(self, manifest):
        assert manifest.add_group("record") is True
        assert manifest.add_group("record") is False
        manifest.add_group("auth")
        assert manifest.packages.groups == ["record", "auth"]
        assert manifest.remove_group("record") is True
        assert manifest.packages.groups == ["auth"]


class TestSerialisation:
    def test_a_rendered_manifest_round_trips(self, fullstack_manifest, tmp_path):
        path = tmp_path / "sillo.toml"
        save_manifest(path, fullstack_manifest)
        reloaded = load_manifest(path)

        assert reloaded.project.name == fullstack_manifest.project.name
        assert reloaded.database.driver == fullstack_manifest.database.driver
        assert reloaded.auth.strategy == fullstack_manifest.auth.strategy
        assert reloaded.packages.groups == fullstack_manifest.packages.groups

    def test_disabled_sections_are_omitted_from_a_new_manifest(self, manifest):
        """A minimal project should get a manifest that is actually minimal."""
        rendered = render_manifest(manifest)
        assert "[inertia]" not in rendered
        assert "[queue]" not in rendered
        assert "[project]" in rendered

    def test_saving_preserves_comments_a_developer_added(self, manifest, tmp_path):
        path = tmp_path / "sillo.toml"
        save_manifest(path, manifest)
        path.write_text(path.read_text() + "\n# a note from a human\n")

        manifest.project.version = "0.2.0"
        save_manifest(path, manifest)

        contents = path.read_text()
        assert "# a note from a human" in contents
        assert '0.2.0' in contents

    def test_unknown_sections_survive_a_round_trip(self, tmp_path):
        """A plugin's section must not be dropped by an older tool."""
        path = tmp_path / "sillo.toml"
        path.write_text(
            '[project]\nname = "app"\n\n[search]\nengine = "meili"\n',
            encoding="utf-8",
        )
        loaded = load_manifest(path)
        save_manifest(path, loaded)
        assert "meili" in path.read_text()


class TestDiscovery:
    def test_finds_the_manifest_in_a_parent_directory(self, tmp_path):
        (tmp_path / "sillo.toml").write_text('[project]\nname = "app"\n')
        nested = tmp_path / "app" / "http"
        nested.mkdir(parents=True)

        assert find_manifest(nested) == tmp_path / "sillo.toml"

    def test_returns_none_outside_a_project(self, tmp_path):
        assert find_manifest(tmp_path) is None

    def test_load_project_reports_a_missing_manifest_clearly(self, tmp_path):
        with pytest.raises(ManifestNotFoundError):
            load_project(tmp_path)

    def test_an_invalid_manifest_names_the_offending_field(self, tmp_path):
        path = tmp_path / "sillo.toml"
        path.write_text('[project]\nname = "1invalid"\n')

        with pytest.raises(ManifestError) as error:
            load_manifest(path)
        assert "project.name" in str(error.value)
