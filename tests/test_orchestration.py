"""Service definitions, the supervisor and process management.

These tests never start a real server. Services are defined as short-lived
shell commands so process lifecycle can be exercised deterministically without
binding ports or waiting on network I/O.
"""

from __future__ import annotations

import sys
import time

import pytest

from sillo_start.blueprints.registry import registry as blueprint_registry
from sillo_start.exceptions import UsageError
from sillo_start.orchestration.health import HttpCheck, PortCheck
from sillo_start.orchestration.process import ManagedProcess, ProcessState
from sillo_start.orchestration.services import (
    ServiceDefinition,
    ServiceRegistry,
    build_registry,
)
from sillo_start.orchestration.supervisor import ProcessSupervisor
from sillo_start.project.manifest import ProjectOptions, build_manifest
from sillo_start.utils.ports import find_free_port, is_port_free


def python_service(name: str, script: str, **kwargs) -> ServiceDefinition:
    """Build a service that runs a short Python snippet."""
    return ServiceDefinition(
        name=name,
        command=f'{sys.executable} -c "{script}"',
        **kwargs,
    )


class TestServiceDefinition:
    def test_splits_the_command_respecting_quotes(self):
        service = ServiceDefinition(name="x", command='python -c "print(1)"')
        assert service.argv() == ["python", "-c", "print(1)"]

    def test_an_unparsable_command_is_rejected_with_context(self):
        service = ServiceDefinition(name="x", command='python -c "unterminated')
        with pytest.raises(UsageError) as error:
            service.argv()
        assert "x" in str(error.value)

    def test_an_empty_command_is_rejected(self):
        with pytest.raises(UsageError):
            ServiceDefinition(name="x", command="   ").argv()

    def test_the_working_directory_resolves_against_the_project(self, tmp_path):
        service = ServiceDefinition(name="x", command="true", cwd="frontend")
        assert service.working_directory(tmp_path) == (tmp_path / "frontend").resolve()


class TestServiceRegistry:
    @pytest.fixture
    def registry(self) -> ServiceRegistry:
        registry = ServiceRegistry()
        registry.register(ServiceDefinition(name="backend", command="true"))
        registry.register(ServiceDefinition(name="worker", command="true", depends_on=("backend",)))
        registry.register(ServiceDefinition(name="frontend", command="true"))
        return registry

    def test_dependencies_are_ordered_first(self, registry):
        names = [service.name for service in registry.all()]
        assert names.index("backend") < names.index("worker")

    def test_only_pulls_in_dependencies(self, registry):
        selected = [s.name for s in registry.select(only=["worker"])]
        assert set(selected) == {"backend", "worker"}

    def test_without_excludes_a_service(self, registry):
        selected = [s.name for s in registry.select(without=["frontend"])]
        assert "frontend" not in selected

    def test_an_unknown_selection_is_rejected(self, registry):
        with pytest.raises(UsageError):
            registry.select(only=["nonsense"])

    def test_a_dependency_cycle_does_not_hang(self):
        registry = ServiceRegistry()
        registry.register(ServiceDefinition(name="a", command="true", depends_on=("b",)))
        registry.register(ServiceDefinition(name="b", command="true", depends_on=("a",)))

        assert len(registry.all()) == 2


class TestRegistryFromManifest:
    def test_a_plain_api_project_defines_only_a_backend(self, api_manifest):
        registry = build_registry(api_manifest)
        assert registry.names() == ["backend"]

    def test_an_inertia_project_adds_a_frontend_service(self):
        blueprint = blueprint_registry.get("inertia-react")
        manifest = build_manifest(ProjectOptions(name="site", blueprint="inertia-react"), blueprint)

        registry = build_registry(manifest)

        assert "frontend" in registry.names()
        assert registry.get("frontend").cwd == "frontend"
        assert registry.get("frontend").port == 5173

    def test_a_worker_project_adds_worker_and_scheduler(self):
        blueprint = blueprint_registry.get("worker")
        manifest = build_manifest(ProjectOptions(name="jobs", blueprint="worker"), blueprint)

        names = build_registry(manifest).names()

        assert "worker" in names
        assert "scheduler" in names

    def test_custom_services_from_the_manifest_are_included(self, api_manifest):
        api_manifest.development.extra_services = {"tunnel": "ngrok http 8000"}
        registry = build_registry(api_manifest)

        assert "tunnel" in registry.names()


class TestHealthChecks:
    def test_a_port_check_fails_when_nothing_listens(self):
        port = find_free_port(45000)
        assert PortCheck(port=port).check() is False

    def test_an_http_check_fails_when_nothing_answers(self):
        port = find_free_port(45100)
        assert HttpCheck(url=f"http://127.0.0.1:{port}/").check() is False

    def test_checks_describe_what_they_probe(self):
        assert "8000" in PortCheck(port=8000).describe()
        assert "http" in HttpCheck(url="http://localhost:1/").describe()


