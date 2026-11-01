import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base, get_db
from backend.app.core.security import hash_password
from backend.app.main import app
from backend.app.models import User

client = TestClient(app)


@pytest.fixture(autouse=True)
def installed_docs_assets(monkeypatch):
    # Source-mounted Docker checks import /workspace while npm assets live /app.
    from pathlib import Path
    from backend.app.api import docs
    installed = Path("/app/node_modules/swagger-ui-dist")
    if not docs.ASSETS_DIR.is_dir() and installed.is_dir():
        monkeypatch.setattr(docs, "ASSETS_DIR", installed)


@pytest.fixture
def platform_user(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'docs.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add(User(username="docs-fixture", password_hash=hash_password("fixture-password")))
        db.commit()

    def database():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database
    yield
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def test_docs_use_local_resources_and_new_schema_route():
    response = client.get("/api/docs")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    urls = re.findall(r'(?:src|href)="([^"]+)"', html)
    assert urls
    for url in urls:
        assert url.startswith("/api/docs/assets/")
        asset = client.get(url)
        assert asset.status_code == 200
        assert len(asset.content) > 100
    assert "/api/openapi.json" in html
    assert '"persistAuthorization": false' in html
    assert '"validatorUrl": null' in html


def test_schema_documents_authentication_requests_and_note_response_fields():
    schema = client.get("/api/openapi.json").json()
    assert "Authorize" in schema["info"]["description"]
    flow = schema["components"]["securitySchemes"]["OAuth2PasswordBearer"]["flows"]["password"]
    assert flow["tokenUrl"] == "/api/auth/token"
    token = schema["paths"]["/api/auth/token"]["post"]
    assert "application/x-www-form-urlencoded" in token["requestBody"]["content"]
    login = schema["paths"]["/api/auth/login"]["post"]
    assert "application/json" in login["requestBody"]["content"]
    notes = schema["paths"]["/api/xhs/account-notes/{account_id}/notes"]["get"]
    assert notes["security"] == [{"OAuth2PasswordBearer": []}]
    assert notes["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/ManagedNoteList")
    assert {"views", "likes", "collects", "comments", "shares"}.issubset(schema["components"]["schemas"]["ManagedNote"]["properties"])
    assert "/api/docs/assets/{file_name}" not in schema["paths"]
    assert client.get("/openapi.json").json() == schema


@pytest.mark.parametrize("url", ["/docs", "/redoc"])
def test_legacy_docs_redirect_to_interactive_docs(url):
    response = client.get(url, follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/api/docs"


@pytest.mark.parametrize("file_name", ["package.json", "swagger-ui-bundle.js.map", ".env"])
def test_documentation_asset_route_only_serves_whitelisted_files(file_name):
    assert client.get(f"/api/docs/assets/{file_name}").status_code == 404


def test_swagger_form_login_authorizes_protected_calls_and_json_login_still_works(platform_user):
    response = client.post("/api/auth/token", data={"grant_type": "password", "username": "docs-fixture", "password": "fixture-password"})
    assert response.status_code == 200
    result = response.json()
    assert result["token_type"] == "bearer"
    headers = {"Authorization": "Bearer " + result["access_token"]}
    assert client.get("/api/auth/me", headers=headers).json()["username"] == "docs-fixture"
    assert client.get("/api/xhs/account-notes/accounts", headers=headers).json() == {"items": []}
    assert client.get("/api/xhs/account-notes/accounts").status_code == 401
    json_login = client.post("/api/auth/login", json={"username": "docs-fixture", "password": "fixture-password"})
    assert json_login.status_code == 200
    assert json_login.json()["user"] == result["user"]


@pytest.mark.parametrize("password", ["wrong-password", "x" * 129])
def test_form_login_rejects_bad_credentials(platform_user, password):
    response = client.post("/api/auth/token", data={"grant_type": "password", "username": "docs-fixture", "password": password})
    assert response.status_code == 401
    assert "access_token" not in response.json()
