# Verified Sillo APIs

Ground truth for every template Sillo Start generates. Everything here was
verified by importing the real packages and introspecting signatures on
2026-07-31 against `sillo-framework==0.0.1a1` and `sillo-inertia==0.1.0`.

**Rule: no template may import a symbol that is not on this page.** When a
capability is genuinely missing from the framework, Sillo Start defines an
adapter interface and marks it `TODO(sillo)` rather than inventing an import.

## Distribution names

| Import        | PyPI distribution   | Notes                                    |
| ------------- | ------------------- | ---------------------------------------- |
| `sillo`       | `sillo-framework`   | Import name differs from the dist name.  |
| `sillo_inertia` | `sillo-inertia`   | Separate repo/package.                   |

`sillo-framework` extras: `jwt`, `record`, `hashing-bcrypt`, `hashing-argon2`,
`hashing-scrypt`, `hashing-all`, `cache`, `events`, `templating`, `graphql`,
`cli`, `granian`, `all`, `dev`.

Admin, auth, sessions, security, work/queue/scheduler, cache and testclient all
live **inside core** — there is no separate `sillo-admin` or `sillo-auth`
distribution. Package groups therefore map mostly to *extras plus drivers*, not
to standalone Sillo packages.

## Application

```python
from sillo import silloApp, Router, Depend, Query, Path, Header, Cookie, Form, File
from sillo.core.http import Request, Response

app = silloApp(debug=..., title=..., version=..., description=...)
```

Methods that exist on `silloApp`:

`use(middleware)`, `mount_router(router, name=None)`, `register(asgi_app, prefix="")`,
`on_startup(fn)`, `on_shutdown(fn)`, `get/post/put/patch/delete/head/options(path, ...)`,
`add_route(...)`, `ws_route(...)`, `add_ws_route(...)`, `add_exception_handler(exc, handler)`,
`add_encoder(...)`, `frontend(path="/", directory="dist", fallback="auto")`,
`run(host="127.0.0.1", port=8000, reload=False)`, `url_for(...)`,
`build_openapi()`, `get_all_routes()`, `setup()`, `wrap_asgi(...)`, plus the
`state` dict.

**Do not generate these — they do not exist:** `app.add_middleware()`,
`app.route()`, `app.include_router()`, `app.mount()`. Middleware is registered
with `app.use(...)`. Several checked-in examples under `core/examples/` still
call `app.add_middleware(...)` and `from sillo.auth.base import BaseUser`; those
examples are stale and must not be used as a template source.

Handlers take `(request, response)` and return the response:

```python
@app.get("/items/{item_id:int}")
async def get_item(req: Request, res: Response) -> Response:
    return res.json({"id": req.path_params.item_id})
```

`Response` builders: `.json(data, status_code=..., headers=...)`, `.html(...)`,
`.redirect(location, status_code=...)`, `.empty(status_code=...)`, `.file(...)`,
`.stream(...)`, `.set_header(name, value)`, `.status(code)`.

`Router(prefix=None, routes=[], tags=None, dependencies=None, ...)` carries the
same verb decorators plus `.route()`, and is attached with `app.mount_router()`.

Path parameters are injected as **keyword arguments**, not read off
`request.path_params`; the converter in the path decides the type:

```python
@router.get("/items/{item_id:int}")
async def show(request, response, item_id):   # item_id is already an int
    ...
```

`request_model=` injects the validated body as the next plain parameter after
`(request, response)`.

**Inside a router, `request.app` is the router, not the application.** Reach
the application — and therefore `app.state`, where `setup_record` and
`setup_work` put their managers — through `request.base_app`.

## Configuration

```python
from sillo.config import Config, Field

class AppConfig(Config):
    database_url: str
    debug: bool = False
    port: int = 8000

    class Config:
        env_file = ".env"
```

`Config` is a Pydantic `BaseModel` subclass that loads `.env`. Load it **once**
at startup and pass it around; do not scatter `os.getenv` through the app.

## Record ORM

```python
from sillo.record import (
    Model, DatabaseConfig, DatabaseBackend, DatabaseManager, setup_record,
    TimestampsMixin, SoftDeletesMixin, HasUlidMixin, SerializesToDictMixin,
    Collection, paginate, transaction, Factory, Seeder, MigrationHelper,
)
from tortoise import fields

db = setup_record(app, config, model_modules=["database.models"])
```

`setup_record(app, config, *, model_modules=None) -> DatabaseManager` registers
`app.use(manager.ensure_context)`, `app.on_startup(manager.init)` and
`app.on_shutdown(manager.shutdown)`, and stores the manager at
`app.state["record"]`. `DatabaseManager.health()` returns a bool — that is the
database health check.

