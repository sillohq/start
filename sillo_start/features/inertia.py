"""Installing the Inertia frontend.

Inertia is the most involved feature to add: it touches Python dependencies,
the root HTML view, a Vite project, an adapter-specific entry file and page
components. It is built as a plan like everything else, so a failure half way
through leaves no half-configured frontend behind.

Svelte deserves a note. ``sillo_inertia`` ships ``vite_react()`` and
``vite_vue()`` helpers but nothing for Svelte, so rather than inventing an
import, generated Svelte projects get a small ``ViteOptions`` subclass in their
own codebase. It renders the same tags the Vue variant does, which is correct
for Svelte's Vite plugin.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config.defaults import (
    INERTIA_ENTRY_FILES,
    INERTIA_FRONTEND_PACKAGES,
    INERTIA_PAGE_EXTENSIONS,
    FrontendPackageManager,
    InertiaAdapter,
)
from ..config.models import SilloManifest
from ..operations.base import ExecutionContext
from ..operations.commands import RunCommand, UpdateManifest
from ..operations.files import CreateDirectory, CreateFile
from ..operations.transaction import ExecutionPlan, execute_plan
from ..packages.installer import build_install_plan
from ..packages.resolver import resolve
from ..templating import build_context
from ..templating import engine as default_engine
from ..utils.console import console
from ..utils.pkgmanagers import frontend_manager


def add_inertia(
    root: Path,
    manifest: SilloManifest,
    *,
    adapter: InertiaAdapter,
    install: bool = True,
    dry_run: bool = False,
) -> None:
    """Add an Inertia frontend to an existing project."""
    if manifest.inertia.enabled and manifest.inertia.adapter == adapter.value:
        console.info(f"Inertia with {adapter} is already configured.")
        return

    # The manifest is updated before the plan is built so every template sees
    # the final configuration rather than the pre-install state.
    manifest.inertia.enabled = True
    manifest.inertia.adapter = adapter

    plan = build_plan(root, manifest, adapter=adapter, install=install)
    context = ExecutionContext(project_root=root, manifest=manifest, dry_run=dry_run)

    if dry_run:
        console.header("Dry run", f"{len(plan)} operation(s)")
        plan.render(context, console=console)
        return

    console.header(f"Adding Inertia ({adapter})")
    execute_plan(plan, context, console=console)

    console.blank()
    console.success(f"Inertia with {adapter} is configured.")

    _report_wiring(root)

    console.blank()
    console.print("[bold]Next[/bold]")
    steps = []
    if not install:
        steps.append(
            f"cd {manifest.inertia.frontend_path} && {manifest.inertia.package_manager} install"
        )
    steps.append("sillo-start dev")
    console.commands(steps)


def _report_wiring(root: Path) -> None:
    """Tell the developer how to attach the adapter, if it is not attached yet.

    ``app/bootstrap.py`` belongs to the developer and may have been edited, so
    Sillo Start does not rewrite it. Checking whether the wiring is already
    there means the instruction only appears when it is actually needed.
    """
    bootstrap = root / "app" / "bootstrap.py"
    if not bootstrap.exists():
        return
    try:
        source = bootstrap.read_text(encoding="utf-8")
    except OSError:
        return
    if "app.inertia" in source:
        return

    console.blank()
    console.warning("One manual step: attach the adapter in app/bootstrap.py.")
    console.blank()
    console.hint("Inside create_app(), after the routes are mounted, add:")
    console.blank()
    console.code(
        "from app.inertia import inertia\n\n"
        "    inertia.middleware(application)",
        language="python",
    )


def build_plan(
    root: Path,
    manifest: SilloManifest,
    *,
    adapter: InertiaAdapter,
    install: bool = True,
) -> ExecutionPlan:
    """Build the plan that installs Inertia."""
    engine = default_engine
    frontend = manifest.inertia.frontend_path
    extension = INERTIA_PAGE_EXTENSIONS[adapter]
    entry = INERTIA_ENTRY_FILES[adapter]

    context = build_context(
        manifest,
        adapter=adapter.value,
        entry=entry,
        extension=extension,
        frontend=frontend,
    )

    plan = ExecutionPlan(f"Add Inertia ({adapter})")

    # The Python side first: sillo-inertia plus the templating extra.
    resolution = resolve(["inertia"], installed=manifest.packages.groups)
    if resolution.groups:
        plan.extend(
            build_install_plan(resolution, manifest, install=install, title="Inertia packages").operations
        )

    for directory in (
        "templates",
        f"{frontend}/src/pages",
        f"{frontend}/src/layouts",
        f"{frontend}/src/components",
        f"{frontend}/public",
    ):
        plan.add(CreateDirectory(directory))

    # Backend wiring.
    plan.add(
        CreateFile(
            "app/inertia.py",
            engine.render("inertia/adapter.py.j2", context),
            skip_if_exists=True,
        )
    )
    plan.add(
        CreateFile(
            manifest.inertia.root_view,
            engine.render("inertia/root.html.j2", context),
            skip_if_exists=True,
        )
    )

    # Frontend project.
    plan.add(
        CreateFile(
            f"{frontend}/package.json",
            _package_json(manifest, adapter),
            skip_if_exists=True,
        )
    )
    plan.add(
        CreateFile(
            f"{frontend}/vite.config.ts",
            engine.render("inertia/vite.config.ts.j2", context),
            skip_if_exists=True,
        )
    )
    plan.add(
        CreateFile(
            f"{frontend}/tsconfig.json",
            _tsconfig(adapter),
            skip_if_exists=True,
        )
    )
    plan.add(
        CreateFile(
            f"{frontend}/{entry}",
            engine.render(f"inertia/{adapter.value}/main.j2", context),
            skip_if_exists=True,
        )
    )
    plan.add(
        CreateFile(
            f"{frontend}/src/pages/Home.{extension}",
            engine.render(f"inertia/{adapter.value}/page.j2", context),
            skip_if_exists=True,
        )
    )
    plan.add(
        CreateFile(
            f"{frontend}/src/layouts/AppLayout.{extension}",
            engine.render(f"inertia/{adapter.value}/layout.j2", context),
            skip_if_exists=True,
        )
    )

    plan.add(
        UpdateManifest(
            lambda m: _configure(m, adapter),
            description=f"record the Inertia frontend ({adapter}) in sillo.toml",
        )
    )

    if install:
        manager = frontend_manager(str(manifest.inertia.package_manager))
        plan.add(
            RunCommand(
                manager.install_command(),
                description=f"install frontend dependencies with {manager.name}",
                cwd=frontend,
                timeout=900,
                optional=True,
            )
        )

    return plan


def _configure(manifest: SilloManifest, adapter: InertiaAdapter) -> None:
    """Record the Inertia configuration in the manifest."""
    manifest.inertia.enabled = True
    manifest.inertia.adapter = adapter
    manifest.add_group("inertia")
    manager = FrontendPackageManager(manifest.inertia.package_manager)
    manifest.development.frontend_command = f"{manager.value} run dev"


def _package_json(manifest: SilloManifest, adapter: InertiaAdapter) -> str:
    """Build the frontend ``package.json``.

    Versions are left to the package manager to resolve rather than pinned
    here — a scaffolding tool that hard-codes React's version is out of date
    the week after it ships.
    """
    packages = INERTIA_FRONTEND_PACKAGES[adapter]
    data = {
        "name": f"{manifest.project.name}-frontend",
        "private": True,
        "type": "module",
        "scripts": {
            "dev": f"vite --port {manifest.inertia.port}",
            "build": "vite build",
            "preview": "vite preview",
        },
        "dependencies": {name: "latest" for name in packages["dependencies"]},
        "devDependencies": {name: "latest" for name in packages["devDependencies"]},
    }
    return json.dumps(data, indent=2)


def _tsconfig(adapter: InertiaAdapter) -> str:
    """Build a TypeScript configuration for the chosen adapter."""
    compiler_options = {
        "target": "ES2022",
        "module": "ESNext",
        "moduleResolution": "bundler",
        "strict": True,
        "esModuleInterop": True,
        "skipLibCheck": True,
        "resolveJsonModule": True,
        "isolatedModules": True,
        "noEmit": True,
        "lib": ["ES2022", "DOM", "DOM.Iterable"],
        "types": ["vite/client"],
        "baseUrl": ".",
        "paths": {"@/*": ["./src/*"]},
    }
    if adapter is InertiaAdapter.REACT:
        compiler_options["jsx"] = "react-jsx"

    return json.dumps(
        {"compilerOptions": compiler_options, "include": ["src"]},
        indent=2,
    )
