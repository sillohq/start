"""Structure-preserving TOML reading and writing.

``pyproject.toml`` and ``sillo.toml`` both belong to the developer, so edits go
through :mod:`tomlkit`, which keeps comments, key order and formatting intact.
Rewriting those files from a plain dict would silently discard anything the
developer added, which is exactly the kind of destructive edit Sillo Start
promises not to make.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import tomlkit
from tomlkit import TOMLDocument
from tomlkit.items import Array, Table

from ..exceptions import OperationError


def parse(text: str) -> TOMLDocument:
    """Parse TOML text into an editable document.

    Raises:
        OperationError: If the text is not valid TOML.
    """
    try:
        return tomlkit.parse(text)
    except Exception as exc:  # tomlkit raises several unrelated parse errors
        raise OperationError(f"Invalid TOML: {exc}") from exc


def load(path: Path) -> TOMLDocument:
    """Load *path* as an editable TOML document.

    Raises:
        OperationError: If the file is missing or malformed.
    """
    if not path.exists():
        raise OperationError(f"TOML file not found: {path}")
    try:
        return parse(path.read_text(encoding="utf-8"))
    except OperationError as exc:
        raise OperationError(f"Invalid TOML in {path}: {exc.message}") from exc


def dump(document: TOMLDocument) -> str:
    """Render a document back to text."""
    return tomlkit.dumps(document)


def save(path: Path, document: TOMLDocument) -> None:
    """Write a document to *path*, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump(document), encoding="utf-8")


def get_path(document: Any, dotted: str, default: Any = None) -> Any:
    """Read a nested value by dotted key, e.g. ``"project.dependencies"``."""
    node: Any = document
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def ensure_table(document: TOMLDocument, dotted: str) -> Table:
    """Return the table at *dotted*, creating intermediate tables as needed.

    Tables created here are marked as super-tables where appropriate so that
    ``tool.ruff.lint`` renders as one dotted header rather than a chain of
    empty sections.
    """
    node: Any = document
    parts = dotted.split(".")
    for index, part in enumerate(parts):
        if part not in node:
            table = tomlkit.table(is_super_table=index < len(parts) - 1)
            node[part] = table
        node = node[part]
        if not isinstance(node, dict):
            raise OperationError(
                f"Cannot create table '{dotted}': '{part}' is already a value."
            )
    return node  # type: ignore[return-value]


def set_path(document: TOMLDocument, dotted: str, value: Any) -> None:
    """Assign a nested value by dotted key, creating parent tables."""
    parts = dotted.split(".")
    if len(parts) == 1:
        document[parts[0]] = value
        return
    table = ensure_table(document, ".".join(parts[:-1]))
    table[parts[-1]] = value


def add_to_array(
    document: TOMLDocument,
    dotted: str,
    values: list[str],
    *,
    multiline: bool = True,
) -> list[str]:
    """Add string entries to a TOML array, skipping ones already present.

    Args:
        document: Document to modify in place.
        dotted: Dotted path of the array, e.g. ``"project.dependencies"``.
        values: Entries to add.
        multiline: Render the array one entry per line, which keeps dependency
            lists reviewable in diffs.

    Returns:
        The entries that were actually added.
    """
    parts = dotted.split(".")
    parent = ensure_table(document, ".".join(parts[:-1])) if len(parts) > 1 else document
    key = parts[-1]

    existing = parent.get(key)
    if existing is None:
        array = tomlkit.array()
        array.multiline(multiline)
        parent[key] = array
        existing = parent[key]
    elif not isinstance(existing, (list, Array)):
        raise OperationError(f"Cannot append to '{dotted}': it is not an array.")

    present = {_requirement_name(str(item)) for item in existing}
    added: list[str] = []
    for value in values:
        if _requirement_name(value) in present:
            continue
        existing.append(value)
        present.add(_requirement_name(value))
        added.append(value)
    return added


def remove_from_array(document: TOMLDocument, dotted: str, values: list[str]) -> list[str]:
    """Remove entries from a TOML array by requirement name.

    Matching ignores version specifiers so ``remove(["redis"])`` also removes
    ``redis>=5.0.0``.

    Returns:
        The entries that were removed.
    """
    array = get_path(document, dotted)
    if array is None:
        return []
    targets = {_requirement_name(value) for value in values}
    removed: list[str] = []
    for item in list(array):
        if _requirement_name(str(item)) in targets:
            array.remove(item)
            removed.append(str(item))
    return removed


def _requirement_name(requirement: str) -> str:
    """Extract the bare distribution name from a PEP 508 requirement string.

    ``sillo-framework[record]>=0.1`` -> ``sillo-framework``. Extras and version
    specifiers are dropped so that presence checks compare like with like, and
    the name is normalised per PEP 503 so ``sillo_start`` and ``sillo-start``
    are recognised as the same distribution.
    """
    text = requirement.strip()
    for separator in ("[", ";", "=", ">", "<", "!", "~", " ", "@"):
        index = text.find(separator)
        if index > 0:
            text = text[:index]
    return text.strip().lower().replace("_", "-")