`DatabaseConfig` constructors: `.from_env(prefix="")` (reads `DATABASE_URL`,
defaults `sqlite://:memory:`), `.sqlite(path=":memory:")`,
`.postgres(database, password, *, user="postgres", host="localhost", port=5432)`,
`.mysql(database, password, *, user="root", host="localhost", port=3306)`.

Record wraps Tortoise ORM, so model fields come from `tortoise.fields`. Record
adds `CreatedAtField`, `UpdatedAtField`, `SoftDeleteField`, `SlugField`,
`ULIDField` on top.

## Users

```python
from sillo.users import (
    User, UserBaseModel, UserManager, AnonymousUser,
    make_password, check_password, validate_password,
)
```

`UserBaseModel` is the extension point (a Record `Model`) with fields `id`,
`email`, `username`, `password`, `is_active`, `is_staff`, `is_superuser`,
`last_login`, `email_verified_at`, and methods `set_password`, `check_password`,
`set_last_login`, `mark_email_verified`, `load_user`, `verify_credentials`.
`User` is the concrete default, table `users`, with `objects = UserManager()`.

`UserManager`: `create_user(email, username, password=None, **extra)`,
`create_superuser(email, username, password, **extra)`, `get_by_id`,
`get_by_email`, `get_by_username`, `get_by_natural_key`.

`make_password(raw_password=None, scheme=None, **kwargs)` and
`check_password(raw_password, encoded)` are module-level helpers.

## Authentication

```python
from sillo.auth import AuthenticationMiddleware, useAuth, auth, has_permission
from sillo.auth.jwt_auth import JWTAuthBackend, create_jwt, decode_jwt, TokenForUser
from sillo.auth.session_auth import SessionAuthBackend, login, logout, SessionGuard
from sillo.auth.apikey import APIKeyAuthBackend, generate_api_key, verify_api_key

app.use(AuthenticationMiddleware(user_model=User, backend=JWTAuthBackend()))
```

- `AuthenticationMiddleware(user_model=SimpleUser, backend=None)` — registered via `app.use()`.
- `JWTAuthBackend(identifier="id", secret_key=None, check_blacklist=True)` —
  **pass `identifier="sub"` whenever tokens come from `TokenForUser`.** The
  backend does `identity=payload.get(self.identifier, "")` and sillo writes the
  user id into `sub`, never `id`. With the default, `identity` is `""`, the user
  never loads, and every authenticated request fails with no error logged.
- `TokenForUser(user, secret, algorithm="HS256", issuer=None, audience=None)` —
  `.token_pair(access_expires=None, refresh_expires=None)` returns
  `{"access_token", "refresh_token", "token_type"}`; `.access_token()`,
  `.refresh_token()` and `.verify(token)` are also available. Prefer this over
  hand-building a payload with `create_jwt`: it sets `sub` and `typ` correctly.
  Refresh tokens carry `typ="refresh"` — check it, or an access token will be
  accepted as a refresh token.
- `JWTUserMixin.refresh_token_pair` does **not** work out of the box: it looks
  the row up by a `jti` claim that `token_pair()` never emits, so it raises
  `ValueError("Unknown refresh token")`. Do stateless refresh via `decode_jwt`
  instead.
- `SessionAuthBackend(session_key="user", identifier="id")` — requires session middleware.
- `create_jwt(payload, secret, algorithm="HS256", expires_in=None)` — **`secret` is
  required and positional.** The one-argument `create_jwt({"sub": ...})` form in
  the stale examples raises `TypeError`.
- `decode_jwt(token, secret, algorithms=None)` raises `ValueError` on expiry/invalid.
- `login(request, user, session_key="user", identifier="id")` / `logout(request, session_key="user")`
- `useAuth(scopes=None, permissions=None, backends=None, user_model=None, required=True)`
  is also accepted by route decorators as `auth=`.

`request.user` is populated by the middleware; check `request.user.is_authenticated`.

## Sessions

```python
from sillo.session import SessionMiddleware, SessionConfig

app.use(SessionMiddleware(config=SessionConfig(...), secret_key=...))
```

`SessionConfig(session_cookie_name="session_id", session_expiration_time=86400,
session_permanent=True, session_refresh_each_request=True,
session_cookie_secure=True, session_cookie_httponly=True,
session_cookie_samesite="lax", ...)`.

## Admin

```python
from sillo.admin import AdminSite, ModelAdmin, setup_admin, AdminUser, AdminActivity

admin = setup_admin(app, title="MyApp Admin", prefix="/admin", user_model=None)

@admin.register(Post)
class PostAdmin(ModelAdmin):
    list_display = ["id", "title", "created_at"]
    search_fields = ["title"]
```

