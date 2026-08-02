"""Operations, transactions and rollback."""

from __future__ import annotations

from pathlib import Path

import pytest

from sillo_start.exceptions import OperationError, TransactionError
from sillo_start.operations.base import (
    ExecutionContext,
    Operation,
    OperationStatus,
)
from sillo_start.operations.dependencies import UpdateJson, UpdateToml
from sillo_start.operations.files import (
    CreateDirectory,
    CreateFile,
    DeleteFile,
    UpdateEnvironment,
    UpdateMarkerSection,
)
from sillo_start.operations.transaction import ExecutionPlan, execute_plan
from sillo_start.utils.environment import EnvVar


@pytest.fixture
def context(tmp_path: Path) -> ExecutionContext:
    return ExecutionContext(project_root=tmp_path)


class ExplodingOperation(Operation):
    """An operation that always fails, for testing rollback."""

    def describe(self, context):
        return "fail on purpose"

    def apply(self, context):
        raise OperationError("boom")


class TestCreateFile:
    def test_writes_the_file(self, context):
        CreateFile("app/main.py", "print('hi')").apply(context)
        assert (context.project_root / "app/main.py").read_text() == "print('hi')\n"

    def test_leaves_an_existing_file_alone_by_default(self, context):
        target = context.project_root / "keep.py"
        target.write_text("mine\n")

        result = CreateFile("keep.py", "theirs").apply(context)

        assert result.status is OperationStatus.SKIPPED
        assert target.read_text() == "mine\n"

    def test_overwrite_replaces_and_can_be_undone(self, context):
        target = context.project_root / "keep.py"
        target.write_text("mine\n")

        operation = CreateFile("keep.py", "theirs", overwrite=True)
        operation.apply(context)
        assert target.read_text() == "theirs\n"

        operation.rollback(context)
        assert target.read_text() == "mine\n"

    def test_rollback_removes_a_file_it_created(self, context):
        operation = CreateFile("new.py", "x")
        operation.apply(context)
        operation.rollback(context)
        assert not (context.project_root / "new.py").exists()

    def test_identical_content_is_a_no_op(self, context):
        target = context.project_root / "same.py"
        target.write_text("same\n")
        result = CreateFile("same.py", "same", overwrite=True).apply(context)
        assert result.status is OperationStatus.SKIPPED

    def test_refuses_to_overwrite_when_told_not_to_skip(self, context):
        (context.project_root / "x.py").write_text("mine")
        with pytest.raises(OperationError):
            CreateFile("x.py", "theirs", skip_if_exists=False).apply(context)

    def test_dry_run_writes_nothing_but_produces_a_diff(self, tmp_path):
        context = ExecutionContext(project_root=tmp_path, dry_run=True)
        result = CreateFile("app/main.py", "print('hi')").apply(context)

        assert not (tmp_path / "app/main.py").exists()
        assert result.status is OperationStatus.APPLIED
        assert "print" in result.diff


class TestCreateDirectory:
    def test_creates_nested_directories(self, context):
        CreateDirectory("a/b/c").apply(context)
        assert (context.project_root / "a/b/c").is_dir()

    def test_rollback_removes_only_what_it_created(self, context):
        (context.project_root / "a").mkdir()
        operation = CreateDirectory("a/b/c")
        operation.apply(context)
        operation.rollback(context)

        assert (context.project_root / "a").is_dir()
        assert not (context.project_root / "a/b").exists()

    def test_keep_writes_a_gitkeep(self, context):
        CreateDirectory("storage/logs", keep=True).apply(context)
        assert (context.project_root / "storage/logs/.gitkeep").exists()


class TestDeleteFile:
    def test_removes_and_restores(self, context):
        target = context.project_root / "gone.py"
        target.write_text("content\n")

        operation = DeleteFile("gone.py")
        operation.apply(context)
        assert not target.exists()

        operation.rollback(context)
        assert target.read_text() == "content\n"


class TestUpdateToml:
    def test_appends_to_an_array_without_duplicating(self, context):
        pyproject = context.project_root / "pyproject.toml"
        pyproject.write_text('[project]\ndependencies = ["a>=1"]\n')

        UpdateToml("pyproject.toml", append={"project.dependencies": ["b>=2", "a>=1"]}).apply(context)

        contents = pyproject.read_text()
        assert "b>=2" in contents
        assert contents.count("a>=1") == 1

    def test_removes_by_distribution_name_ignoring_the_version(self, context):
        pyproject = context.project_root / "pyproject.toml"
        pyproject.write_text('[project]\ndependencies = ["redis>=5.0.0", "keep>=1"]\n')

        UpdateToml("pyproject.toml", remove={"project.dependencies": ["redis"]}).apply(context)

        contents = pyproject.read_text()
        assert "redis" not in contents
        assert "keep" in contents

    def test_preserves_comments(self, context):
        pyproject = context.project_root / "pyproject.toml"
        pyproject.write_text('# keep me\n[project]\nname = "x"\ndependencies = []\n')

        UpdateToml("pyproject.toml", append={"project.dependencies": ["a"]}).apply(context)

        assert "# keep me" in pyproject.read_text()

    def test_rollback_restores_the_previous_contents(self, context):
        pyproject = context.project_root / "pyproject.toml"
        original = '[project]\ndependencies = []\n'
        pyproject.write_text(original)

        operation = UpdateToml("pyproject.toml", append={"project.dependencies": ["a"]})
        operation.apply(context)
        operation.rollback(context)

        assert pyproject.read_text() == original


