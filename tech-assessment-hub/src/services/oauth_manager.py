# oauth_manager.py - OAuth2 token management for ServiceNow instances
#
# Supports the Password Grant flow (most compatible across SN versions):
#   POST /oauth_token.do  grant_type=password
#   Requires: client_id, client_secret, username, password
#
# Also supports token refresh via refresh_token grant.

import logging
import time
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# Buffer before actual expiry to avoid edge-case 401s
TOKEN_EXPIRY_BUFFER_SECONDS = 60


class OAuthError(Exception):
    """Raised when OAuth token exchange or refresh fails."""
    pass


class OAuthTokenManager:
    """Manages OAuth2 token lifecycle for a ServiceNow instance.

    Handles initial token exchange (password grant), token refresh,
    and expiry tracking. Tokens can be cached on the Instance record
    to survive process restarts.
    """

    def __init__(
        self,
        instance_url: str,
        client_id: str,
        client_secret: str,
        username: str,
        password: str,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        token_expires_at: Optional[datetime] = None,
    ):
        self.instance_url = instance_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_expires_at = token_expires_at

    @property
    def token_endpoint(self) -> str:
        return f"{self.instance_url}/oauth_token.do"

    def is_token_valid(self) -> bool:
        """Check if the current access token is still valid."""
        if not self.access_token or not self.token_expires_at:
            return False
        return datetime.utcnow() < (
            self.token_expires_at - timedelta(seconds=TOKEN_EXPIRY_BUFFER_SECONDS)
        )

    def get_access_token(self) -> str:
        """Return a valid access token, refreshing or re-authenticating as needed."""
        if self.is_token_valid():
            return self.access_token

        # Try refresh first if we have a refresh token
        if self.refresh_token:
            try:
                return self._refresh_token()
            except OAuthError:
                logger.warning("OAuth refresh failed, falling back to full auth")

        # Full password grant
        return self._password_grant()

    def _password_grant(self) -> str:
        """Exchange credentials for an access token using password grant."""
        data = {
            "grant_type": "password",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "username": self.username,
            "password": self.password,
        }
        return self._exchange_token(data)

    def _refresh_token(self) -> str:
        """Use refresh token to obtain a new access token."""
        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
        }
        return self._exchange_token(data)

    def _exchange_token(self, data: Dict[str, str]) -> str:
        """Execute the token exchange and update internal state."""
        try:
            response = requests.post(
                self.token_endpoint,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
            )
        except requests.exceptions.ConnectionError:
            raise OAuthError(
                f"Could not connect to {self.token_endpoint}. Check the instance URL."
            )
        except requests.exceptions.Timeout:
            raise OAuthError("OAuth token request timed out.")

        if response.status_code != 200:
            # ServiceNow returns JSON error body on failure
            detail = ""
            try:
                body = response.json()
                detail = body.get("error_description", body.get("error", ""))
            except Exception:
                detail = response.text[:200]
            raise OAuthError(
                f"OAuth token exchange failed (HTTP {response.status_code}): {detail}"
            )

        try:
            token_data = response.json()
        except ValueError:
            raise OAuthError("OAuth response was not valid JSON.")

        self.access_token = token_data.get("access_token")
        if not self.access_token:
            raise OAuthError("OAuth response did not contain an access_token.")

        # Update refresh token if a new one was issued
        if token_data.get("refresh_token"):
            self.refresh_token = token_data["refresh_token"]

        # Calculate expiry
        expires_in = int(token_data.get("expires_in", 1800))
        self.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

        logger.info(
            "OAuth token obtained for %s (expires in %ds)",
            self.instance_url,
            expires_in,
        )
        return self.access_token

    def force_refresh(self) -> str:
        """Force a new token exchange regardless of current token state."""
        self.access_token = None
        self.token_expires_at = None
        return self.get_access_token()