`setup_admin` builds the site, mounts auth middleware + static files, and
registers routes on startup. The configured user model and `AdminActivity` are
auto-registered. Admin logins authenticate against `AdminUser` (table
`admin_users`) unless `user_model=` overrides it — it must subclass
`UserBaseModel`.

`ModelAdmin` knobs: `list_display`, `list_display_links`, `list_filter`,
`search_fields`, `ordering`, `readonly_fields`, `fields`, `exclude`, `actions`,
`list_per_page`, `save_on_top`, `verbose_name`, and `has_*_permission` hooks.

## Security middleware

```python
from sillo.security import (
    CORSMiddleware, CorsConfig, CSRFMiddleware, CSRFConfig,
    RateLimitMiddleware, RateLimitConfig, Shield, shield,
)
```

## Cache

```python
from sillo.cache import configure_cache, CacheSettings, MemoryCache, RedisCache, cache
```

## Work: queue, tasks, scheduler

```python
from sillo.work import task, setup_work, MemoryBackend, RedisBackend, TaskPriority
from sillo.work.queue import (
    Job, dispatch, QueueWorker, WorkerOptions, WorkerPool,
    SyncConnection, RedisConnection, ConnectionManager,
    PayloadSerializer, FailedJobRepository, MemoryFailedRepository,
)
from sillo.work.scheduler import setup_scheduler, SchedulerManager, CronTrigger, IntervalTrigger
```

- `setup_work(app, *, queue_backend=None, queue_name="default")` populates
  `app.state["work"]`, `["scheduler"]`, `["queue_connection"]`, `["events"]`.
- `setup_scheduler(app) -> SchedulerManager`; manager has `cron`, `every`,
  `schedule`, `start`, `stop`, `pause`, `resume`, `list`, `stats`.
- `QueueWorker(manager, serializer, failed_repo, *, options=WorkerOptions(...))`
  with `run/stop/pause/resume`. `WorkerOptions(concurrency=4, memory_limit=128,
  timeout=..., ...)`.
- `@task(name=None, *, priority=..., max_attempts=1, queue="default", timeout=None)`
- `RedisConnection(url="redis://localhost:6379", *, prefix="sillo:queue:")`
- `ConnectionManager()` has **`add(name, connection)` and `connection(name)`
  only** — there is no `register()`. `manager.register(...)` raises
  `AttributeError` at worker startup, after the database has already connected,
  so the failure looks like a database problem rather than a typo.

## Testing

```python
from sillo.testclient import TestClient, AsyncTestClient, create_client
```

## Inertia

```python
from sillo_inertia import Inertia, InertiaConfig, vite_react, vite_vue, lazy, raw

inertia = Inertia(app=app, root_view="templates/app.html", vite=vite_react(entry="src/main.jsx"))
await inertia.render(request, response, "Dashboard", {"user": ...})
```

- `Inertia(app=None, root_view="app.html", version=None, root_id="app",
  base_dir=None, vite=None, shared_props={}, view_data={})`. Passing `app=`
  registers the middleware immediately; otherwise call `.middleware(app)`.
- `.render(request, response, component, props=None, *, status_code=200,
  view_data=None, encrypt_history=False, clear_history=False)`
- `.share(**props)`, `.redirect(request, response, location, status_code=None)`,
  `.location(response, url, status_code=409)`
- `vite_react(entry="src/main.jsx", dev_server="http://localhost:5173",
  manifest_path="dist/.vite/manifest.json", asset_prefix="/assets/", dev=True,
  react_refresh=True)`
- `vite_vue(entry="src/main.ts", ...)` — same minus `react_refresh`.

**Svelte has no first-party helper.** Only `ViteReactOptions` and
`ViteVueOptions` exist. Sillo Start ships a `ViteOptions` subclass into the
generated project for Svelte and marks it `TODO(sillo)`; it renders the same
tags as the Vue variant, which is correct for Svelte's Vite plugin.

## Integration constraints found by running generated code

These are not documented anywhere in the framework and were each found by
generating a project and executing it. Every one of them silently produces a
broken application if ignored, so the templates encode all of them.

1. **`app.use()` builds the chain inside-out.** The middleware registered
   *last* is outermost and runs *first*. Authentication reads the session, so
   `AuthenticationMiddleware` must be registered *before* `SessionMiddleware`.
   Getting this backwards yields `Auth backend SessionAuthBackend failed: No
   Session Middleware Installed` on every request, and `request.user` is never
   populated. The framework's own admin test notes the same ordering.

2. **A mounted router claims its entire prefix subtree.** Mounting `/api`
   before `/api/auth` makes every auth route return 404. Routers must be
   mounted most-specific-prefix first. `ProjectCreator.routers()` sorts by
   descending prefix length for exactly this reason.

   The degenerate case is worse: a router with **no prefix** mounts at `""` and
   claims the whole URL tree, shadowing anything registered afterwards —
   including the admin panel's routes, which are added during startup, after
   mounting has finished. Generated projects therefore register root-level page
   handlers individually with `application.get("/", handler=...)` rather than
   mounting a prefix-less router.

