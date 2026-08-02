"""Serialising a manifest back to ``sillo.toml``.

Writing goes through tomlkit rather than a plain dump so that an existing
manifest keeps its comments, key order and spacing. Only the keys that actually
changed are rewritten, which keeps ``sillo-start add`` diffs small enough to
review.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import tomlkit
from tomlkit import TOMLDocument

from ..utils import toml_io
from .models import SilloManifest

#: Section order in a freshly written manifest — identity first, then features,
#: then the tooling and run configuration.
SECTION_ORDER = [
    "project",
    "application",
    "database",
    "auth",
    "authorization",
    "admin",
    "inertia",
    "queue",
    "scheduler",
    "cache",
    "session",
    "mail",
    "storage",
    "api",
    "tooling",
    "packages",
    "development",
]

#: Sections that are omitted from a new manifest when the feature is switched
#: off, so a minimal project gets a manifest that is actually minimal. They are
#: still written once the feature is enabled.
OPTIONAL_SECTIONS = {
    "database",
    "auth",
    "authorization",
    "admin",
    "inertia",
    "queue",
    "scheduler",
    "cache",
    "session",
    "mail",
    "storage",
}

_HEADER = """\
# Sillo project manifest.
#
# This file is the source of truth for `sillo-start`. It records what the
# application is and which features are enabled, and drives `add`, `remove`,
# `dev`, `doctor` and `upgrade`. Edit it by hand if you like — the tool
# preserves your comments and formatting.
"""


def _normalise(manifest: SilloManifest) -> None:
    """Settle implied flags before the manifest is written.

    The manifest validator only runs on construction, but blueprints and the
    wizard flip section flags afterwards — so a rule like "the admin needs
    sessions" has to be re-applied here or ``sillo.toml`` would claim sessions
    are off while the generated app registers the middleware anyway.
    """
    if manifest.admin.enabled and not manifest.session.enabled:
        object.__setattr__(manifest.session, "enabled", True)


def render_manifest(manifest: SilloManifest) -> str:
    """Render a manifest as a new TOML document."""
    _normalise(manifest)
    document = tomlkit.parse(_HEADER)
    _apply(document, manifest, prune_disabled=True)
    return tomlkit.dumps(document)


def render_manifest_table(manifest: SilloManifest) -> str:
    """Render the manifest as a ``[tool.sillo.*]`` block for pyproject.toml.

    The shared identity fields are left out: pyproject already states the
    project's name, version, description and Python requirement in
    ``[project]``, and repeating them is how the two drift apart.
    """
    from .loader import SHARED_PROJECT_FIELDS

    _normalise(manifest)
    document = tomlkit.document()
    tool = tomlkit.table(is_super_table=True)
    sillo = tomlkit.table(is_super_table=True)
    tool["sillo"] = sillo
    document["tool"] = tool
    _apply(sillo, manifest, prune_disabled=True, skip_project=SHARED_PROJECT_FIELDS)
    return tomlkit.dumps(document)


def save_manifest(path: Path, manifest: SilloManifest) -> None:
    """Write *manifest* to *path*.

    An existing file is updated in place so hand-written comments survive; a
    missing one is created from the template header. Writing to a
    ``pyproject.toml`` targets its ``[tool.sillo]`` table and leaves the rest of
    the file — including ``[project]`` — untouched.
    """
    from .loader import PYPROJECT_FILENAME, SHARED_PROJECT_FIELDS

    if path.name == PYPROJECT_FILENAME:
        _normalise(manifest)
        document = toml_io.load(path)
        section = _tool_sillo_table(document)
        _apply(section, manifest, prune_disabled=False, skip_project=SHARED_PROJECT_FIELDS)
        toml_io.save(path, document)
        return

    if path.exists():
        _normalise(manifest)
        document = toml_io.load(path)
        _apply(document, manifest, prune_disabled=False)
        toml_io.save(path, document)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_manifest(manifest), encoding="utf-8")


def _tool_sillo_table(document: TOMLDocument):
    """Return the ``[tool.sillo]`` table, creating it when absent."""
    if "tool" not in document:
        document["tool"] = tomlkit.table(is_super_table=True)
    tool = document["tool"]
    if "sillo" not in tool:
        tool["sillo"] = tomlkit.table(is_super_table=True)
    return tool["sillo"]


#: Keys always written even when they equal the default, because their presence
#: is what makes a section readable at a glance.
ALWAYS_WRITE = {"enabled", "type", "driver", "strategy"}


def _section_defaults(manifest: SilloManifest, section: str) -> dict[str, Any]:
    """The default values for one section, or empty when it has no defaults.

    ``[project]`` is required and has no default instance, so everything in it
    is written — which is right, since it is the identifying section.
    """
    field = type(manifest).model_fields.get(section)
    factory = getattr(field, "default_factory", None) if field else None
    if factory is None:
        return {}
    # mode="json" so enums compare equal to the serialised values in to_dict().
    return factory().model_dump(mode="json", exclude_none=True)


def _apply(
    document: TOMLDocument,
    manifest: SilloManifest,
    *,
    prune_disabled: bool,
    skip_project: dict[str, str] | None = None,
) -> None:
    """Merge manifest values into *document* in place.

    Args:
        skip_project: Manifest ``project`` keys to leave out, because the
            destination already carries them — pyproject's own ``[project]``.
    """
    data = manifest.to_dict()
    for section in SECTION_ORDER:
        values = data.get(section)
        if values is None:
            continue
        if section == "project" and skip_project:
            values = {k: v for k, v in values.items() if k not in skip_project}
            if not values:
                continue
        if (
            prune_disabled
            and section in OPTIONAL_SECTIONS
            and not values.get("enabled", True)
        ):
            continue
        _merge_section(document, section, values, _section_defaults(manifest, section))

    # Sections a plugin added that are not part of the built-in order still
    # need to round-trip.
    for section, values in data.items():
        if section not in SECTION_ORDER and isinstance(values, dict):
            _merge_section(document, section, values)


def _merge_section(
    document: TOMLDocument,
    name: str,
    values: dict[str, Any],
    defaults: dict[str, Any] | None = None,
) -> None:
    """Write one section, creating it when absent and updating it when present.

    Keys still at their default are omitted from a section being created, so a
    new manifest records decisions rather than restating the defaults it did
    not change. A key already in the document is always written back, even at
    the default value — it was put there deliberately, and dropping it would
    silently rewrite someone's file.
    """
    defaults = defaults or {}
    if name not in document:
        table = tomlkit.table()
        for key, value in values.items():
            if key not in ALWAYS_WRITE and key in defaults and defaults[key] == value:
                continue
            table[key] = _to_toml(value)
        if not len(table):
            return
        document[name] = table
        return

    existing = document[name]
    for key, value in values.items():
        if (
            key not in existing
            and key not in ALWAYS_WRITE
            and key in defaults
            and defaults[key] == value
        ):
            continue
        existing[key] = _to_toml(value)


def _to_toml(value: Any) -> Any:
    """Convert a Python value into its TOML representation.

    ``None`` has no TOML spelling, so it becomes an empty string — the manifest
    models use empty strings rather than nulls for "unset" precisely so this
    conversion stays lossless in both directions. Lists of strings are rendered
    multiline, which keeps package-group edits readable in review.
    """
    if value is None:
        return ""
    if isinstance(value, dict):
        table = tomlkit.inline_table()
        for key, item in value.items():
            table[key] = _to_toml(item)
        return table
    if isinstance(value, (list, tuple)):
        array = tomlkit.array()
        for item in value:
            array.append(_to_toml(item))
        if len(value) > 3:
            array.multiline(True)
        return array
    return value
