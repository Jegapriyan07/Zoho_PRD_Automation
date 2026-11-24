"""Read-only Zoho Recruit module and field metadata export."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from dotenv import load_dotenv

from adapters.zoho_auth import ZohoOAuthClient

load_dotenv()


class ZohoRecruitMetadataExporter:
    def __init__(
        self,
        modules: list[str] | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
        recruit_url: str | None = None,
        accounts_url: str | None = None,
        timeout: int = 30,
        session: requests.Session | None = None,
        fields_only: bool = False,
    ):
        self.fields_only = fields_only
        self.modules = modules or [
            item.strip()
            for item in os.getenv("ZOHO_RECRUIT_MODULES", "").split(",")
            if item.strip()
        ]
        if not self.modules:
            raise ValueError(
                "Provide Recruit module API names or set ZOHO_RECRUIT_MODULES."
            )

        self.client_id = client_id or os.getenv("ZOHO_RECRUIT_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("ZOHO_RECRUIT_CLIENT_SECRET")
        self.refresh_token = refresh_token or os.getenv("ZOHO_RECRUIT_REFRESH_TOKEN")
        if not all((self.client_id, self.client_secret, self.refresh_token)):
            raise ValueError(
                "Set ZOHO_RECRUIT_CLIENT_ID, ZOHO_RECRUIT_CLIENT_SECRET, and "
                "ZOHO_RECRUIT_REFRESH_TOKEN in .env."
            )

        self.recruit_url = (
            recruit_url
            or os.getenv("ZOHO_RECRUIT_API_URL", "https://recruit.zoho.eu/recruit/v2")
        ).rstrip("/")
        self.accounts_url = (
            accounts_url
            or os.getenv("ZOHO_RECRUIT_ACCOUNTS_URL", "https://accounts.zoho.eu")
        ).rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.oauth = ZohoOAuthClient(
            client_id=self.client_id,
            client_secret=self.client_secret,
            refresh_token=self.refresh_token,
            accounts_url=self.accounts_url,
            timeout=timeout,
            session=self.session,
        )

    def _get(
        self,
        path: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        for attempt in range(2):
            response = self.session.get(
                f"{self.recruit_url}{path}",
                params=params,
                headers={
                    "Authorization": f"Zoho-oauthtoken "
                    f"{self.oauth.get_access_token(force_refresh=bool(attempt))}"
                },
                timeout=self.timeout,
            )
            if response.status_code != 401 or attempt:
                break

        try:
            body = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"Zoho Recruit returned HTTP {response.status_code} with a non-JSON response."
            ) from exc
        if not response.ok:
            error = body.get("message") or body.get("code") if isinstance(body, dict) else body
            raise RuntimeError(f"Zoho Recruit HTTP {response.status_code}: {error}")
        if not isinstance(body, dict):
            raise RuntimeError("Zoho Recruit returned an unexpected metadata response.")
        return body

    @staticmethod
    def _items(body: dict[str, Any], key: str) -> list[dict[str, Any]]:
        items = body.get(key)
        if not isinstance(items, list):
            raise RuntimeError(f"Zoho Recruit metadata response did not contain '{key}'.")
        return [item for item in items if isinstance(item, dict)]

    def collect(self) -> dict[str, Any]:
        catalog: dict[str, Any] = {
            "format": "zoho-recruit-metadata",
            "format_version": 1,
            "source": "Zoho Recruit REST API v2",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "modules": [],
            "entities": [],
        }
        if self.fields_only:
            catalog["metadata_scope"] = "fields-only"
            catalog["limitations"] = [
                "Module-level metadata was not collected; entity names are the requested module API names."
            ]

        for module_api_name in self.modules:
            module_details: dict[str, Any] = {}
            if not self.fields_only:
                encoded_name = quote(module_api_name, safe="")
                module_response = self._get(f"/settings/modules/{encoded_name}")
                module_items = self._items(module_response, "modules")
                if not module_items:
                    raise RuntimeError(
                        f"Zoho Recruit returned no module metadata for '{module_api_name}'."
                    )
                module_details = module_items[0]

            fields_response = self._get(
                "/settings/fields",
                params={"module": module_api_name},
            )
            fields = self._items(fields_response, "fields")
            normalized_fields = [
                {
                    "name": field.get("api_name") or field.get("name"),
                    "data_type": field.get("data_type") or field.get("json_type"),
                    "description": field.get("field_label") or field.get("display_label"),
                }
                for field in fields
                if field.get("api_name") or field.get("name")
            ]
            if not normalized_fields:
                raise RuntimeError(
                    f"Zoho Recruit returned no named fields for '{module_api_name}'."
                )

            module_name = (
                module_details.get("module_name")
                or module_details.get("plural_label")
                or module_details.get("api_name")
                or module_api_name
            )
            catalog["modules"].append({
                "api_name": module_api_name,
                "metadata": None if self.fields_only else module_details,
                "fields": fields,
            })
            catalog["entities"].append({
                "name": module_name,
                "module": "Zoho Recruit",
                "description": module_details.get("singular_label"),
                "fields": normalized_fields,
                "relationships": [],
            })

        return catalog

    def export(self, output_path: str) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.collect(), indent=2), encoding="utf-8")
        return path
