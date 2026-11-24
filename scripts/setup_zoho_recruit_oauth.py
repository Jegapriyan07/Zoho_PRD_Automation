"""Exchange a Zoho Recruit authorization code for a refresh token."""
from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path

import requests
from dotenv import load_dotenv, set_key


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exchange a Zoho Recruit OAuth authorization code for a refresh token."
    )
    parser.add_argument("--code", help="Authorization code; omit to enter it securely.")
    parser.add_argument(
        "--redirect-uri",
        help="Registered redirect URI, required for client types that use one.",
    )
    parser.add_argument("--env-file", default=".env", help="Environment file to update.")
    args = parser.parse_args()

    env_path = Path(args.env_file)
    load_dotenv(env_path)
    client_id = os.getenv("ZOHO_RECRUIT_CLIENT_ID")
    client_secret = os.getenv("ZOHO_RECRUIT_CLIENT_SECRET")
    accounts_url = os.getenv(
        "ZOHO_RECRUIT_ACCOUNTS_URL", "https://accounts.zoho.eu"
    ).rstrip("/")
    redirect_uri = args.redirect_uri or os.getenv("ZOHO_RECRUIT_REDIRECT_URI")
    if not client_id or not client_secret:
        raise SystemExit(
            "Set ZOHO_RECRUIT_CLIENT_ID and ZOHO_RECRUIT_CLIENT_SECRET in .env first."
        )

    code = args.code or getpass.getpass("Zoho Recruit authorization code: ")
    if not code:
        raise SystemExit("An authorization code is required.")

    token_request = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
    }
    if redirect_uri:
        token_request["redirect_uri"] = redirect_uri

    response = requests.post(
        f"{accounts_url}/oauth/v2/token",
        data=token_request,
        timeout=30,
    )
    try:
        body = response.json()
    except ValueError as exc:
        raise SystemExit(
            f"Zoho Recruit OAuth setup failed with HTTP {response.status_code} "
            "and a non-JSON response."
        ) from exc
    if not response.ok or body.get("error") or not body.get("refresh_token"):
        error = body.get("error") or body.get("error_description") or body.get("message")
        if not error:
            error = f"HTTP {response.status_code}; no OAuth error was returned"
        detail = f"Zoho Recruit OAuth setup failed (HTTP {response.status_code}): {error}"
        if error == "invalid_code":
            detail += (
                ". Authorization codes are single-use and short-lived. Generate a "
                "fresh code for this client and exchange it immediately. For a "
                "server-based client, pass the exact registered redirect URI with "
                "--redirect-uri or ZOHO_RECRUIT_REDIRECT_URI."
            )
        elif error == "invalid_redirect_uri":
            detail += (
                ". Pass the exact redirect URI registered for this OAuth client "
                "using --redirect-uri or ZOHO_RECRUIT_REDIRECT_URI."
            )
        elif error in ("invalid_client", "invalid_client_secret"):
            detail += (
                ". Check the Recruit client ID/secret and use the Accounts server "
                "for the same Zoho data center as the Recruit API."
            )
        elif response.ok and not body.get("refresh_token"):
            detail += (
                ". No refresh token was issued; generate the authorization code "
                "with offline access enabled."
            )
        raise SystemExit(detail)

    env_path.parent.mkdir(parents=True, exist_ok=True)
    set_key(str(env_path), "ZOHO_RECRUIT_REFRESH_TOKEN", body["refresh_token"])
    print(f"Zoho Recruit refresh token saved to {env_path}.")


if __name__ == "__main__":
    main()