class TestUpdateJson:
    def test_merges_nested_keys_without_dropping_siblings(self, context):
        package_json = context.project_root / "package.json"
        package_json.write_text('{"scripts": {"dev": "vite"}, "name": "app"}')

        UpdateJson("package.json", {"scripts": {"build": "vite build"}}).apply(context)

        import json

        data = json.loads(package_json.read_text())
        assert data["scripts"] == {"dev": "vite", "build": "vite build"}
        assert data["name"] == "app"


class TestUpdateMarkerSection:
    def test_creates_the_block_when_absent(self, context):
        target = context.project_root / "models.py"
        target.write_text("# header\n")

        UpdateMarkerSection("models.py", "models", "X = 1").apply(context)

        contents = target.read_text()
        assert "# header" in contents
        assert "sillo-start: models" in contents
        assert "X = 1" in contents

    def test_replaces_only_the_block(self, context):
        target = context.project_root / "models.py"
        UpdateMarkerSection("models.py", "models", "first").apply(context)
        target.write_text(target.read_text() + "\n# a human wrote this\n")

        UpdateMarkerSection("models.py", "models", "second").apply(context)

        contents = target.read_text()
        assert "second" in contents
        assert "first" not in contents
        assert "# a human wrote this" in contents


class TestUpdateEnvironment:
    def test_adds_missing_variables(self, context):
        UpdateEnvironment(".env", [EnvVar("KEY", "value")]).apply(context)
        assert "KEY=value" in (context.project_root / ".env").read_text()

    def test_never_overwrites_an_existing_value(self, context):
        env = context.project_root / ".env"
        env.write_text("SECRET=the-real-one\n")

        UpdateEnvironment(".env", [EnvVar("SECRET", "placeholder")]).apply(context)

        assert "the-real-one" in env.read_text()
        assert "placeholder" not in env.read_text()

    def test_is_a_no_op_when_everything_is_present(self, context):
        env = context.project_root / ".env"
        env.write_text("A=1\n")
        result = UpdateEnvironment(".env", [EnvVar("A", "2")]).apply(context)
        assert result.status is OperationStatus.SKIPPED


class TestTransaction:
    def test_applies_every_operation(self, context):
        plan = ExecutionPlan("test").add(
            CreateFile("a.py", "a"),
            CreateFile("b.py", "b"),
        )
        report = execute_plan(plan, context, show_progress=False)

        assert report.changed_count == 2
        assert (context.project_root / "a.py").exists()

    def test_a_failure_rolls_back_everything_applied(self, context):
        plan = ExecutionPlan("test").add(
            CreateFile("a.py", "a"),
            CreateFile("b.py", "b"),
            ExplodingOperation(),
        )

        with pytest.raises(TransactionError):
            execute_plan(plan, context, show_progress=False)

        assert not (context.project_root / "a.py").exists()
        assert not (context.project_root / "b.py").exists()

    def test_rollback_restores_edited_files_rather_than_deleting_them(self, context):
        keep = context.project_root / "keep.py"
        keep.write_text("original\n")

        plan = ExecutionPlan("test").add(
            CreateFile("keep.py", "changed", overwrite=True),
            ExplodingOperation(),
        )
        with pytest.raises(TransactionError):
            execute_plan(plan, context, show_progress=False)

        assert keep.read_text() == "original\n"

    def test_the_original_error_is_preserved_as_the_cause(self, context):
        plan = ExecutionPlan("test").add(ExplodingOperation())
        with pytest.raises(TransactionError) as error:
            execute_plan(plan, context, show_progress=False)
        assert isinstance(error.value.__cause__, OperationError)

    def test_a_plan_reports_which_steps_are_irreversible(self, context):
        from sillo_start.operations.commands import RunCommand

        plan = ExecutionPlan("test").add(
            CreateFile("a.py", "a"),
            RunCommand(["echo", "hi"]),
        )
        assert len(plan.irreversible) == 1
