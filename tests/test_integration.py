"""Integration tests that execute generated projects against the real framework.

These are the tests that catch what unit tests cannot: a template that produces
valid Python which nonetheless does not work against Sillo. Every constraint
documented in ``docs/verified-apis.md`` was found by a failure at this level.

They are skipped when ``sillo`` is not importable, so the suite still runs in an
environment that only has Sillo Start installed.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sillo = pytest.importorskip("sillo", reason="sillo-framework is not installed")


def run_in_project(root: Path, script: str, *, env: dict[str, str] | None = None) -> str:
    """Execute *script* with the project on ``sys.path`` and return its output.

    A subprocess is used rather than importing directly because generated
    projects define modules — ``app``, ``routes``, ``database`` — whose names
    would collide between tests inside one interpreter.

    Raises:
        AssertionError: If the script exits non-zero, with its output attached.
    """
    import os

    environment = {
        **os.environ,
        "PYTHONPATH": str(root),
        "DATABASE_URL": f"sqlite://{root / 'test.db'}",
        # Generated projects keep schema generation off because migrations own
        # the schema. These tests exercise handlers against a throwaway
        # database with no migrations, so they opt back in — the same escape
        # hatch a scratch database would use.
        "DB_GENERATE_SCHEMAS": "true",
        "SECRET_KEY": "t" * 50,
        "JWT_SECRET": "j" * 50,
        **(env or {}),
    }
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=str(root),
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"script failed with code {result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    return result.stdout


class TestGeneratedApiProject:
    def test_the_application_starts_and_serves_its_routes(self, project: Path):
        output = run_in_project(
            project,
            """
            from sillo.testclient import TestClient
            from app.bootstrap import create_app

            with TestClient(create_app()) as client:
                health = client.get("/api/health")
                root = client.get("/api/")
                schema = client.get("/openapi.json")
                print("health", health.status_code, health.json()["status"])
                print("root", root.status_code, root.json()["name"])
                print("openapi", schema.status_code)
            """,
        )

        assert "health 200 ok" in output
        assert "root 200 Testapp" in output
        assert "openapi 200" in output


class TestGeneratedFullstackProject:
    @pytest.fixture
    def fullstack(self, project_factory) -> Path:
        return project_factory(blueprint="fullstack", name="shop")

    def test_the_whole_authentication_flow_works(self, fullstack: Path):
        """Register, sign in, and read the session back."""
        output = run_in_project(
            fullstack,
            """
            from sillo.testclient import TestClient
            from app.bootstrap import create_app

            with TestClient(create_app()) as client:
                created = client.post("/api/auth/register", json={
                    "email": "a@b.com", "username": "alice", "password": "sekret123",
                })
                signed_in = client.post("/api/auth/login", json={
                    "identifier": "a@b.com", "password": "sekret123",
                })
                me = client.get("/api/auth/me")
                print("register", created.status_code)
                print("login", signed_in.status_code)
                print("me", me.status_code, me.json().get("email"))
            """,
        )

        assert "register 201" in output
        assert "login 200" in output
        assert "me 200 a@b.com" in output

    def test_the_database_health_check_reports_a_live_connection(self, fullstack: Path):
        output = run_in_project(
            fullstack,
            """
            from sillo.testclient import TestClient
            from app.bootstrap import create_app

            with TestClient(create_app()) as client:
                payload = client.get("/api/health").json()
                print("database", payload["checks"]["database"])
            """,
        )

        assert "database ok" in output

    def test_duplicate_registration_is_rejected_with_a_conflict(self, fullstack: Path):
        output = run_in_project(
            fullstack,
            """
            from sillo.testclient import TestClient
            from app.bootstrap import create_app

            payload = {"email": "a@b.com", "username": "alice", "password": "sekret123"}
            with TestClient(create_app()) as client:
                client.post("/api/auth/register", json=payload)
                again = client.post("/api/auth/register", json=payload)
                print("conflict", again.status_code)
            """,
        )

        assert "conflict 409" in output

    def test_bad_credentials_do_not_reveal_whether_the_account_exists(self, fullstack: Path):
        output = run_in_project(
            fullstack,
            """
            from sillo.testclient import TestClient
            from app.bootstrap import create_app

            with TestClient(create_app()) as client:
                client.post("/api/auth/register", json={
                    "email": "a@b.com", "username": "alice", "password": "sekret123",
                })
                wrong_password = client.post("/api/auth/login", json={
                    "identifier": "a@b.com", "password": "wrong",
                })
                no_such_user = client.post("/api/auth/login", json={
                    "identifier": "nobody@example.com", "password": "wrong",
                })
                print("same_status", wrong_password.status_code == no_such_user.status_code)
                print("same_body", wrong_password.json() == no_such_user.json())
            """,
        )

        assert "same_status True" in output
        assert "same_body True" in output

    def test_request_validation_rejects_a_malformed_body(self, fullstack: Path):
        output = run_in_project(
            fullstack,
            """
            from sillo.testclient import TestClient
            from app.bootstrap import create_app

            with TestClient(create_app()) as client:
                bad = client.post("/api/auth/register", json={
                    "email": "not-an-email", "username": "x", "password": "short",
                })
                print("validation", bad.status_code)
            """,
        )

        assert "validation 422" in output

    def test_the_admin_login_page_renders(self, fullstack: Path):
        """Admin routes carry a trailing slash; without it they 404."""
        output = run_in_project(
            fullstack,
            """
            from sillo.testclient import TestClient
            from app.bootstrap import create_app

            with TestClient(create_app()) as client:
                page = client.get("/admin/login/")
                print("admin", page.status_code, len(page.text) > 500)
            """,
        )

        assert "admin 200 True" in output


class TestGeneratedModels:
    def test_a_generated_model_persists_and_resolves_its_relations(self, project_factory):
        """The generated model must work against the real ORM, not just parse."""
        from typer.testing import CliRunner

        from sillo_start.cli import build_cli

        root = project_factory(blueprint="fullstack", name="shop")
        runner = CliRunner()
        import os

        previous = Path.cwd()
        os.chdir(root)
        try:
            result = runner.invoke(
                build_cli(),
                ["generate", "model", "Post", "-f", "title:str", "-f", "author:fk:User"],
            )
            assert result.exit_code == 0, result.output
        finally:
            os.chdir(previous)

        output = run_in_project(
            root,
            """
            from sillo.testclient import TestClient
            from app.bootstrap import create_app
            from database.models.post import Post
            from database.models.user import User

            app = create_app()
            with TestClient(app) as client:
                client.post("/api/auth/register", json={
                    "email": "a@b.com", "username": "alice", "password": "sekret123",
                })
                # Re-enter the ORM context captured at startup so queries made
                # outside a request can see the connection.
                context = app.state["record"]._root_context
                context.__enter__()
                try:
                    async def work():
                        user = await User.objects.get_by_email("a@b.com")
                        post = await Post.create(title="Hello", author=user)
                        fetched = await Post.get(id=post.id)
                        author = await fetched.author
                        reverse = [p.title for p in await user.posts]
                        return fetched.title, author.email, reverse
                    title, email, reverse = client.portal.call(work)
                    print("post", title)
                    print("author", email)
                    print("reverse", reverse)
                finally:
                    context.__exit__(None, None, None)
            """,
        )

        assert "post Hello" in output
        assert "author a@b.com" in output
        assert "reverse ['Hello']" in output


class TestGeneratedInertiaProject:
    @pytest.fixture
    def site(self, project_factory) -> Path:
        pytest.importorskip("sillo_inertia", reason="sillo-inertia is not installed")
        return project_factory(blueprint="inertia-react", name="site")

    def test_a_browser_request_gets_html_with_the_vite_tags(self, site: Path):
        output = run_in_project(
            site,
            """
            from sillo.testclient import TestClient
            from app.bootstrap import create_app

            with TestClient(create_app()) as client:
                page = client.get("/")
                print("status", page.status_code)
                print("has_root", 'id="app"' in page.text)
                print("has_vite", "5173" in page.text)
            """,
        )

        assert "status 200" in output
        assert "has_root True" in output
        assert "has_vite True" in output

    def test_pages_api_auth_and_admin_all_stay_reachable(self, project_factory):
        """Regression: a prefix-less router would claim "/" and shadow the rest.

        With Inertia and the admin panel both enabled, the web page at "/", the
        API, the auth routes and the admin all have to coexist. Mounting the
        web routes as a router made "/" a catch-all mount that swallowed the
        admin, whose routes are registered later, during startup.
        """
        pytest.importorskip("sillo_inertia", reason="sillo-inertia is not installed")
        root = project_factory(blueprint="inertia-react", name="site", admin=True)

        output = run_in_project(
            root,
            """
            from sillo.testclient import TestClient
            from app.bootstrap import create_app

            with TestClient(create_app()) as client:
                print("page", client.get("/").status_code)
                print("api", client.get("/api/health").status_code)
                print("auth", client.get("/api/auth/me").status_code)
                print("admin", client.get("/admin/login/").status_code)
            """,
        )

        assert "page 200" in output
        assert "api 200" in output
        assert "auth 401" in output   # reachable, and correctly unauthenticated
        assert "admin 200" in output

    def test_an_inertia_request_gets_the_page_object(self, site: Path):
        """The Inertia protocol: same URL, JSON when the header is present."""
        output = run_in_project(
            site,
            """
            import json
            from sillo.testclient import TestClient
            from app.bootstrap import create_app

            with TestClient(create_app()) as client:
                page = client.get("/", headers={"X-Inertia": "true"})
                payload = page.json()
                print("status", page.status_code)
                print("component", payload["component"])
                print("has_props", "message" in payload["props"])
            """,
        )

        assert "status 200" in output
        assert "component Home" in output
        assert "has_props True" in output
