from fastapi.testclient import TestClient

from nebulai.main import app


def test_me_returns_testing_user() -> None:
    with TestClient(app) as client:
        response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json()["id"] == "local-user"
    assert response.json()["workspace_id"] == "local-workspace"


def test_email_code_login_sets_session_cookie() -> None:
    class FakePostgres:
        def __init__(self) -> None:
            self.code_hash = ""

        async def create_email_code(self, code_id: str, email: str, code_hash: str, expires_minutes: int = 10):
            assert code_id
            assert email == "user@example.com"
            assert expires_minutes == 10
            self.code_hash = code_hash

        async def consume_email_code(self, email: str, code_hash: str):
            assert email == "user@example.com"
            return code_hash == self.code_hash

        async def upsert_user(self, user_id: str, email: str, name: str, avatar_url: str | None, provider: str, provider_subject: str):
            assert user_id.startswith("email-")
            assert email == "user@example.com"
            assert name == "user"
            assert avatar_url is None
            assert provider == "email"
            assert provider_subject == "user@example.com"

        async def ensure_personal_workspace(self, user_id: str, name: str):
            assert user_id.startswith("email-")
            assert name == "user"
            return f"workspace-{user_id}"

    fake = FakePostgres()
    with TestClient(app) as client:
        client.app.state.postgres_store = fake
        code_response = client.post("/api/auth/email/request-code", json={"email": "user@example.com"})
        login_response = client.post(
            "/api/auth/email/login",
            json={"email": "user@example.com", "code": code_response.json()["dev_code"]},
        )

    assert code_response.status_code == 200
    assert login_response.status_code == 200
    assert login_response.json()["email"] == "user@example.com"
    assert "nebulai_session" in login_response.headers["set-cookie"]


def test_dev_login_sets_internal_test_user_cookie() -> None:
    class FakePostgres:
        async def upsert_user(
            self,
            user_id: str,
            email: str,
            name: str,
            avatar_url: str | None,
            provider: str,
            provider_subject: str,
        ):
            assert user_id.startswith("internal-")
            assert email == "test@nebulai.local"
            assert name == "内部测试账号"
            assert avatar_url is None
            assert provider == "internal"
            assert provider_subject == "test@nebulai.local"

        async def ensure_personal_workspace(self, user_id: str, name: str):
            assert user_id.startswith("internal-")
            assert name == "内部测试账号"
            return f"workspace-{user_id}"

    with TestClient(app) as client:
        client.app.state.postgres_store = FakePostgres()
        response = client.post("/api/auth/dev-login")

    assert response.status_code == 200
    assert response.json()["email"] == "test@nebulai.local"
    assert response.json()["name"] == "内部测试账号"
    assert "nebulai_session" in response.headers["set-cookie"]


def test_oauth_reports_unconfigured_provider() -> None:
    with TestClient(app) as client:
        response = client.get("/api/auth/oauth/github")

    assert response.status_code == 200
    assert response.json()["configured"] is False
