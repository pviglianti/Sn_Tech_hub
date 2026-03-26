"""Tests for OAuth authentication support.

Covers:
- OAuthTokenManager: token exchange, refresh, expiry
- ServiceNowClient: OAuth Bearer auth, automatic token refresh
- Instance model: auth_type and OAuth fields
- create_client_for_instance: factory function for both auth types
- Instance routes: add/edit with OAuth fields
"""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from sqlmodel import Session

from src.models import AuthType, Instance
from src.services.encryption import encrypt_password, decrypt_password
from src.services.oauth_manager import OAuthTokenManager, OAuthError
from src.services.sn_client import ServiceNowClient
from src.services.sn_client_factory import create_client_for_instance


# ── AuthType enum ──


class TestAuthTypeEnum:
    def test_basic_value(self):
        assert AuthType.basic.value == "basic"

    def test_oauth_value(self):
        assert AuthType.oauth.value == "oauth"

    def test_is_str(self):
        assert isinstance(AuthType.basic, str)


# ── OAuthTokenManager ──


class TestOAuthTokenManager:
    def _make_manager(self, **overrides):
        defaults = dict(
            instance_url="https://dev12345.service-now.com",
            client_id="test-client-id",
            client_secret="test-client-secret",
            username="admin",
            password="password123",
        )
        defaults.update(overrides)
        return OAuthTokenManager(**defaults)

    def test_token_endpoint(self):
        mgr = self._make_manager()
        assert mgr.token_endpoint == "https://dev12345.service-now.com/oauth_token.do"

    def test_token_endpoint_strips_trailing_slash(self):
        mgr = self._make_manager(instance_url="https://dev12345.service-now.com/")
        assert mgr.token_endpoint == "https://dev12345.service-now.com/oauth_token.do"

    def test_is_token_valid_no_token(self):
        mgr = self._make_manager()
        assert not mgr.is_token_valid()

    def test_is_token_valid_expired(self):
        mgr = self._make_manager(
            access_token="old-token",
            token_expires_at=datetime.utcnow() - timedelta(minutes=5),
        )
        assert not mgr.is_token_valid()

    def test_is_token_valid_within_buffer(self):
        """Token should be considered invalid when within the 60s buffer."""
        mgr = self._make_manager(
            access_token="almost-expired",
            token_expires_at=datetime.utcnow() + timedelta(seconds=30),
        )
        assert not mgr.is_token_valid()

    def test_is_token_valid_ok(self):
        mgr = self._make_manager(
            access_token="good-token",
            token_expires_at=datetime.utcnow() + timedelta(minutes=20),
        )
        assert mgr.is_token_valid()

    def test_get_access_token_returns_cached(self):
        mgr = self._make_manager(
            access_token="cached-token",
            token_expires_at=datetime.utcnow() + timedelta(minutes=20),
        )
        assert mgr.get_access_token() == "cached-token"

    @patch("src.services.oauth_manager.requests.post")
    def test_password_grant_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 1800,
            "token_type": "Bearer",
        }
        mock_post.return_value = mock_resp

        mgr = self._make_manager()
        token = mgr.get_access_token()

        assert token == "new-access-token"
        assert mgr.access_token == "new-access-token"
        assert mgr.refresh_token == "new-refresh-token"
        assert mgr.token_expires_at is not None

        # Verify correct endpoint and params
        call_args = mock_post.call_args
        assert "oauth_token.do" in call_args[1].get("url", "") or "oauth_token.do" in str(call_args)
        posted_data = call_args[1].get("data", call_args[0][1] if len(call_args[0]) > 1 else {})
        assert posted_data.get("grant_type") == "password"
        assert posted_data.get("client_id") == "test-client-id"

    @patch("src.services.oauth_manager.requests.post")
    def test_password_grant_failure(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"error": "invalid_client", "error_description": "Bad credentials"}
        mock_post.return_value = mock_resp

        mgr = self._make_manager()
        with pytest.raises(OAuthError, match="Bad credentials"):
            mgr.get_access_token()

    @patch("src.services.oauth_manager.requests.post")
    def test_refresh_token_flow(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "refreshed-token",
            "refresh_token": "new-refresh",
            "expires_in": 1800,
        }
        mock_post.return_value = mock_resp

        mgr = self._make_manager(
            access_token="expired-token",
            refresh_token="valid-refresh-token",
            token_expires_at=datetime.utcnow() - timedelta(minutes=5),
        )
        token = mgr.get_access_token()

        assert token == "refreshed-token"
        # Should have used refresh_token grant
        posted_data = mock_post.call_args[1].get("data", {})
        assert posted_data.get("grant_type") == "refresh_token"

    @patch("src.services.oauth_manager.requests.post")
    def test_refresh_failure_falls_back_to_password(self, mock_post):
        """If refresh token fails, should fall back to full password grant."""
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            mock_resp = MagicMock()
            if call_count[0] == 1:
                # First call: refresh fails
                mock_resp.status_code = 401
                mock_resp.json.return_value = {"error": "invalid_grant"}
            else:
                # Second call: password grant succeeds
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "access_token": "fallback-token",
                    "refresh_token": "new-refresh",
                    "expires_in": 1800,
                }
            return mock_resp

        mock_post.side_effect = side_effect

        mgr = self._make_manager(
            access_token="expired",
            refresh_token="bad-refresh",
            token_expires_at=datetime.utcnow() - timedelta(minutes=5),
        )
        token = mgr.get_access_token()

        assert token == "fallback-token"
        assert call_count[0] == 2

    @patch("src.services.oauth_manager.requests.post")
    def test_force_refresh(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "forced-token",
            "expires_in": 1800,
        }
        mock_post.return_value = mock_resp

        mgr = self._make_manager(
            access_token="valid-but-stale",
            token_expires_at=datetime.utcnow() + timedelta(minutes=20),
        )
        token = mgr.force_refresh()
        assert token == "forced-token"


