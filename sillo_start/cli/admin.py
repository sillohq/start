"""``sillo-start admin`` — manage the admin panel."""

from __future__ import annotations

import subprocess
import sys

import typer

from ..config.loader import load_project
from ..exceptions import UsageError
from ..utils.console import console
from ..utils.pkgmanagers import detect_python_manager
from .app import app, handle_errors

admin_app = typer.Typer(help="Manage the admin panel.", no_args_is_help=True)
app.add_typer(admin_app, name="admin")

#: Run inside the project so its models, config and database are the real ones.
#: Written as a script rather than assembled from imports here, because Sillo
#: Start's own interpreter usually has no access to the project's dependencies.
_CREATE_USER_SCRIPT = '''
import asyncio, sys

from sillo.record import DatabaseConfig, setup_record
from sillo import silloApp

from app.config import config
from database.models.user import User


async def main(email, username, password, superuser):
    app = silloApp(debug=False, title="admin-cli", version="0")
    manager = setup_record(
        app,
        DatabaseConfig(url=config.database_url),
        model_modules=["{models_module}", "sillo.admin.models"],
    )
    await manager.init()
    try:
        if await User.objects.get_by_email(email) is not None:
            print(f"ERROR: a user with email {{email}} already exists.", file=sys.stderr)
            return 1
        create = User.objects.create_superuser if superuser else User.objects.create_user
        user = await create(email=email, username=username, password=password)
        if superuser:
            user.is_staff = True
            await user.save()
        print(f"OK:{{user.id}}")
        return 0
    finally:
        await manager.shutdown()


sys.exit(asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] == "1")))
'''


@admin_app.command("create-user")
@handle_errors
def create_user(
    email: str = typer.Option(None, "--email", "-e", help="Email address."),
    username: str = typer.Option(None, "--username", "-u", help="Username."),
    password: str = typer.Option(None, "--password", "-p", help="Password. Prompted if omitted."),
    superuser: bool = typer.Option(True, "--superuser/--regular", help="Grant full access."),
) -> None:
    """Create a user who can sign in to the admin panel.

    Runs inside the project's environment so it uses the project's own models
    and database.
    """
    root, manifest = load_project()

    if not manifest.admin.enabled:
        raise UsageError(
            "This project has no admin panel.",
            hint="Add one with `sillo-start add admin`.",
        )
    if not manifest.uses_record:
        raise UsageError("The admin panel needs a database, which is not configured.")

    email = email or typer.prompt("Email")
    username = username or typer.prompt("Username", default=email.split("@")[0])
    password = password or typer.prompt("Password", hide_input=True, confirmation_prompt=True)

    if len(password) < 8:
        raise UsageError("Password must be at least 8 characters.")

    script = _CREATE_USER_SCRIPT.format(models_module=manifest.database.models_module)
    manager = detect_python_manager()
    argv = [
        *(["uv", "run", "python"] if manager.name == "uv" else [sys.executable]),
        "-c",
        script,
        email,
        username,
        password,
        "1" if superuser else "0",
    ]

    console.header("Creating admin user", email)
    result = subprocess.run(  # noqa: S603 — argv list, never shell=True
        argv, cwd=str(root), capture_output=True, text=True, timeout=120
    )

    if result.returncode != 0:
        console.blank()
        console.failure("Could not create the user.")
        if result.stdout.strip() or result.stderr.strip():
            console.blank()
            console.raw((result.stdout + result.stderr).strip())
        raise typer.Exit(code=1)

    console.success(f"Created {email}" + (" (superuser)" if superuser else ""))
    console.blank()
    console.hint(
        f"Sign in at http://localhost:{manifest.application.port}{manifest.admin.prefix}/login/"
    )
