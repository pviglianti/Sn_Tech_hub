# sn_client_factory.py - Centralized ServiceNow client creation from Instance records
#
# All code that needs a ServiceNowClient from a stored Instance should use
# create_client_for_instance() to get a properly configured client regardless
# of auth type (basic or oauth).

import logging
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from .encryption import decrypt_password, encrypt_password
from .sn_client import ServiceNowClient
from .oauth_manager import OAuthTokenManager

if TYPE_CHECKING:
    from ..models import Instance

logger = logging.getLogger(__name__)


def create_client_for_instance(
    instance: "Instance",
    *,
    persist_tokens: bool = True,
) -> ServiceNowClient:
    """Create a ServiceNowClient configured for the instance's auth type.

    Args:
        instance: Instance record with credentials.
        persist_tokens: If True and auth_type is oauth, cache refreshed tokens
                       back to the instance record (caller must commit the session).

    Returns:
        A ready-to-use ServiceNowClient.
    """
    password = ""
    if instance.password_encrypted:
        try:
            password = decrypt_password(instance.password_encrypted)
        except Exception:
            pass

    if instance.auth_type == "oauth" and instance.client_id and instance.client_secret_encrypted:
        client_secret = decrypt_password(instance.client_secret_encrypted)

        # Restore cached tokens if available
        access_token = None
        refresh_token = None
        token_expires_at = instance.oauth_token_expires_at

        if instance.oauth_access_token_encrypted:
            try:
                access_token = decrypt_password(instance.oauth_access_token_encrypted)
            except Exception:
                access_token = None

        if instance.oauth_refresh_token_encrypted:
            try:
                refresh_token = decrypt_password(instance.oauth_refresh_token_encrypted)
            except Exception:
                refresh_token = None

        oauth_mgr = OAuthTokenManager(
            instance_url=instance.url,
            client_id=instance.client_id,
            client_secret=client_secret,
            username=instance.username,
            password=password,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=token_expires_at,
        )

        client = ServiceNowClient(
            instance_url=instance.url,
            username=instance.username,
            password=password,
            instance_id=instance.id,
            auth_type="oauth",
            oauth_manager=oauth_mgr,
        )

        # Cache the tokens back on the instance for persistence
        if persist_tokens:
            _cache_tokens_on_instance(instance, oauth_mgr)

        return client

    # Default: basic auth
    return ServiceNowClient(
        instance_url=instance.url,
        username=instance.username,
        password=password,
        instance_id=instance.id,
    )


def _cache_tokens_on_instance(instance: "Instance", oauth_mgr: OAuthTokenManager) -> None:
    """Write current OAuth tokens back to the instance record (caller commits)."""
    try:
        if oauth_mgr.access_token:
            instance.oauth_access_token_encrypted = encrypt_password(oauth_mgr.access_token)
        if oauth_mgr.refresh_token:
            instance.oauth_refresh_token_encrypted = encrypt_password(oauth_mgr.refresh_token)
        if oauth_mgr.token_expires_at:
            instance.oauth_token_expires_at = oauth_mgr.token_expires_at
    except Exception:
        logger.warning("Failed to cache OAuth tokens on instance %s", instance.id)