# ── ServiceNowClient with OAuth ──


class TestServiceNowClientOAuth:
    def test_basic_auth_default(self):
        client = ServiceNowClient("https://dev.service-now.com", "admin", "pass")
        assert client.auth_type == "basic"
        assert client.session.auth is not None

    def test_oauth_auth_sets_bearer(self):
        mock_mgr = MagicMock()
        mock_mgr.get_access_token.return_value = "test-token"

        client = ServiceNowClient(
            "https://dev.service-now.com", "admin", "pass",
            auth_type="oauth", oauth_manager=mock_mgr,
        )
        assert client.auth_type == "oauth"
        assert "Bearer test-token" in client.session.headers.get("Authorization", "")

    def test_oauth_get_retries_on_401(self):
        mock_mgr = MagicMock()
        mock_mgr.get_access_token.return_value = "initial-token"
        mock_mgr.force_refresh.return_value = "refreshed-token"

        client = ServiceNowClient(
            "https://dev.service-now.com", "admin", "pass",
            auth_type="oauth", oauth_manager=mock_mgr,
        )

        # Mock session.get to return 401 first, then 200
        call_count = [0]
        def fake_get(*args, **kwargs):
            call_count[0] += 1
            resp = MagicMock()
            resp.status_code = 200 if call_count[0] > 1 else 401
            resp.json.return_value = {"result": []}
            return resp

        client.session.get = fake_get
        response = client._get("https://dev.service-now.com/api/now/table/incident")
        assert response.status_code == 200
        assert call_count[0] == 2


# ── Instance model with OAuth fields ──


class TestInstanceOAuthFields:
    def test_default_auth_type(self):
        inst = Instance(name="test", url="https://dev.service-now.com",
                       username="admin", password_encrypted="enc")
        assert inst.auth_type == "basic"

    def test_oauth_fields_nullable(self):
        inst = Instance(name="test", url="https://dev.service-now.com",
                       username="admin", password_encrypted="enc",
                       auth_type="oauth")
        assert inst.client_id is None
        assert inst.client_secret_encrypted is None
        assert inst.oauth_access_token_encrypted is None

    def test_oauth_fields_set(self):
        inst = Instance(
            name="test", url="https://dev.service-now.com",
            username="admin", password_encrypted="enc",
            auth_type="oauth",
            client_id="my-client-id",
            client_secret_encrypted=encrypt_password("my-secret"),
        )
        assert inst.auth_type == "oauth"
        assert inst.client_id == "my-client-id"
        assert decrypt_password(inst.client_secret_encrypted) == "my-secret"