class TestManagedProcess:
    @pytest.fixture
    def multiplexer(self):
        from sillo_start.orchestration.logging import LogMultiplexer

        return LogMultiplexer()

    def test_runs_to_completion_and_reports_stopped(self, tmp_path, multiplexer):
        process = ManagedProcess(
            definition=python_service("quick", "print('done')"),
            project_root=tmp_path,
            multiplexer=multiplexer,
        )
        process.start()
        for _ in range(100):
            if process.poll() is not ProcessState.RUNNING:
                break
            time.sleep(0.05)

        assert process.state is ProcessState.STOPPED
        assert process.exit_code == 0

    def test_a_non_zero_exit_is_reported_as_a_crash(self, tmp_path, multiplexer):
        process = ManagedProcess(
            definition=python_service("bad", "import sys; sys.exit(3)"),
            project_root=tmp_path,
            multiplexer=multiplexer,
        )
        process.start()
        for _ in range(100):
            if process.poll() is not ProcessState.RUNNING:
                break
            time.sleep(0.05)

        assert process.state is ProcessState.CRASHED
        assert process.exit_code == 3

    def test_a_missing_executable_fails_without_raising(self, tmp_path, multiplexer):
        process = ManagedProcess(
            definition=ServiceDefinition(name="ghost", command="definitely-not-a-real-binary"),
            project_root=tmp_path,
            multiplexer=multiplexer,
        )
        process.start()

        assert process.state is ProcessState.FAILED

    def test_a_long_running_process_can_be_stopped(self, tmp_path, multiplexer):
        process = ManagedProcess(
            definition=python_service("sleeper", "import time; time.sleep(30)"),
            project_root=tmp_path,
            multiplexer=multiplexer,
        )
        process.start()
        assert process.alive

        process.stop(grace=2.0)

        assert process.state is ProcessState.STOPPED
        assert not process.alive

    def test_restarting_is_abandoned_after_repeated_crashes(self, tmp_path, multiplexer):
        """A service crashing in a loop is misconfigured, not flaky."""
        process = ManagedProcess(
            definition=python_service("flaky", "import sys; sys.exit(1)"),
            project_root=tmp_path,
            multiplexer=multiplexer,
        )
        allowed = sum(1 for _ in range(10) if process.should_restart())

        assert allowed == 3
        assert process.state is ProcessState.FAILED

    def test_a_service_marked_no_restart_is_not_restarted(self, tmp_path, multiplexer):
        process = ManagedProcess(
            definition=python_service("once", "import sys; sys.exit(1)", restart=False),
            project_root=tmp_path,
            multiplexer=multiplexer,
        )
        assert process.should_restart() is False


class TestSupervisor:
    def test_reports_a_port_conflict_before_starting_anything(self, tmp_path):
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
            held.bind(("127.0.0.1", 0))
            held.listen(1)
            taken = held.getsockname()[1]

            supervisor = ProcessSupervisor(project_root=tmp_path)
            supervisor.add(python_service("api", "import time; time.sleep(5)", port=taken))

            conflicts = supervisor.check_ports()
            assert conflicts and str(taken) in conflicts[0]

            with pytest.raises(UsageError):
                supervisor.start_all(wait_for_health=False)

    def test_starts_and_stops_every_service(self, tmp_path):
        supervisor = ProcessSupervisor(project_root=tmp_path)
        supervisor.add(python_service("a", "import time; time.sleep(30)"))
        supervisor.add(python_service("b", "import time; time.sleep(30)"))

        supervisor.start_all(wait_for_health=False)
        assert all(process.alive for process in supervisor.processes.values())

        supervisor.stop_all()
        assert not any(process.alive for process in supervisor.processes.values())

    def test_status_describes_each_service(self, tmp_path):
        supervisor = ProcessSupervisor(project_root=tmp_path)
        supervisor.add(python_service("a", "import time; time.sleep(30)"))
        supervisor.start_all(wait_for_health=False)

        try:
            rows = supervisor.status()
            assert rows[0]["name"] == "a"
            assert rows[0]["state"] == "running"
            assert rows[0]["pid"]
        finally:
            supervisor.stop_all()

    def test_stopping_a_process_group_kills_its_children(self, tmp_path):
        """A reloading server spawns children; leaving them behind holds ports."""
        script = (
            "import subprocess, sys, time; "
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
            "time.sleep(30)"
        )
        supervisor = ProcessSupervisor(project_root=tmp_path)
        supervisor.add(python_service("parent", script))
        supervisor.start_all(wait_for_health=False)
        time.sleep(0.5)

        supervisor.stop_all()

        assert not any(process.alive for process in supervisor.processes.values())


class TestPorts:
    def test_find_free_port_returns_a_bindable_port(self):
        port = find_free_port(46000)
        assert is_port_free(port)

    def test_a_bound_port_is_reported_as_taken(self):
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
            held.bind(("127.0.0.1", 0))
            held.listen(1)
            assert is_port_free(held.getsockname()[1]) is False
