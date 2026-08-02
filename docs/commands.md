# Command reference

Global options come before the subcommand:

```bash
sillo-start --verbose create myapp    # correct
sillo-start create myapp --verbose    # not a create option
```

| Option | Effect |
| ------ | ------ |
| `--verbose`, `-v` | Debug output, and tracebacks on unexpected errors. |
| `--quiet`, `-q` | Suppress everything but errors. |
| `--version`, `-V` | Print the version. |

Exit codes: `0` success, `1` failure, `2` usage error, `130` cancelled.

## create

Create a new application.

```bash
sillo-start create myapp                       # guided setup
sillo-start create myapp --no-interaction      # defaults, no prompts
sillo-start create myapp --blueprint inertia-vue
```

| Option | Default | Meaning |
| ------ | ------- | ------- |
| `--blueprint`, `-b` | inferred | Project archetype. `--list-blueprints` to see them. |
| `--directory`, `-d` | `./<name>` | Where to generate. |
| `--database` | wizard | `postgres`, `mysql`, `sqlite`, `none`. |
| `--auth` | wizard | `session`, `jwt`, `token`, `apikey`, `none`. |
| `--admin` / `--no-admin` | off | Include the admin panel. |
| `--inertia` | off | `react`, `vue`, `svelte`. |
| `--queue` | off | `redis`, `database`, `memory`, `none`. |
| `--scheduler` | off | Scheduled tasks. |
| `--cache`, `--mail`, `--storage` | off | Backend for each. |
| `--package-group`, `-p` | — | Enable a group. Repeatable. |
| `--package-manager` | `uv` | `uv` or `pip`. |
| `--install` | off | Install dependencies after generating. |
| `--git` / `--no-git` | on | Initialise a repository. |
| `--force`, `-f` | off | Generate into a non-empty directory. |
| `--dry-run` | off | Show the plan; write nothing. |
| `--no-interaction` | off | Never prompt. Implied in CI. |

Passing any feature flag skips the wizard for every decision — being asked
about something you already specified is worse than assuming a default.

### init

The same thing in the current directory, taking the project name from it.

## add

Install a feature into an existing project.

```bash
sillo-start add auth --strategy session
sillo-start add admin
sillo-start add inertia --adapter react
sillo-start add queue --driver redis
sillo-start add auth --dry-run
```

Features: `auth`, `admin`, `inertia`, `queue`, `scheduler`, `record`,
`monitoring`, `security`, `realtime`, `testing`, `api`. Run `sillo-start add`
with no argument to list them.

Each feature resolves to package groups, so `add admin` also brings in `auth`
and `record` and says so.

## package

```bash
sillo-start package list                 # with an installed marker
sillo-start package list --json
sillo-start package info record          # what it installs and requires
sillo-start package add monitoring
sillo-start package remove monitoring --yes
```

Removal drops dependencies and unregisters the group, but leaves generated
source alone — it may have been edited, and deleting your code is not something
a package manager should do. Removing a group another group requires is
refused.

## generate

```bash
sillo-start generate                              # list the generators
sillo-start generate model Post -f title:str -f body:text:null
sillo-start generate service Billing
sillo-start generate controller UserController
sillo-start generate job SendInvoice
```

### Model fields

`--field` / `-f` takes `name:type[:flag...]`:

```bash
-f title:str:unique
-f body:text:null
-f views:int:default=0
-f code:str:max=10
-f author:fk:User
```

Types: `str`, `text`, `int`, `bigint`, `float`, `decimal`, `bool`, `date`,
`datetime`, `time`, `json`, `uuid`, `email`, `url`, `slug`, plus the
relationships `fk`, `o2o`, `m2m`.

Flags: `null`, `unique`, `index`, `default=<value>`, `max=<n>`.

| Option | Effect |
| ------ | ------ |
| `--no-timestamps` | Omit the created/updated columns. |
| `--soft-deletes` | Add a soft-delete column. |
| `--repository`, `--controller` | Also generate those. |
| `--no-schema`, `--no-tests` | Skip the companions. |
| `--force` | Overwrite existing files. |

A generated model is registered in `database/models/__init__.py` automatically.
Without that the ORM cannot see it, and its first query fails confusingly.

## migrate

```bash
sillo-start migrate init
sillo-start migrate make -m "add posts"
sillo-start migrate run
sillo-start migrate status --json
sillo-start migrate rollback --steps 1
```

Migrations run through aerich against the generated `database/config.py`, in
the project's environment and with its `.env` loaded, so the migration tool
always sees the same database the application does. Destructive commands
confirm first unless `--yes` is passed or CI is detected.

## dev

```bash
sillo-start dev
sillo-start dev --only backend,frontend
sillo-start dev --without worker
sillo-start dev --list
```

Starts everything the manifest defines, with:

- output prefixed and coloured per service,
- ports checked before anything starts,
- health checks before the ready banner,
- crashed services restarted, up to three times a minute,
- Ctrl+C stopping everything in reverse order, including grandchild processes.

A second Ctrl+C forces the shutdown.

## services

```bash
sillo-start services list
sillo-start services status         # what is reachable right now
```

`status` probes the ports rather than tracking daemons, so it reports the truth
whether a service was started by `dev` or by hand.

## build

```bash
sillo-start build                # dependencies, then frontend assets
sillo-start build --frontend
```

## admin

```bash
sillo-start admin create-user
sillo-start admin create-user --email a@b.com --username admin --regular
```

Runs inside the project's environment against its own models. Sign in at
`/admin/login/` — the trailing slash matters.

## inspect

```bash
sillo-start inspect
sillo-start inspect --json
sillo-start inspect --section database
```

## doctor

```bash
sillo-start doctor
sillo-start doctor --fix       # apply the safe fixes
sillo-start doctor --strict    # warnings fail too, for CI
sillo-start doctor --json
```

Checks the Python version, package managers, the framework install, the
manifest, `.env` completeness and secret strength, storage permissions, the
database driver and server, Redis, migration state, frontend dependencies and
Vite config, Node or Bun, Docker, port availability, package-group consistency,
and plugin loading.

Output separates errors, warnings and passes, and each problem carries the
command that resolves it. Exits non-zero when anything failed.