# ── create_client_for_instance factory ──


class TestCreateClientForInstance:
    def _make_instance(self, auth_type="basic", **kwargs):
        defaults = dict(
            name="test",
            url="https://dev.service-now.com",
            username="admin",
            password_encrypted=encrypt_password("password123"),
        )
        defaults.update(kwargs)
        defaults["auth_type"] = auth_type
        return Instance(**defaults)

    def test_basic_auth_creates_basic_client(self):
        inst = self._make_instance()
        client = create_client_for_instance(inst, persist_tokens=False)
        assert client.auth_type == "basic"
        assert client.session.auth is not None

    @patch("src.services.sn_client_factory.OAuthTokenManager")
    def test_oauth_creates_oauth_client(self, MockMgr):
        mock_instance = MockMgr.return_value
        mock_instance.get_access_token.return_value = "test-token"
        mock_instance.access_token = "test-token"
        mock_instance.refresh_token = "test-refresh"
        mock_instance.token_expires_at = datetime.utcnow() + timedelta(hours=1)

        inst = self._make_instance(
            auth_type="oauth",
            client_id="cid",
            client_secret_encrypted=encrypt_password("csecret"),
        )
        client = create_client_for_instance(inst, persist_tokens=False)
        assert client.auth_type == "oauth"
        assert "Bearer" in client.session.headers.get("Authorization", "")

    def test_oauth_missing_client_id_falls_back_to_basic(self):
        """If auth_type is oauth but client_id is missing, fall back to basic."""
        inst = self._make_instance(auth_type="oauth")
        client = create_client_for_instance(inst, persist_tokens=False)
        assert client.auth_type == "basic"


# ── Instance routes with OAuth ──


class TestInstanceRoutesOAuth:
    """Test that instance add/edit routes accept OAuth parameters.

    Uses the `client` fixture from conftest.py which provides a TestClient
    wired to an in-memory test database.
    """

    def test_add_form_renders_with_oauth_fields(self, client):
        """The add instance form should include OAuth auth type and fields."""
        resp = client.get("/instances/add")
        assert resp.status_code == 200
        assert "auth_type" in resp.text
        assert "OAuth 2.0" in resp.text
        assert "client_id" in resp.text
        assert "client_secret" in resp.text
        assert "Basic Auth" in resp.text

    def test_edit_form_renders_with_oauth_fields(self, client, db_session):
        """The edit instance form should show current auth type."""
        inst = Instance(
            name="oauth-edit-test",
            url="https://test.service-now.com",
            username="admin",
            password_encrypted=encrypt_password("pass"),
            auth_type="oauth",
            client_id="my-cid",
            client_secret_encrypted=encrypt_password("my-secret"),
        )
        db_session.add(inst)
        db_session.commit()
        db_session.refresh(inst)

        resp = client.get(f"/instances/{inst.id}/edit")
        assert resp.status_code == 200
        assert "my-cid" in resp.text
        assert 'value="oauth"' in resp.text or "checked" in resp.text

    def test_instance_persisted_with_oauth_fields(self, db_session):
        """Verify OAuth fields round-trip through the database."""
        inst = Instance(
            name="oauth-persist-test",
            url="https://test.service-now.com",
            username="admin",
            password_encrypted=encrypt_password("pass"),
            auth_type="oauth",
            client_id="persist-cid",
            client_secret_encrypted=encrypt_password("persist-secret"),
        )
        db_session.add(inst)
        db_session.commit()
        db_session.refresh(inst)

        loaded = db_session.get(Instance, inst.id)
        assert loaded.auth_type == "oauth"
        assert loaded.client_id == "persist-cid"
        assert decrypt_password(loaded.client_secret_encrypted) == "persist-secret"
