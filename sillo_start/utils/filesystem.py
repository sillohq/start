"""Filesystem helpers with safety rails.

Sillo Start writes into directories that contain user code, so every helper
here is conservative by default: writes refuse to clobber an existing file
unless overwriting is explicitly requested, and destructive edits capture the
previous bytes so a transaction can put them back.
"""

from __future__ import annotations

import difflib
import os
import shutil
from collections.abc import Iterable
from pathlib import Path

from ..exceptions import OperationError

#: Directory entries that do not make a directory "occupied" for our purposes.
_IGNORABLE_ENTRIES = {".git", ".DS_Store", ".idea", ".vscode", "__pycache__"}


def is_empty_dir(path: Path) -> bool:
    """Report whether *path* is absent, or present but effectively empty."""
    if not path.exists():
        return True
    if not path.is_dir():
        return False
    return all(entry.name in _IGNORABLE_ENTRIES for entry in path.iterdir())


def ensure_dir(path: Path) -> Path:
    """Create *path* and its parents if needed, returning it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_text(path: Path) -> str:
    """Read UTF-8 text, raising :class:`OperationError` with the path on failure."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise OperationError(f"File not found: {path}") from exc
    except UnicodeDecodeError as exc:
        raise OperationError(f"File is not valid UTF-8 text: {path}") from exc


def write_text(path: Path, content: str, *, overwrite: bool = False) -> None:
    """Write UTF-8 text, creating parent directories as needed.

    Args:
        path: Destination file.
        content: Text to write.
        overwrite: When false (the default) an existing file is an error rather
            than being silently replaced.

    Raises:
        OperationError: If the file exists and *overwrite* is false.
    """
    if path.exists() and not overwrite:
        raise OperationError(
            f"Refusing to overwrite existing file: {path}",
            hint="Pass --force to replace it, or remove the file first.",
        )
    ensure_dir(path.parent)
    # Normalise to a trailing newline so generated files are POSIX-clean.
    if content and not content.endswith("\n"):
        content += "\n"
    path.write_text(content, encoding="utf-8")


def append_text(path: Path, content: str) -> None:
    """Append text to a file, creating it when missing."""
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(content)


def remove(path: Path) -> None:
    """Delete a file or directory tree, tolerating absence."""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists() or path.is_symlink():
        path.unlink(missing_ok=True)


def copy_tree(source: Path, destination: Path) -> None:
    """Recursively copy *source* into *destination*, merging with what is there."""
    shutil.copytree(source, destination, dirs_exist_ok=True)


def is_writable(path: Path) -> bool:
    """Report whether *path* can be written to.

    For a directory this tests the directory itself; for a file that does not
    exist yet it tests the nearest existing parent, which is what actually
    governs whether the write will succeed.
    """
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return os.access(probe, os.W_OK)


def relative_to_cwd(path: Path) -> str:
    """Render *path* relative to the working directory when that is shorter."""
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def unified_diff(before: str, after: str, *, path: str) -> str:
    """Build a unified diff between two versions of a file.

    Returns an empty string when the contents are identical, which callers use
    to skip no-op edits.
    """
    if before == after:
        return ""
    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(lines)


def iter_files(root: Path, *, skip_dirs: Iterable[str] = ()) -> Iterable[Path]:
    """Walk *root* yielding files, skipping the named directories.

    Args:
        root: Directory to walk.
        skip_dirs: Directory names pruned anywhere in the tree.
    """
    skip = set(skip_dirs) | {"__pycache__", ".git", "node_modules", ".venv"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in skip]
        for filename in filenames:
            yield Path(dirpath) / filename
