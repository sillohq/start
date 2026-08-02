"""The model generator.

Models are the one component where a name alone is not enough — a model has
fields, and typing them out afterwards is the tedious part. This generator
accepts a compact field syntax and can additionally register the model in the
models package, which is required for the ORM to see it at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config.models import SilloManifest
from ..exceptions import GeneratorError
from ..operations.base import Operation
from ..operations.files import CreateFile, UpdateMarkerSection
from ..templating import TemplateEngine
from ..templating import engine as default_engine
from ..utils import filesystem as fs
from ..utils import naming
from .base import Generator, GeneratorTarget

#: Field types the compact syntax accepts, mapped to their Tortoise field.
#: Kept as a table so `generate model --help` can list exactly what is valid.
FIELD_TYPES: dict[str, str] = {
    "str": "fields.CharField(max_length={max_length})",
    "text": "fields.TextField()",
    "int": "fields.IntField()",
    "bigint": "fields.BigIntField()",
    "float": "fields.FloatField()",
    "decimal": "fields.DecimalField(max_digits=12, decimal_places=2)",
    "bool": "fields.BooleanField()",
    "date": "fields.DateField()",
    "datetime": "fields.DatetimeField()",
    "time": "fields.TimeField()",
    "json": "fields.JSONField()",
    "uuid": "fields.UUIDField()",
    "email": "fields.CharField(max_length=255)",
    "url": "fields.CharField(max_length=2048)",
    "slug": "fields.CharField(max_length=255)",
}

#: Relationship kinds, mapped to their Tortoise constructor.
RELATION_TYPES = {
    "fk": "fields.ForeignKeyField('models.{target}', related_name='{related}')",
    "o2o": "fields.OneToOneField('models.{target}', related_name='{related}')",
    "m2m": "fields.ManyToManyField('models.{target}', related_name='{related}')",
}

DEFAULT_MAX_LENGTH = 255


@dataclass
class FieldSpec:
    """One parsed field declaration."""

    name: str
    kind: str
    nullable: bool = False
    unique: bool = False
    indexed: bool = False
    default: str | None = None
    max_length: int = DEFAULT_MAX_LENGTH
    target: str | None = None
    #: The model this field belongs to, needed to name the reverse accessor.
    owner: str = ""

    def render(self) -> str:
        """Render the field as a line of Tortoise model source."""
        if self.kind in RELATION_TYPES:
            if not self.target:
                raise GeneratorError(
                    f"Relationship field '{self.name}' needs a target, "
                    f"e.g. {self.name}:fk:Author"
                )
            # related_name is how the *target* reaches back, so it is named for
            # the owning model: Post.author -> User gives `user.posts`, not
            # `user.authors`.
            related = naming.pluralize(naming.to_snake(self.owner or self.name))
            expression = RELATION_TYPES[self.kind].format(
                target=naming.to_pascal(self.target), related=related
            )
        else:
            expression = FIELD_TYPES[self.kind].format(max_length=self.max_length)

        arguments = []
        if self.nullable:
            arguments.append("null=True")
        if self.unique:
            arguments.append("unique=True")
        if self.indexed and not self.unique:
            arguments.append("db_index=True")
        if self.default is not None:
            arguments.append(f"default={self.default}")

        if arguments:
            # Splice the extra arguments in before the closing parenthesis.
            expression = expression[:-1] + (", " if not expression.endswith("()") else "")
            expression += ", ".join(arguments) + ")"
        return f"{self.name} = {expression}"

    @property
    def python_type(self) -> str:
        """The annotation used in generated schemas."""
        mapping = {
            "str": "str",
            "text": "str",
            "email": "str",
            "url": "str",
            "slug": "str",
            "int": "int",
            "bigint": "int",
            "float": "float",
            "decimal": "Decimal",
            "bool": "bool",
            "date": "date",
            "datetime": "datetime",
            "time": "time",
            "json": "dict",
            "uuid": "UUID",
        }
        base = mapping.get(self.kind, "int" if self.kind in RELATION_TYPES else "str")
        return f"{base} | None" if self.nullable else base


def parse_fields(specs: list[str], *, owner: str = "") -> list[FieldSpec]:
    """Parse the compact field syntax.

    The syntax is ``name:type`` with optional flags, e.g.::

        title:str:unique
        body:text:null
        views:int:default=0
        author:fk:Author
        email:str:unique:index

    Args:
        specs: Raw ``name:type[:flag...]`` strings.
        owner: The model these fields belong to, used to name reverse
            accessors on relationships.

    Returns:
        The parsed field specifications.

    Raises:
        GeneratorError: On an unknown type or malformed declaration, naming the
            offending declaration and listing the valid types.
    """
    fields_out: list[FieldSpec] = []

    for raw in specs:
        parts = raw.split(":")
        if len(parts) < 2:
            raise GeneratorError(
                f"Malformed field: '{raw}'",
                hint="Use name:type, for example title:str or author:fk:Author.",
            )

        name, kind, *flags = parts
        name = naming.to_snake(name)
        kind = kind.lower()

        if kind not in FIELD_TYPES and kind not in RELATION_TYPES:
            known = ", ".join([*sorted(FIELD_TYPES), *sorted(RELATION_TYPES)])
            raise GeneratorError(f"Unknown field type '{kind}' in '{raw}'.", hint=f"Valid types: {known}.")

        spec = FieldSpec(name=name, kind=kind, owner=owner)

        # A relationship's first flag is its target model.
        if kind in RELATION_TYPES and flags and "=" not in flags[0] and flags[0] not in (
            "null",
            "unique",
            "index",
        ):
            spec.target = flags.pop(0)

        for flag in flags:
            lowered = flag.lower()
            if lowered in ("null", "nullable", "optional"):
                spec.nullable = True
            elif lowered == "unique":
                spec.unique = True
            elif lowered in ("index", "indexed"):
                spec.indexed = True
            elif lowered.startswith("default="):
                spec.default = flag.split("=", 1)[1]
            elif lowered.startswith("max="):
                spec.max_length = int(flag.split("=", 1)[1])
            else:
                raise GeneratorError(
                    f"Unknown flag '{flag}' in '{raw}'.",
                    hint="Valid flags: null, unique, index, default=<value>, max=<n>.",
                )

        fields_out.append(spec)

    return fields_out


@dataclass
class ModelGenerator(Generator):
    """Generates a Record model, and optionally its companions."""

    name: str = "model"
    summary: str = "A Record ORM model, with optional schema, repository and tests."
    requires: tuple[str, ...] = ("uses_record",)
    targets: tuple[GeneratorTarget, ...] = field(
        default=(GeneratorTarget("generators/model.py.j2", "database/models/{snake}.py"),),
        repr=False,
    )

    def plan(
        self,
        name: str,
        manifest: SilloManifest,
        *,
        engine: TemplateEngine | None = None,
        force: bool = False,
        **options: Any,
    ) -> list[Operation]:
        """Build the operations for a model and its selected companions."""
        renderer = engine or default_engine
        specs = parse_fields(options.get("fields") or [], owner=name)

        context = self.context(
            name,
            manifest,
            fields=specs,
            timestamps=options.get("timestamps", True),
            soft_deletes=options.get("soft_deletes", False),
            needs_decimal=any(f.kind == "decimal" for f in specs),
            needs_date=any(f.kind in ("date", "datetime", "time") for f in specs),
            needs_uuid=any(f.kind == "uuid" for f in specs),
        )
        substitutions = self.substitutions(name)

        operations: list[Operation] = [
            CreateFile(
                f"database/models/{substitutions['snake']}.py",
                renderer.render("generators/model.py.j2", context),
                skip_if_exists=not force,
                overwrite=force,
            )
        ]

        # Registering the model is not optional in practice: the ORM discovers
        # models through this package, so one that is not imported here simply
        # does not exist as far as the database is concerned.
        operations.append(self._registration_operation(name, manifest))

        if options.get("schema", True):
            operations.append(
                CreateFile(
                    f"app/http/requests/{substitutions['snake']}.py",
                    renderer.render("generators/schema.py.j2", context),
                    skip_if_exists=not force,
                    overwrite=force,
                )
            )
        if options.get("repository"):
            operations.append(
                CreateFile(
                    f"app/repositories/{substitutions['snake']}_repository.py",
                    renderer.render("generators/repository.py.j2", context),
                    skip_if_exists=not force,
                    overwrite=force,
                )
            )
        if options.get("controller"):
            operations.append(
                CreateFile(
                    f"app/http/controllers/{substitutions['snake']}_controller.py",
                    renderer.render("generators/controller.py.j2", context),
                    skip_if_exists=not force,
                    overwrite=force,
                )
            )
        if options.get("tests", True) and manifest.tooling.pytest:
            operations.append(
                CreateFile(
                    f"tests/unit/test_{substitutions['snake']}.py",
                    renderer.render("generators/model_test.py.j2", context),
                    skip_if_exists=not force,
                    overwrite=force,
                )
            )
        return operations

    def _registration_operation(self, name: str, manifest: SilloManifest) -> Operation:
        """Build the edit that adds the model to the models package.

        The import block is fenced with markers so the file can be rewritten
        for each new model without disturbing anything the developer added
        around it.
        """
        from pathlib import Path

        pascal = naming.to_pascal(name)
        snake = naming.to_snake(name)
        models_init = Path("database/models/__init__.py")

        existing = self._existing_models(models_init, manifest)
        if pascal not in existing:
            existing.append(pascal)

        imports = "\n".join(
            f"from database.models.{naming.to_snake(model)} import {model}"
            for model in sorted(existing)
        )
        registry = ", ".join(sorted(existing))
        body = f"{imports}\n\n__models__ = [{registry}]\n\n__all__ = {sorted(existing)!r}"

        _ = snake  # the import line is derived from the sorted list above
        return UpdateMarkerSection(str(models_init), "models", body)

    @staticmethod
    def _existing_models(models_init, manifest: SilloManifest) -> list[str]:
        """Read the models already registered in the package.

        Parsed from the ``__all__`` list rather than by importing the package,
        which would require the project's dependencies to be installed.
        """
        from pathlib import Path

        path = Path.cwd() / models_init
        if not path.exists():
            return []
        try:
            source = fs.read_text(path)
        except Exception:  # noqa: BLE001 — an unreadable file just means "none yet"
            return []

        import ast

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        try:
                            value = ast.literal_eval(node.value)
                        except ValueError:
                            continue
                        if isinstance(value, (list, tuple)):
                            return [str(item) for item in value]
        return []
