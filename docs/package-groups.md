# Package groups

A package group is a declarative bundle: the packages a capability needs, the
environment variables and directories it expects, and the groups it requires or
conflicts with.

```bash
sillo-start package list
sillo-start package info record
sillo-start package add monitoring
```

## An important property of the Sillo ecosystem

Most capabilities live *inside* `sillo-framework` rather than in separate
distributions. The admin panel, authentication, sessions, security middleware,
queues, the scheduler, caching and the test client are all first-party in core.

So a group usually contributes framework **extras** — which accumulate into a
single `sillo-framework[record,jwt,templating]` requirement — rather than new
packages. Several groups legitimately install nothing at all, because the code
is already there; they contribute structure and configuration. Inventing a
`sillo-api` package to make the list look symmetrical would produce projects
that cannot install.

## The built-in groups

| Group | Installs | Requires |
| ----- | -------- | -------- |
| `api` | nothing — routing, validation, OpenAPI and pagination are in core | — |
| `record` | `record` extra, `aerich`, a database driver | — |
| `auth` | `jwt` and `hashing-bcrypt` extras, `email-validator` | `record` |
| `admin` | `templating` extra | `record`, `auth` |
| `inertia` | `sillo-inertia`, `templating` extra, frontend packages | — |
| `work` | `cache` extra (only Redis needs it) | — |
| `realtime` | `events` extra for cross-process broadcasting | — |
| `monitoring` | `structlog` | — |
| `security` | nothing — CORS, CSRF, rate limiting are in core | — |
| `testing` | `pytest`, `pytest-asyncio`, `httpx`, `coverage` | — |

`sillo-start package info <name>` prints the full detail for any group.

## Resolution

Groups are resolved transitively and returned dependencies-first, so the admin
scaffolding can assume the user model already exists.

```bash
$ sillo-start package add admin
Also enabling required groups: record, auth
```

Conflicts between two groups in the final set are rejected, as are dependency
cycles, and removing a group another group depends on is refused:

```bash
$ sillo-start package remove record
✗ 'record' is required by: admin, auth.
  Remove those first: sillo-start package remove admin
```

## Defining a group

```python
from sillo_start.plugins import PackageGroup
from sillo_start.utils.environment import EnvVar

SEARCH = PackageGroup(
    name="search",
    summary="Full-text search.",
    description="Indexes models into Meilisearch and exposes a search endpoint.",
    python_packages=("meilisearch-python-sdk>=2.0",),
    env_vars=(
        EnvVar("MEILI_URL", "http://localhost:7700"),
        EnvVar("MEILI_KEY", "", comment="Master key.", secret=True),
    ),
    directories=("app/search",),
    requires=("record",),
    requires_database=True,
    post_install=("Run `sillo-start search reindex` once your models are ready.",),
)
```

| Field | Meaning |
| ----- | ------- |
| `sillo_extras` | Extras added to the `sillo-framework` requirement. |
| `python_packages` | Additional PEP 508 requirements. |
| `dev_packages` | Requirements added to the `dev` optional group. |
| `frontend_packages` | npm dependencies. |
| `env_vars` | Written to `.env` and `.env.example`, never overwriting an existing value. |
| `directories` | Created relative to the project root. |
| `requires` / `conflicts` | Relationships with other groups. |
| `requires_database` | Refuses to install without one. |
| `provides` | Capability tags, so several groups can satisfy one need. |
| `plan_hook` | Extra operations contributed at install time. |
| `post_install` | Follow-up steps shown to the user. |
