"""Reading and updating ``.env`` files.

Adding a feature to an existing project usually means adding environment
variables, and doing that by appending blindly produces duplicate keys that
shadow each other. :class:`EnvFile` parses the file into ordered entries so a
variable can be added, updated or removed while preserving the comments and
blank lines the developer wrote around it.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path

_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")

#: Characters that force a value to be quoted when written back out.
_NEEDS_QUOTING = re.compile(r"[\s#\"'$`\\]")


@dataclass
class EnvVar:
    """One environment variable destined for a ``.env`` file."""

    key: str
    value: str
    comment: str | None = None
    #: Variables the user is expected to fill in are written commented-out
    #: in ``.env.example`` with a placeholder instead of a working default.
    secret: bool = False


@dataclass
class EnvFile:
    """An in-memory ``.env`` document that round-trips comments and layout.

    Lines are kept verbatim; only the lines for keys being changed are
    rewritten. That means re-running ``sillo-start add`` never reflows a file
    the developer has edited by hand.
    """

    lines: list[str] = field(default_factory=list)

    @classmethod
    def parse(cls, text: str) -> EnvFile:
        """Parse the contents of a ``.env`` file."""
        return cls(lines=text.splitlines())

    @classmethod
    def load(cls, path: Path) -> EnvFile:
        """Load from *path*, returning an empty document when absent."""
        if not path.exists():
            return cls()
        return cls.parse(path.read_text(encoding="utf-8"))

    def render(self) -> str:
        """Render back to text with a trailing newline."""
        body = "\n".join(self.lines).rstrip("\n")
        return body + "\n" if body else ""

    def save(self, path: Path) -> None:
        """Write the document to *path*."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render(), encoding="utf-8")

    # -- reading -------------------------------------------------------

    def keys(self) -> list[str]:
        """List every assigned key, in file order."""
        found = []
        for line in self.lines:
            match = _ASSIGNMENT.match(line)
            if match:
                found.append(match.group(1))
        return found

    def get(self, key: str) -> str | None:
        """Return the value assigned to *key*, or ``None`` when unset."""
        for line in self.lines:
            match = _ASSIGNMENT.match(line)
            if match and match.group(1) == key:
                return _unquote(match.group(2).strip())
        return None

    def has(self, key: str) -> bool:
        """Report whether *key* is assigned anywhere in the file."""
        return key in set(self.keys())

    # -- writing -------------------------------------------------------

    def set(self, key: str, value: str, *, comment: str | None = None) -> None:
        """Assign *key*, replacing an existing assignment in place.

        A key that is not present yet is appended; one that is present keeps
        its position, and its surrounding comments, so diffs stay small.
        """
        rendered = f"{key}={_quote(value)}"
        for index, line in enumerate(self.lines):
            match = _ASSIGNMENT.match(line)
            if match and match.group(1) == key:
                self.lines[index] = rendered
                return
        if comment:
            self.lines.append(f"# {comment}")
        self.lines.append(rendered)

    def setdefault(self, key: str, value: str, *, comment: str | None = None) -> bool:
        """Assign *key* only when it is absent.

        Returns:
            True when the key was added, false when it was already present.
        """
        if self.has(key):
            return False
        self.set(key, value, comment=comment)
        return True

    def remove(self, key: str) -> bool:
        """Delete the assignment for *key*.

        Returns:
            True when a line was removed.
        """
        for index, line in enumerate(self.lines):
            match = _ASSIGNMENT.match(line)
            if match and match.group(1) == key:
                del self.lines[index]
                return True
        return False

    def add_section(self, title: str, variables: list[EnvVar]) -> None:
        """Append a titled block of variables, skipping ones already present.

        The whole block is skipped when every variable in it already exists, so
        repeated ``add`` runs do not accumulate empty headers.
        """
        pending = [var for var in variables if not self.has(var.key)]
        if not pending:
            return
        if self.lines and self.lines[-1].strip():
            self.lines.append("")
        self.lines.append(f"# --- {title} ---")
        for var in pending:
            if var.comment:
                self.lines.append(f"# {var.comment}")
            self.lines.append(f"{var.key}={_quote(var.value)}")


def _quote(value: str) -> str:
    """Quote a value when it contains characters a dotenv reader would eat."""
    if value == "":
        return ""
    if _NEEDS_QUOTING.search(value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _unquote(value: str) -> str:
    """Strip matching surrounding quotes from a parsed value."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def generate_secret_key(length: int = 50) -> str:
    """Generate a URL-safe application secret.

    Used for ``APP_SECRET_KEY`` and ``JWT_SECRET`` in generated projects so a
    new project is never born with a placeholder secret that someone might ship.
    """
    return secrets.token_urlsafe(length)[:length]
