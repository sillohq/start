# Contributing

```bash
git clone https://github.com/sillohq/start
cd start
uv sync --extra dev
uv run pytest
```

The tool depends on `typer` and `rich` and nothing else, so the development
environment is small and installs in seconds.

## Running the tests

```bash
uv run pytest                            # everything
uv run pytest tests/test_template.py     # one module
uv run pytest -k "rename"                # by name
uv run pytest --cov=sillo_start          # with coverage
```

Two layers:

- **`tests/test_template.py`** — parsing a repository reference, unpacking an
  archive, and rewriting the result into someone's project. The network is
  stubbed at `urlopen`; what is tested is what the tool does with an archive,
  not that GitHub serves one.
- **`tests/test_cli.py`** — the command through Typer's runner, asserting on
  exit codes and on what the user is told.

Neither hits the network, so the suite runs offline and in well under a second.

## What belongs here

Creating a project from a starter repository. That is the whole tool.

Everything a project needs *after* it exists — migrations, users, the queue
worker, running the app — belongs to the project, in its own `console.py`. The
framework provides those operations as plain functions in
`sillo.record.commands`, `sillo.users.commands` and `sillo.work.commands`, and
a project decides how to expose them.

The split is deliberate. A tool that also manages projects has to keep working
against every version of every project it ever generated. A tool that only
creates them is finished the moment the files land.

## Layout

```
sillo_start/
  __main__.py          `python -m sillo_start` and the console script
  cli/
    app.py             the Typer app, error rendering, exit codes
    create.py          create-app
  project/
    template.py        fetching a starter and personalising it
  utils/               console, naming, subprocess, package managers
  exceptions.py
```

## Style

Docstrings say *why*, not *what* — the signature already says what. A comment
worth keeping is one explaining a decision that would otherwise look arbitrary.

Run `uv run ruff check .` and `uv run ruff format .` before opening a pull
request.
