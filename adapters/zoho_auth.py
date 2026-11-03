"""OAuth token handling for the Zoho Analytics REST API."""
from __future__ import annotations

import os
import time
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()


class ZohoOAuthError(RuntimeError):
    """Raised when Zoho cannot issue an access token."""


class ZohoOAuthClient:
    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
        accounts_url: str | None = None,
        timeout: int = 30,
        expiry_skew: int = 60,
        session: requests.Session | None = None,
    ):
        self.client_id = client_id or os.getenv("ANALYTICS_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("ANALYTICS_CLIENT_SECRET")
        self.refresh_token = refresh_token or os.getenv("ANALYTICS_REFRESH_TOKEN")
        self.accounts_url = (
            accounts_url or os.getenv("ACCOUNTS_SERVER_URL", "https://accounts.zoho.in")
        ).rstrip("/")
        self.timeout = timeout
        self.expiry_skew = expiry_skew
        self.session = session or requests.Session()
        self._access_token: str | None = None
        self._expires_at = 0.0

    def get_access_token(self, force_refresh: bool = False) -> str:
        if (
            not force_refresh
            and self._access_token
            and time.time() < self._expires_at - self.expiry_skew
        ):
            return self._access_token

        if not all((self.client_id, self.client_secret, self.refresh_token)):
            raise ZohoOAuthError(
                "Set ANALYTICS_CLIENT_ID, ANALYTICS_CLIENT_SECRET, and "
                "ANALYTICS_REFRESH_TOKEN in .env."
            )

        response = self.session.post(
            f"{self.accounts_url}/oauth/v2/token",
            data={
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
            },
            timeout=self.timeout,
        )
        try:
            body: dict[str, Any] = response.json()
        except ValueError as exc:
            raise ZohoOAuthError(
                f"Zoho token endpoint returned HTTP {response.status_code} with a non-JSON response."
            ) from exc
        if not response.ok or body.get("error"):
            error = body.get("error") or body.get("message") or f"HTTP {response.status_code}"
            raise ZohoOAuthError(f"Zoho OAuth refresh failed: {error}")
        token = body.get("access_token")
        if not token:
            raise ZohoOAuthError("Zoho OAuth response did not contain an access_token.")

        self._access_token = str(token)
        self._expires_at = time.time() + int(body.get("expires_in", 3600))
        return self._access_token
