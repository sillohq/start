"""Jinja2 rendering for generated project files.

Templates live under ``sillo_start/templates`` as ``.j2`` files and are
rendered against a context derived from the manifest, so a template asks
``{% if manifest.auth.enabled %}`` rather than being handed a pile of loose
booleans. Plugins can prepend their own directory, which is also how a project
overrides a built-in template.

Autoescaping is off: the output is Python, TOML and TypeScript source, where
escaping ``&`` and ``<`` would corrupt the result. The HTML root view is the one
exception and contains no user-controlled interpolation.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, StrictUndefined
from jinja2 import TemplateNotFound as JinjaTemplateNotFound

from .exceptions import GeneratorError
from .utils import naming

#: Directory holding the built-in templates.
TEMPLATE_ROOT = Path(__file__).parent / "templates"


class TemplateEngine:
    """Renders project templates.

    Undefined variables raise rather than rendering as empty text. A template
    that silently drops a name produces a file that looks fine and fails at
    import time in the user's project — far more expensive to diagnose than a
    loud failure here.
    """

    def __init__(self, extra_dirs: Sequence[Path] = ()) -> None:
        """
        Args:
            extra_dirs: Directories searched before the built-ins, letting a
                plugin or a project override any template by path.
        """
        loaders = [FileSystemLoader(str(directory)) for directory in extra_dirs]
        loaders.append(FileSystemLoader(str(TEMPLATE_ROOT)))
        self.environment = Environment(
            loader=ChoiceLoader(loaders),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
            autoescape=False,
        )
        self._install_filters()

    def _install_filters(self) -> None:
        """Expose the naming helpers so templates can reshape a name inline."""
        self.environment.filters.update(
            snake=naming.to_snake,
            pascal=naming.to_pascal,
            camel=naming.to_camel,
            kebab=naming.to_kebab,
            title_case=naming.to_title,
            human=naming.to_human,
            plural=naming.pluralize,
            table=naming.table_name,
        )

    def render(self, template: str, context: dict[str, Any]) -> str:
        """Render *template* with *context*.

        Raises:
            GeneratorError: If the template is missing or fails to render.
        """
        try:
            return self.environment.get_template(template).render(**context)
        except JinjaTemplateNotFound as exc:
            raise GeneratorError(
                f"Template not found: {template}",
                hint="This is a bug in Sillo Start or in a plugin that overrode the template.",
            ) from exc
        except Exception as exc:
            raise GeneratorError(f"Failed to render template '{template}': {exc}") from exc

    def render_string(self, source: str, context: dict[str, Any]) -> str:
        """Render a template given as a string, for inline snippets."""
        try:
            return self.environment.from_string(source).render(**context)
        except Exception as exc:
            raise GeneratorError(f"Failed to render inline template: {exc}") from exc

    def exists(self, template: str) -> bool:
        """Report whether *template* can be loaded."""
        try:
            self.environment.get_template(template)
            return True
        except JinjaTemplateNotFound:
            return False


def build_context(manifest, **extra: Any) -> dict[str, Any]:
    """Build the rendering context for a project's templates.

    Every template receives the manifest plus a handful of derived values that
    would otherwise be recomputed in each one — the app class name, the entry
    module, whether any Redis-backed feature is on.

    Args:
        manifest: The project manifest.
        **extra: Additional values, which override the derived ones.

    Returns:
        The context dictionary.
    """
    context: dict[str, Any] = {
        "manifest": manifest,
        "project": manifest.project,
        "app": manifest.application,
        "database": manifest.database,
        "auth": manifest.auth,
        "authorization": manifest.authorization,
        "admin": manifest.admin,
        "inertia": manifest.inertia,
        "queue": manifest.queue,
        "scheduler": manifest.scheduler,
        "cache": manifest.cache,
        "session": manifest.session,
        "mail": manifest.mail,
        "storage": manifest.storage,
        "api": manifest.api,
        "tooling": manifest.tooling,
        "packages": manifest.packages,
        "development": manifest.development,
        # Derived conveniences.
        "name": manifest.project.name,
        "package": manifest.project.package,
        "class_name": naming.to_pascal(manifest.project.name),
        "title": naming.to_title(manifest.project.name),
        "uses_record": manifest.uses_record,
        "uses_sessions": manifest.uses_sessions,
        "needs_redis": manifest.needs_redis,
        "needs_database_server": manifest.needs_database_server,
        "needs_web_routes": manifest.needs_web_routes,
        "groups": manifest.packages.groups,
    }
    context.update(extra)
    return context


#: Shared engine using only the built-in templates.
engine = TemplateEngine()
