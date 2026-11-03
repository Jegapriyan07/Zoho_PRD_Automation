"""Exchange a Zoho authorization code for a refresh token and update .env."""
from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path

import requests
from dotenv import load_dotenv, set_key


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exchange a Zoho OAuth authorization code for a refresh token."
    )
    parser.add_argument("--code", help="Authorization code; omit to enter it securely.")
    parser.add_argument("--env-file", default=".env", help="Environment file to update.")
    args = parser.parse_args()

    env_path = Path(args.env_file)
    load_dotenv(env_path)
    client_id = os.getenv("ANALYTICS_CLIENT_ID")
    client_secret = os.getenv("ANALYTICS_CLIENT_SECRET")
    accounts_url = os.getenv("ACCOUNTS_SERVER_URL", "https://accounts.zoho.in").rstrip("/")
    if not client_id or not client_secret:
        raise SystemExit(
            "Set ANALYTICS_CLIENT_ID and ANALYTICS_CLIENT_SECRET in .env before running setup."
        )

    code = args.code or getpass.getpass("Zoho authorization code: ")
    if not code:
        raise SystemExit("An authorization code is required.")

    response = requests.post(
        f"{accounts_url}/oauth/v2/token",
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    try:
        body = response.json()
    except ValueError as exc:
        raise SystemExit(f"Zoho OAuth setup failed with HTTP {response.status_code}.") from exc
    if not response.ok or body.get("error") or not body.get("refresh_token"):
        error = body.get("error") or body.get("message") or f"HTTP {response.status_code}"
        raise SystemExit(f"Zoho OAuth setup failed: {error}")

    env_path.parent.mkdir(parents=True, exist_ok=True)
    set_key(str(env_path), "ANALYTICS_REFRESH_TOKEN", body["refresh_token"])
    print(f"Refresh token saved to {env_path}.")


if __name__ == "__main__":
    main()
