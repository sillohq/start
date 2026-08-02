# Sillo Start

The official bootstrapper, installer and development orchestrator for the
[Sillo](https://github.com/sillohq/core) framework.

```bash
uvx sillo-start create myapp
```

That runs a short setup wizard and generates a project that starts, serves, and
passes its own tests immediately — with authentication, the admin panel, an
Inertia frontend, queues and migrations already wired together if you asked for
them.

## What it does

Sillo Start is four tools that happen to share a manifest:

- **A project generator.** Blueprints for the shapes applications actually take
  — an API, a server-rendered app, an Inertia SPA, a background worker, a
  modular monolith.
- **A feature installer.** `sillo-start add auth` resolves the package groups,
  installs the dependencies, writes the files and updates the manifest as one
  transaction that rolls back if any step fails.
- **A development orchestrator.** `sillo-start dev` reads the manifest and runs
  every service the project needs, with prefixed output, health checks, crash
  restarts and a clean shutdown on Ctrl+C.
- **A diagnostician.** `sillo-start doctor` checks the project and its
  environment, and tells you the command that fixes each problem.

## Install

```bash
# Run without installing
uvx sillo-start create myapp

# Or install it
uv tool install sillo-start
```

Requires Python 3.11+. `uv` is preferred; `pip` works as a fallback.

## Quick start

```bash
uvx sillo-start create myapp
cd myapp
uv sync
sillo-start migrate run
sillo-start dev
```

Non-interactively — for scripts and CI:

```bash
uvx sillo-start create myapp \
  --database postgres \
  --auth session \
  --admin \
  --inertia react \
  --queue redis \
  --package-group monitoring \
  --no-interaction
```

## Commands

| Command | What it does |
| ------- | ------------ |
| `create` | Create a new application, with or without the wizard. |
| `init` | Create one in the current directory. |
| `add` | Install a feature: auth, admin, inertia, queue, scheduler. |
| `package` | List, inspect, add and remove package groups. |
| `generate` | Scaffold a model, controller, service, job, policy, and more. |
| `migrate` | Create, apply, roll back and inspect migrations. |
| `dev` | Run every development service together. |
| `services` | List the services and check what is reachable. |
| `build` | Install dependencies and build production assets. |
| `admin` | Create admin users. |
| `inspect` | Show what the project is configured with. |
| `doctor` | Diagnose the project and environment, with `--fix`. |

Every inspection command takes `--json`; every mutating command takes
`--dry-run`.

See [`docs/commands.md`](docs/commands.md) for the full reference.

## The manifest

`sillo.toml` is the source of truth. Every command reads it, and `add`,
`remove`, `generate`, `dev` and `doctor` all agree on the project's shape
because they are all looking at the same file.

```toml
[project]
name = "myapp"
sillo_version = ">=0.0.1a1"

[database]
enabled = true
driver = "postgres"
orm = "record"

[auth]
enabled = true
strategy = "session"

[packages]
groups = ["api", "record", "auth", "admin", "testing"]

[development]
backend_command = "uvicorn app.main:app --reload"
worker_command = "python scripts/worker.py"
```

Edit it by hand freely — writes go through a structure-preserving TOML parser,
so your comments and formatting survive.

## Safety

Sillo Start edits directories full of code you wrote, so:

- **Nothing is overwritten silently.** An existing file is left alone unless
  you pass `--force`.
- **Installs are transactional.** A failure part-way through undoes what
  already happened and restores the previous bytes.
- **`--dry-run` is honest.** It builds the same plan that would be applied and
  shows you the diffs.
- **Regenerated regions are fenced.** Blocks Sillo Start maintains are marked;
  everything outside them is yours.
- **Subprocess output is never hidden.** A failing `uv add` shows you why.

## Documentation

| Guide | Contents |
| ----- | -------- |
| [Commands](docs/commands.md) | Every command, flag and example. |
| [Blueprints](docs/blueprints.md) | The project archetypes, and writing your own. |
| [Package groups](docs/package-groups.md) | What each group installs and requires. |
| [Plugins](docs/plugins.md) | Extending Sillo Start from your own package. |
| [Architecture](docs/architecture.md) | How the internals fit together. |
| [Verified APIs](docs/verified-apis.md) | The framework surface templates may use, and the integration constraints they encode. |
| [Contributing](docs/contributing.md) | Working on Sillo Start itself. |

## Development

```bash
uv sync --extra dev
uv run pytest              # 279 tests
uv run ruff check .
```

The integration suite generates projects and executes them against the real
framework. That is deliberate: several constraints in the generated code —
middleware ordering, router mount order, how the ORM discovers models — produce
perfectly valid Python that simply does not work, and only running it catches
them. They are documented in [`docs/verified-apis.md`](docs/verified-apis.md).

## Licence

BSD-3-Clause.
