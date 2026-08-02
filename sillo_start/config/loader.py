"""Finding, reading and validating the project manifest.

The manifest normally lives under ``[tool.sillo]`` in ``pyproject.toml``, which
is where Python tooling keeps its configuration and avoids restating the
project's name and version in a second file. A standalone ``sillo.toml`` is
still read when there is no ``pyproject.toml`` — a project that is not a Python
distribution has nowhere else to put it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from ..exceptions import ManifestError, ManifestNotFoundError
from ..utils import toml_io
from .models import SilloManifest

MANIFEST_FILENAME = "sillo.toml"
PYPROJECT_FILENAME = "pyproject.toml"

#: Manifest ``project`` fields that restate ``[project]`` in pyproject.toml.
#: They are read from there rather than duplicated, so the two cannot drift.
SHARED_PROJECT_FIELDS = {
    "name": "name",
    "version": "version",
    "description": "description",
    "python": "requires-python",
}


def _tool_table(path: Path) -> dict[str, Any] | None:
    """Return ``[tool.sillo]`` from a pyproject, or None when it is absent."""
    try:
        document = toml_io.load(path)
    except Exception:
        # An unparseable pyproject is not this function's problem to report;
        # treat it as "no manifest here" and let the search continue.
        return None
    tool = document.get("tool")
    if not isinstance(tool, dict):
        return None
    section = tool.get("sillo")
    return section if isinstance(section, dict) else None


def find_manifest(start: Path | None = None) -> Path | None:
    """Search *start* and its parents for a project manifest.

    Walking upward lets every command work from anywhere inside a project,
    the way ``git`` does. Within a single directory ``pyproject.toml`` wins,
    but only when it actually carries a ``[tool.sillo]`` table — otherwise a
    project keeping its manifest in ``sillo.toml`` alongside an ordinary
    ``pyproject.toml`` would never be found.

    Args:
        start: Directory to search from. Defaults to the working directory.

    Returns:
        The path to the manifest file, or ``None`` when no project encloses
        *start*.
    """
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        pyproject = directory / PYPROJECT_FILENAME
        if pyproject.is_file() and _tool_table(pyproject) is not None:
            return pyproject
        standalone = directory / MANIFEST_FILENAME
        if standalone.is_file():
            return standalone
    return None


def require_manifest_path(start: Path | None = None) -> Path:
    """Locate ``sillo.toml`` or fail with an actionable message.

    Raises:
        ManifestNotFoundError: If no manifest encloses *start*.
    """
    path = find_manifest(start)
    if path is None:
        raise ManifestNotFoundError()
    return path


def load_manifest(path: Path) -> SilloManifest:
    """Read and validate a manifest.

    Raises:
        ManifestError: If the file is missing, malformed, or fails validation.
    """
    if not path.is_file():
        raise ManifestError(
            f"Manifest not found: {path}",
            hint="Run `sillo-start create <name>` to generate a project.",
        )
    document = toml_io.load(path)
    data = _manifest_data(path, document)
    try:
        return SilloManifest.from_dict(data)
    except PydanticValidationError as exc:
        raise ManifestError(
            f"{path} is not a valid Sillo manifest:\n{_format_errors(exc)}",
            hint="Fix the reported fields, or run `sillo-start doctor` for a full check.",
        ) from exc


def load_project(start: Path | None = None) -> tuple[Path, SilloManifest]:
    """Locate the enclosing project and load its manifest.

    Returns:
        The project root directory and its parsed manifest.

    Raises:
        ManifestNotFoundError: If *start* is not inside a Sillo project.
        ManifestError: If the manifest is invalid.
    """
    path = require_manifest_path(start)
    return path.parent, load_manifest(path)


def _manifest_data(path: Path, document: Any) -> dict[str, Any]:
    """Extract the manifest mapping from a loaded TOML document.

    For a pyproject, the manifest is ``[tool.sillo]`` and the shared identity
    fields are filled in from ``[project]`` so they exist in exactly one place.
    """
    raw = document.unwrap()
    if path.name != PYPROJECT_FILENAME:
        return raw

    data = dict(raw.get("tool", {}).get("sillo", {}))
    if not data:
        raise ManifestError(
            f"{path} has no [tool.sillo] table.",
            hint="Run `sillo-start create <name>` to generate a project.",
        )

    pyproject_project = raw.get("project", {})
    manifest_project = dict(data.get("project", {}))
    for manifest_key, pyproject_key in SHARED_PROJECT_FIELDS.items():
        if manifest_key not in manifest_project and pyproject_key in pyproject_project:
            manifest_project[manifest_key] = pyproject_project[pyproject_key]
    data["project"] = manifest_project
    return data


def _format_errors(exc: PydanticValidationError) -> str:
    """Render Pydantic errors as readable ``section.field: message`` lines."""
    lines = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "(root)"
        lines.append(f"  {location}: {error['msg']}")
    return "\n".join(lines)
