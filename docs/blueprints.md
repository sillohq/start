# Blueprints

A blueprint is a stance on what a project of a given shape should start with.
They stay deliberately small: a blueprint that enables everything is not a
starting point, it is a project you have to dismantle.

```bash
sillo-start create myapp --blueprint inertia-react
sillo-start create --list-blueprints
```

## The built-in blueprints

| Blueprint | Shape |
| --------- | ----- |
| `minimal` | Routing and configuration, nothing else. |
| `api` | REST API with OpenAPI docs, health checks and the controller/request/resource layout. |
| `fullstack` | Server-rendered pages, Record models, session auth, admin panel. |
| `inertia-react` | React SPA served through Inertia, with Vite. |
| `inertia-vue` | The same with Vue. |
| `inertia-svelte` | The same with Svelte. |
| `worker` | Queues and scheduled tasks; HTTP limited to a health probe. |
| `modular-monolith` | Feature modules under `app/modules/`, each mountable on its own. |
| `enterprise` | Everything: Postgres, auth, authorization, admin, Redis queues, monitoring, security, Docker, CI. |

A blueprint sets defaults. Explicit flags always win, so
`--blueprint fullstack --database postgres` means "the fullstack shape, on
Postgres".

## What a blueprint defines

```python
Blueprint(
    name="api",
    summary="A REST API with OpenAPI docs, health checks and tests.",
    app_type=AppType.API,
    groups=("api", "testing"),
    extra_directories=("app/http/controllers", "app/services"),
)
```

- `groups` — package groups enabled by default.
- `extra_files` / `extra_directories` — additions to the common set.
- Manifest defaults, declared as data in `BLUEPRINT_DEFAULTS` so choosing a
  blueprint has an effect that can be listed rather than only executed.

Files are declared with a condition, so a blueprint contributes to the shared
set rather than duplicating it:

```python
FileSpec("routes/auth.py.j2", "routes/auth.py", when="auth.enabled,auth.routes")
```

The condition is a dotted manifest path. A leading `!` negates it; commas mean
"all of these". Conditions are declarative rather than arbitrary callables so
the file set can be inspected and explained.

## Writing your own

```python
from sillo_start.plugins import Blueprint, FileSpec, Plugin

CMS = Blueprint(
    name="cms",
    summary="A content-managed site.",
    groups=("api", "record", "auth", "admin", "testing"),
    extra_directories=("app/content",),
    extra_files=(
        FileSpec("cms/content.py.j2", "app/content/models.py", when="uses_record"),
    ),
)

def plugin(registry: Plugin) -> None:
    registry.register_blueprint(CMS)
```

Templates referenced by a plugin's blueprint are found by adding your template
directory to the engine. See [plugins.md](plugins.md).
