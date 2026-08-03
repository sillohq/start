"""Creating a project by fetching a starter repository.

A generated project can render perfectly and still fail on its first request:
templates are checked for rendering, not for running. A starter repository is
a real application with its own CI, so what arrives has been booted and
exercised before it reaches anyone.

The repository is fetched as a tarball rather than cloned. That needs no git on
the machine, brings no history someone has to delete before their first commit,
and pins to a tag as easily as to a branch.
"""

from __future__ import annotations

import io
import re
import secrets
import tarfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from ..exceptions import CommandError


def generate_secret_key(length: int = 50) -> str:
    """Generate a URL-safe application secret.

    So a new project is never born with a placeholder secret that someone might
    ship.
    """
    return secrets.token_urlsafe(length)[:length]


#: The starter used when none is named.
DEFAULT_TEMPLATE = "sillohq/starter"

#: How long to wait for GitHub before giving up, in seconds.
TIMEOUT = 60


@dataclass(frozen=True)
class Template:
    """A starter repository and the revision to take."""

    owner: str
    repo: str
    ref: str = "main"

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def url(self) -> str:
        """The tarball URL. Public repositories need no authentication."""
        return f"https://codeload.github.com/{self.owner}/{self.repo}/tar.gz/{self.ref}"

    @classmethod
    def parse(cls, value: str, *, ref: str | None = None) -> Template:
        """Parse ``owner/repo``, ``owner/repo@ref`` or a full GitHub URL.

        Raises:
            CommandError: If *value* is not a recognisable repository.
        """
        text = value.strip()
        text = re.sub(r"^(https?://)?(www\.)?github\.com/", "", text)
        text = re.sub(r"\.git$", "", text).strip("/")

        at_ref = None
        if "@" in text:
            text, _, at_ref = text.partition("@")

        parts = [part for part in text.split("/") if part]
        if len(parts) != 2:
            raise CommandError(
                f"'{value}' is not a repository.",
                hint="Use owner/repo, for example sillohq/starter.",
            )
        return cls(owner=parts[0], repo=parts[1], ref=ref or at_ref or "main")


def fetch(template: Template, destination: Path) -> None:
    """Download *template* and unpack it into *destination*.

    GitHub wraps the archive in a single top-level directory named after the
    repository and commit, which is stripped so the project's own files land at
    the destination root.

    Raises:
        CommandError: If the repository or ref cannot be fetched.
    """
    try:
        with urllib.request.urlopen(template.url, timeout=TIMEOUT) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise CommandError(
                f"Could not find {template.slug} at ref '{template.ref}'.",
                hint="Check the name and the branch or tag, and that the repository is public.",
            ) from exc
        raise CommandError(f"GitHub returned {exc.code} for {template.slug}.") from exc
    except urllib.error.URLError as exc:
        raise CommandError(
            f"Could not reach GitHub: {exc.reason}",
            hint="Creating a project needs network access to fetch the starter.",
        ) from exc

    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        members = archive.getmembers()
        if not members:
            raise CommandError(f"{template.slug} produced an empty archive.")

        prefix = members[0].name.split("/")[0] + "/"
        for member in members:
            if not member.name.startswith(prefix):
                continue
            relative = member.name[len(prefix) :]
            if not relative:
                continue
            # A member path that escapes the destination is how a malicious
            # archive overwrites files elsewhere. Refuse rather than sanitise.
            target = (destination / relative).resolve()
            if not str(target).startswith(str(destination.resolve())):
                raise CommandError(
                    f"{template.slug} contains an unsafe path: {member.name}"
                )

            member.name = relative
            archive.extract(member, destination, filter="data")


#: Files rewritten to carry the new project's name, and what to replace in each.
#: Targeted rather than a blanket find-and-replace, so prose that happens to say
#: "starter" — the README, a Makefile comment — is left as written.
#:
#: Model files are deliberately absent. A model's docstring becomes its
#: ``table_description``, so rewriting one puts the models out of step with the
#: committed migration and the next `migrate` writes a spurious second one.
RENAMES = (
    ("pyproject.toml", ('name = "{old}"', 'name = "{new}"')),
    (
        "app/config.py",
        ('"""Typed settings for {Old}."""', '"""Typed settings for {New}."""'),
    ),
    ("app/config.py", ('app_name: str = "{Old}"', 'app_name: str = "{New}"')),
    ("app/config.py", ("sqlite://storage/{old}.db", "sqlite://storage/{new}.db")),
    (".env.example", ("# {Old} environment.", "# {New} environment.")),
    (".env.example", ("APP_NAME={Old}", "APP_NAME={New}")),
    (".env.example", ("sqlite://storage/{old}.db", "sqlite://storage/{new}.db")),
)


def personalise(root: Path, name: str, *, template_name: str = "starter") -> list[str]:
    """Rewrite the fetched project to be *name*, and create its ``.env``.

    Args:
        root: The unpacked project.
        name: The new project name.
        template_name: What the starter called itself.

    Returns:
        The paths that changed, relative to *root*.
    """
    substitutions = {
        "old": template_name,
        "new": name,
        "Old": template_name.replace("_", " ").title().replace(" ", ""),
        "New": name.replace("_", " ").title().replace(" ", ""),
    }

    changed: list[str] = []
    for relative, (find, replace) in RENAMES:
        path = root / relative
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        needle = find.format(**substitutions)
        if needle not in content:
            continue
        path.write_text(
            content.replace(needle, replace.format(**substitutions)), encoding="utf-8"
        )
        if relative not in changed:
            changed.append(relative)

    # The lock file names the project as a member of its own workspace, so it
    # has to agree with pyproject or `uv sync` fails on a renamed project.
    lock = root / "uv.lock"
    if lock.is_file():
        content = lock.read_text(encoding="utf-8")
        renamed = content.replace(f'name = "{template_name}"', f'name = "{name}"')
        if renamed != content:
            lock.write_text(renamed, encoding="utf-8")
            changed.append("uv.lock")

    if _write_env(root, name):
        changed.append(".env")
    return changed


def _write_env(root: Path, name: str) -> bool:
    """Create ``.env`` from ``.env.example`` with fresh secrets.

    Returns:
        True when a file was written. An existing ``.env`` is never replaced —
        it may hold real credentials.
    """
    example = root / ".env.example"
    env = root / ".env"
    if not example.is_file() or env.exists():
        return False

    lines = []
    for line in example.read_text(encoding="utf-8").splitlines():
        key, sep, _ = line.partition("=")
        # Secrets committed to a starter are placeholders by definition. Every
        # project gets its own, so no two deployments ever share a signing key.
        if sep and key.strip() in {"SECRET_KEY", "JWT_SECRET", "APP_KEY"}:
            line = f"{key}={generate_secret_key()}"
        lines.append(line)
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True
