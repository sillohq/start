"""Component generators.

A generator turns a name into files inside an existing project. Like every
other mutation in Sillo Start, it produces operations rather than writing
directly, so ``--dry-run`` works and a partial failure rolls back.

Generators are data plus a template mapping wherever possible. The model
generator is the exception: it accepts a field specification and needs real
logic, so it overrides :meth:`plan`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..config.models import SilloManifest
from ..exceptions import GeneratorError
from ..operations.base import Operation
from ..operations.files import CreateFile
from ..templating import TemplateEngine, build_context
from ..templating import engine as default_engine
from ..utils import naming

if TYPE_CHECKING:
    pass


@dataclass
class GeneratorTarget:
    """One file a generator produces.

    Args:
        template: Template path.
        destination: Destination pattern. ``{snake}``, ``{pascal}``,
            ``{kebab}`` and ``{plural}`` are substituted from the name.
        when: Optional dotted manifest condition, as on blueprint files.
    """

    template: str
    destination: str
    when: str | None = None


@dataclass
class Generator:
    """Scaffolds one kind of component.

    Args:
        name: Subcommand name, e.g. ``model``.
        summary: One-line help text.
        targets: Files produced.
        suffix: Appended to the given name if absent — ``UserController``.
        requires: Manifest conditions that must hold, as dotted paths.
        directories: Directories that must exist first.
    """

    name: str
    summary: str
    targets: tuple[GeneratorTarget, ...] = ()
    suffix: str = ""
    requires: tuple[str, ...] = ()
    directories: tuple[str, ...] = ()

    def normalise(self, raw_name: str) -> str:
        """Convert user input into the canonical component name.

        Raises:
            GeneratorError: If the name cannot form a Python identifier.
        """
        pascal = naming.to_pascal(raw_name)
        if not pascal:
            raise GeneratorError(f"'{raw_name}' is not a usable name.")
        if self.suffix:
            pascal = naming.ensure_suffix(pascal, self.suffix)
        if not naming.is_valid_python_identifier(pascal):
            raise GeneratorError(
                f"'{pascal}' is not a valid Python identifier.",
                hint="Use letters, digits and underscores, starting with a letter.",
            )
        return pascal

    def check_requirements(self, manifest: SilloManifest) -> None:
        """Verify the project supports this generator.

        Raises:
            GeneratorError: If a required feature is not enabled.
        """
        for requirement in self.requires:
            value: Any = manifest
            for part in requirement.split("."):
                value = getattr(value, part, False)
            if not value:
                raise GeneratorError(
                    f"`generate {self.name}` needs '{requirement}' to be enabled.",
                    hint="Enable it first, for example with `sillo-start add`.",
                )

    def substitutions(self, name: str) -> dict[str, str]:
        """Build the name variants available to templates and paths."""
        return {
            "name": name,
            "pascal": naming.to_pascal(name),
            "snake": naming.to_snake(name),
            "camel": naming.to_camel(name),
            "kebab": naming.to_kebab(name),
            "plural": naming.pluralize(naming.to_snake(name)),
            "table": naming.table_name(name),
            "human": naming.to_human(name),
            "title": naming.to_title(name),
        }

    def context(self, name: str, manifest: SilloManifest, **extra: Any) -> dict[str, Any]:
        """Build the rendering context for this component."""
        return build_context(manifest, **self.substitutions(name), **extra)

    def plan(
        self,
        name: str,
        manifest: SilloManifest,
        *,
        engine: TemplateEngine | None = None,
        force: bool = False,
        **options: Any,
    ) -> list[Operation]:
        """Build the operations that create this component."""
        renderer = engine or default_engine
        context = self.context(name, manifest, **options)
        substitutions = self.substitutions(name)

        operations: list[Operation] = []
        for target in self.targets:
            if target.when and not _condition_holds(manifest, target.when):
                continue
            destination = target.destination.format(**substitutions)
            operations.append(
                CreateFile(
                    destination,
                    renderer.render(target.template, context),
                    skip_if_exists=not force,
                    overwrite=force,
                )
            )
        return operations

    def describe_output(self, name: str, manifest: SilloManifest) -> list[str]:
        """List the files this generator would create, for reporting."""
        substitutions = self.substitutions(name)
        return [
            target.destination.format(**substitutions)
            for target in self.targets
            if not target.when or _condition_holds(manifest, target.when)
        ]


def _condition_holds(manifest: SilloManifest, expression: str) -> bool:
    """Evaluate a dotted manifest condition, honouring a leading ``!``."""
    negate = expression.startswith("!")
    if negate:
        expression = expression[1:]
    value: Any = manifest
    for part in expression.split("."):
        value = getattr(value, part, False)
    return (not bool(value)) if negate else bool(value)
