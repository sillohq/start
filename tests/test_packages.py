"""Package group registry, resolution and installation planning."""

from __future__ import annotations

import pytest

from sillo_start.exceptions import DependencyResolutionError, PackageGroupError
from sillo_start.packages.installer import sillo_requirement
from sillo_start.packages.registry import PackageGroup, PackageRegistry
from sillo_start.packages.registry import registry as global_registry
from sillo_start.packages.resolver import dependents_of, resolve, validate_selection


@pytest.fixture
def isolated_registry() -> PackageRegistry:
    """A registry with a small, predictable set of groups."""
    registry = PackageRegistry()
    registry.register(PackageGroup(name="base", summary="Base."))
    registry.register(PackageGroup(name="db", summary="Database.", requires=("base",)))
    registry.register(PackageGroup(name="auth", summary="Auth.", requires=("db",)))
    registry.register(PackageGroup(name="admin", summary="Admin.", requires=("auth",)))
    registry.register(PackageGroup(name="sqlite", summary="SQLite.", conflicts=("postgres",)))
    registry.register(PackageGroup(name="postgres", summary="Postgres.", conflicts=("sqlite",)))
    return registry


class TestRegistry:
    def test_built_in_groups_are_registered(self):
        for name in ("api", "record", "auth", "admin", "inertia", "work", "testing"):
            assert global_registry.has(name)

    def test_an_unknown_group_lists_the_valid_ones(self):
        with pytest.raises(PackageGroupError) as error:
            global_registry.get("nonsense")
        assert "record" in str(error.value.hint)

    def test_registering_a_duplicate_name_is_rejected(self, isolated_registry):
        with pytest.raises(PackageGroupError):
            isolated_registry.register(PackageGroup(name="base", summary="Again."))

    def test_replacing_a_group_is_allowed_explicitly(self, isolated_registry):
        isolated_registry.register(PackageGroup(name="base", summary="New."), replace=True)
        assert isolated_registry.get("base").summary == "New."


class TestResolution:
    def test_dependencies_come_before_their_dependents(self, isolated_registry):
        resolution = resolve(["admin"], registry=isolated_registry)
        assert resolution.names == ["base", "db", "auth", "admin"]

    def test_transitive_dependencies_are_reported_as_implied(self, isolated_registry):
        resolution = resolve(["admin"], registry=isolated_registry)
        assert set(resolution.implied) == {"base", "db", "auth"}

    def test_already_installed_groups_are_not_reinstalled(self, isolated_registry):
        resolution = resolve(["admin"], installed=["base", "db"], registry=isolated_registry)
        assert resolution.names == ["auth", "admin"]

    def test_include_installed_returns_everything(self, isolated_registry):
        resolution = resolve(
            ["admin"], installed=["base"], registry=isolated_registry, include_installed=True
        )
        assert resolution.names == ["base", "db", "auth", "admin"]

    def test_conflicting_groups_are_rejected(self, isolated_registry):
        with pytest.raises(DependencyResolutionError) as error:
            resolve(["sqlite", "postgres"], registry=isolated_registry)
        assert "conflicts" in str(error.value)

    def test_a_conflict_with_an_installed_group_is_rejected(self, isolated_registry):
        with pytest.raises(DependencyResolutionError):
            resolve(["postgres"], installed=["sqlite"], registry=isolated_registry)

    def test_a_dependency_cycle_is_reported_rather_than_hanging(self):
        registry = PackageRegistry()
        registry.register(PackageGroup(name="a", summary="A.", requires=("b",)))
        registry.register(PackageGroup(name="b", summary="B.", requires=("a",)))

        with pytest.raises(DependencyResolutionError) as error:
            resolve(["a"], registry=registry)
        assert "cycle" in str(error.value).lower()

    def test_resolution_is_idempotent_for_repeated_requests(self, isolated_registry):
        resolution = resolve(["db", "db", "auth"], registry=isolated_registry)
        assert resolution.names == ["base", "db", "auth"]

    def test_validate_selection_reports_every_unknown_name_at_once(self):
        with pytest.raises(DependencyResolutionError) as error:
            validate_selection(["record", "nope", "alsonope"])
        message = str(error.value)
        assert "nope" in message and "alsonope" in message


class TestAggregation:
    def test_extras_are_collected_across_groups(self):
        resolution = resolve(["admin"], include_installed=True)
        extras = resolution.sillo_extras()
        # admin implies auth implies record.
        assert {"record", "jwt", "templating"} <= set(extras)

    def test_python_packages_are_deduplicated(self):
        resolution = resolve(["record", "admin"], include_installed=True)
        packages = resolution.python_packages()
        assert len(packages) == len(set(packages))

    def test_directories_are_deduplicated_and_ordered(self):
        resolution = resolve(["record", "auth"], include_installed=True)
        directories = resolution.directories()
        assert len(directories) == len(set(directories))


class TestDependents:
    def test_reports_installed_groups_that_need_a_group(self):
        assert dependents_of("record", installed=["record", "auth", "admin"]) == ["admin", "auth"]

    def test_reports_nothing_for_a_leaf_group(self):
        assert dependents_of("admin", installed=["record", "auth", "admin"]) == []


class TestRequirementBuilding:
    def test_extras_are_sorted_and_deduplicated(self):
        requirement = sillo_requirement(["record", "jwt", "record"], ">=0.1")
        assert requirement == "sillo-framework[jwt,record]>=0.1"

    def test_no_extras_gives_a_plain_requirement(self):
        assert sillo_requirement([], ">=0.1") == "sillo-framework>=0.1"


class TestCompatibility:
    def test_a_group_needing_a_database_is_rejected_without_one(self, manifest):
        group = global_registry.get("auth")
        compatible, reason = group.compatible_with(manifest)
        assert compatible is False
        assert "database" in reason

    def test_the_same_group_is_accepted_with_a_database(self, manifest):
        manifest.database.enabled = True
        group = global_registry.get("auth")
        compatible, _ = group.compatible_with(manifest)
        assert compatible is True
