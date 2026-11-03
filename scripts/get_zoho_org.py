"""List Zoho Analytics organizations accessible to the configured OAuth user."""
from __future__ import annotations

import os

import requests
from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    client_id = os.getenv("ANALYTICS_CLIENT_ID")
    client_secret = os.getenv("ANALYTICS_CLIENT_SECRET")
    refresh_token = os.getenv("ANALYTICS_REFRESH_TOKEN")
    if not all((client_id, client_secret, refresh_token)):
        raise SystemExit(
            "Missing ANALYTICS_CLIENT_ID, ANALYTICS_CLIENT_SECRET, or "
            "ANALYTICS_REFRESH_TOKEN in .env."
        )

    org_id = os.getenv("ANALYTICS_ORG_ID")
    accounts_url = os.getenv(
        "ACCOUNTS_SERVER_URL", "https://accounts.zoho.in"
    ).rstrip("/")
    analytics_url = os.getenv(
        "ANALYTICS_SERVER_URL", "https://analyticsapi.zoho.in"
    ).rstrip("/")

    token_response = requests.post(
        f"{accounts_url}/oauth/v2/token",
        data={
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    try:
        token_body = token_response.json()
    except ValueError as exc:
        raise SystemExit(
            f"Access token generation failed with HTTP {token_response.status_code}."
        ) from exc
    if not token_response.ok or "access_token" not in token_body:
        message = token_body.get("message") or token_body.get("error")
        raise SystemExit(f"Access token generation failed: {message or 'unknown error'}")
    access_token = token_body["access_token"]
    token_scope = token_body.get("scope", "")
    print("OAuth token generated.")
    if token_scope:
        print("Granted OAuth scope:", token_scope)
        granted_scopes = token_scope.replace(",", " ").split()
        if "ZohoAnalytics.metadata.read" not in granted_scopes:
            print("WARNING: ZohoAnalytics.metadata.read is not present in the granted scope.")
    else:
        print("Granted OAuth scope was not returned by Zoho.")

    response = requests.get(
        f"{analytics_url}/restapi/v2/orgs",
        headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
        timeout=30,
    )
    try:
        body = response.json()
    except ValueError as exc:
        raise SystemExit(
            f"Organization retrieval failed with HTTP {response.status_code}."
        ) from exc

    if not response.ok:
        message = body.get("message") or body.get("error") if isinstance(body, dict) else body
        raise SystemExit(f"Organization retrieval failed: {message}")

    print("\n========== ZOHO API DEBUG ==========")
    print("HTTP Status:", response.status_code)
    print("API Response:")
    print(response.text)
    print("===================================")

    organizations = body.get("data", {}).get("orgs", []) if isinstance(body, dict) else []
    if not organizations:
        print("\nNo organizations found.")
        print(
            "Zoho returned HTTP 200 with an empty orgs list, so the token is valid "
            "but this Zoho account has no Analytics organization visible to this API."
        )
        print("Verify all of the following:")
        print("1. Open Zoho Analytics using the same account that created the Self Client.")
        print("2. Confirm that at least one Analytics workspace exists or is shared with that account.")
        print("3. Confirm the account and API Console are in the same data center (India: zoho.in).")
        print("4. If Analytics was just enabled, sign out/in and retry after provisioning completes.")
        return

    print("\nAvailable Zoho Analytics Organizations:")
    for organization in organizations:
        print("------------------------------")
        print("Organization Name:", organization.get("orgName", "Unknown"))
        print("Organization ID:", organization.get("orgId", "Unknown"))
        if org_id and str(organization.get("orgId")) == org_id:
            print("Status: Matches ANALYTICS_ORG_ID")


if __name__ == "__main__":
    main()
