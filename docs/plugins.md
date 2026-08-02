# Writing a plugin

A Sillo package extends Sillo Start by exposing a callable under the
`sillo_start.plugins` entry-point group.

```python
# my_package/sillo_start.py
from sillo_start.plugins import PackageGroup, Plugin

SEARCH = PackageGroup(
    name="search",
    summary="Full-text search.",
    python_packages=("meilisearch-python-sdk>=2.0",),
    requires=("record",),
)

def plugin(registry: Plugin) -> None:
    registry.register_package_group(SEARCH)
```

```toml
# my_package/pyproject.toml
[project.entry-points."sillo_start.plugins"]
my_search = "my_package.sillo_start:plugin"
```

Install the package and the group appears everywhere — `package list`, the
wizard, `add`, resolution, `doctor`.

## What a plugin can register

```python
def plugin(registry: Plugin) -> None:
    registry.register_package_group(group)     # a capability bundle
    registry.register_blueprint(blueprint)     # a project archetype
    registry.register_generator(generator)     # a `generate` subcommand
    registry.register_service(service)         # a service `dev` can run
    registry.register_doctor_check(check)      # a diagnostic
```

Registration goes through the `Plugin` object rather than the global registries
directly, so there is one place to validate what is being added and to
attribute a failure to the plugin that caused it. Colliding with a built-in
name is refused.

## A generator

```python
from sillo_start.generators import Generator, GeneratorTarget

INDEXER = Generator(
    name="indexer",
    summary="A search indexer for one model.",
    suffix="Indexer",
    requires=("uses_record",),
    targets=(GeneratorTarget("search/indexer.py.j2", "app/search/{snake}.py"),),
)
```

Destination patterns accept `{snake}`, `{pascal}`, `{camel}`, `{kebab}`,
`{plural}` and `{table}`.

For templates of your own, add your directory to the engine:

```python
from pathlib import Path
from sillo_start.templating import TemplateEngine

engine = TemplateEngine(extra_dirs=[Path(__file__).parent / "templates"])
```

Extra directories are searched first, which is also how a plugin can override a
built-in template.

## A development service

```python
from sillo_start.orchestration import ServiceDefinition, port_check

registry.register_service(ServiceDefinition(
    name="search",
    command="meilisearch --http-addr 127.0.0.1:7700",
    port=7700,
    url="http://localhost:7700",
    health=port_check(7700),
    description="Meilisearch",
))
```

## A doctor check

```python
from sillo_start.cli.doctor import Diagnosis, Finding, Level

def check_search(diagnosis: Diagnosis) -> Finding | None:
    if not diagnosis.in_project or not diagnosis.manifest.has_group("search"):
        return None          # not applicable — report nothing
    from sillo_start.utils.ports import can_connect
    if can_connect("localhost", 7700):
        return Finding("Meilisearch", Level.PASS, "reachable")
    return Finding(
        "Meilisearch",
        Level.FAIL,
        "nothing listening on 7700",
        fix="Start it, or `docker compose up -d search`.",
    )
```

Return `None` when a check does not apply, a `Finding` for one result, or a
list for several. A check that raises becomes a finding of its own rather than
aborting the diagnosis.

## Failure handling

Plugin loading is fault-tolerant on purpose. A plugin that fails to import or
raises during registration is reported as a warning and skipped, and everything
else still loads — one broken third-party package making `sillo-start`
unusable would be far worse than running without that plugin. `sillo-start
doctor` reports the failures.