3. **Models are discovered by class name, per app.** Adding `sillo.users` to
   `model_modules` alongside the project's own models lets the framework's
   built-in `User` displace the project's `User` — the project's extra columns
   are then never created, with no error. Generated projects list only their
   own models module (plus `sillo.admin.models` when the admin is enabled,
   which the panel needs for its activity log and roles).

4. **Models must be imported in the package `__init__`.** Tortoise scans the
   listed module's namespace, so a model in `database/models/post.py` that is
   not imported into `database/models/__init__.py` is invisible. Its first
   query fails with `default_connection for the model ... cannot be None`.
   Generated projects keep an explicit `__models__` list, which Tortoise reads
   in preference to scanning.

5. **`UserManager` never binds itself.** `objects = UserManager()` leaves
   `manager.model` as `None`, because binding happens through Django's
   `contribute_to_class` hook, which Tortoise does not call. The manager then
   falls back to `sillo.users.base.User` — a model the project does not
   register — producing the same `default_connection` error. Generated user
   models call `User.objects.contribute_to_class(User, "objects")` explicitly.

6. **`display_name`, `identity` and `is_authenticated` are read-only
   properties** on `UserBaseModel`. Declaring a field with one of those names
   shadows the property and raises `property ... has no setter` on assignment.

7. **Admin routes carry a trailing slash**: `/admin/login/`, not
   `/admin/login`. Without it the request 404s.

8. **`TestClient` must be used as a context manager** for anything touching the
   database or scheduler — entering it is what runs the ASGI lifespan that
   `setup_record` and `setup_work` hook into.

9. **`import sillo` fails without `tortoise-orm`**, even though `record` is
   declared as an optional extra. `sillo/__init__.py` imports `application` →
   `exception_handler` → `auth` → `sillo.users.base`, which does
   `from tortoise import fields` unconditionally. A project installed with a
   bare `sillo-framework` therefore cannot start at all, database or not.
   Generated projects always include the `record` extra and an async driver;
   see `REQUIRED_SILLO_EXTRAS` in `config/defaults.py`.

10. **`pydantic.EmailStr` needs `email-validator`** at import time, so any
    project generating auth schemas must declare it. The `auth` package group
    does.

## Gaps Sillo Start must work around

1. **No framework CLI.** `sillo-framework` declares no `[project.scripts]` and
   has no `__main__.py`. The `sillo run` / `sillo work` / `sillo schedule`
   commands in the original brief do not exist. Generated manifests therefore
   use real commands: `uvicorn app.main:app --reload` for the backend and
   generated `scripts/worker.py` / `scripts/scheduler.py` entry points, run with
   `python`. Sillo Start's orchestrator drives those.

2. **Migrations are Tortoise-native, not aerich.** Tortoise 1.0+ ships its own
   migration engine (`tortoise.migrations`, history in the
   `tortoise_migrations` table) and aerich itself recommends it from that
   version on. `sillo.record.MigrationHelper` wraps it:
   `MigrationHelper("database.config.TORTOISE_ORM", app="models")` with
   `init/make/upgrade/downgrade/plan/sql`. Sillo Start's `TortoiseBackend`
   drives the same helper inside the project's interpreter.

   Three things bite here:

   - **`apps.<label>.migrations` is required** in `TORTOISE_ORM`. Without it
     Tortoise classes the app as unmigrated and every command cheerfully
     reports "no migrations" while doing nothing at all.
   - **Targets are `app_label.name`.** A bare `"0001_initial"` is rejected as
     `Unknown app label 0001_initial`. `MigrationHelper` qualifies bare names.
     There is no "roll back N steps" — resolve a target from the files on disk.
   - **Nothing closes connections for you.** Neither the native API nor the CLI
     tears Tortoise down, and an open connection keeps the event loop alive, so
     a script that finishes its migration then hangs at interpreter shutdown is
     a missing `Tortoise.close_connections()`, not a deadlock.

   Public API is `tortoise.migrations.api.{migrate,plan,sqlmigrate}`;
   `makemigrations` and `init` exist only behind `tortoise.cli.cli.run_cli_async`,
   which takes the config as a dotted path rather than a mapping.

3. **Authorization.** There is no roles/permissions table in core beyond
   `UserProtocol.has_perm` / `has_perms` / `has_module_perms` and an `AdminRole`
   referenced by the admin package. Generated role/permission models are plain
   Record models that satisfy those protocol methods.

4. **Mail and storage.** `sillo.mail` exists but is not covered here; storage has
   no core module. Both are generated as thin config + adapter modules.
