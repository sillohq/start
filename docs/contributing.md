# Contributing

```bash
git clone https://github.com/sillohq/start
cd start
uv sync --extra dev
uv run pytest
```

The dev environment installs `sillo-framework` and `sillo-inertia` from the
sibling `../core` and `../inertia` checkouts, because the integration suite
executes generated projects against the real framework.

## Running the tests

```bash
uv run pytest                          # everything
uv run pytest tests/test_config.py     # one module
uv run pytest -k "rollback"            # by name
uv run pytest --cov=sillo_start        # with coverage
```

The suite has three layers:

- **Unit tests** for pure logic — manifest coherence, dependency resolution,
  field parsing, naming.
- **CLI tests** through Typer's runner, asserting on exit codes and output.
- **Integration tests** that generate projects and run them in a subprocess
  against the real framework.

The integration layer skips itself when `sillo` is not importable, so the suite
still runs in a bare environment.

## Adding to the generated code

Changing a template means changing code that lands in someone's project, so:

1. **Check the symbol exists.** Everything a template may import is listed in
   [`verified-apis.md`](verified-apis.md). If it is not there, verify it
   against the real package and add it — with how you verified it.
2. **Add an integration test.** Valid Python that does not work is the failure
   mode that matters. Assert on the behaviour, not the file contents.
3. **Prefer a condition over a new template.** `FileSpec(..., when=...)` keeps
   the file set inspectable.
4. **Write comments for the person who inherits the file.** Generated code
   should explain constraints that are not visible from the code — why
   middleware is ordered a particular way, why a model must be registered.

## Adding a command

Commands live in `cli/` and do argument handling and rendering only. The logic
goes in a service layer so it can be tested without a terminal.

```python
@app.command()
@handle_errors
def mycommand(...):
    """One-line summary, then the examples."""
    root, manifest = load_project()
    plan = build_my_plan(manifest)
    execute_plan(plan, ExecutionContext(project_root=root, manifest=manifest))
```

`@handle_errors` turns any `SilloStartError` into a clean message plus its hint
and a predictable exit code. Raise those rather than printing and exiting.

Mutating commands should support `--dry-run`; inspection commands should
support `--json`.

## Style

- Type annotations everywhere; `from __future__ import annotations` at the top.
- Docstrings that say why, not what. `Args:`/`Returns:`/`Raises:` where the
  answer is not obvious from the signature.
- Errors carry a `hint` with the command that fixes them.
- Never overwrite user code without `--force`; never hide subprocess output.

```bash
uv run ruff check .
uv run ruff format .
uv run mypy sillo_start
```
