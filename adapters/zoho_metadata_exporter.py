"""Read-only Zoho Analytics workspace metadata export."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from dotenv import load_dotenv

from adapters.zoho_auth import ZohoOAuthClient

load_dotenv()


class ZohoMetadataExporter:
    def __init__(
        self,
        org_id: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
        access_token: str | None = None,
        workspace_id: str | None = None,
        analytics_url: str | None = None,
        accounts_url: str | None = None,
        timeout: int = 30,
    ):
        self.org_id = org_id or os.getenv("ANALYTICS_ORG_ID")
        if not self.org_id:
            raise ValueError(
                "Set ANALYTICS_ORG_ID in .env or pass --org-id when exporting metadata."
            )
        self.access_token = access_token or os.getenv("ANALYTICS_ACCESS_TOKEN")
        self.workspace_id = workspace_id
        self.analytics_url = (
            analytics_url or os.getenv(
                "ANALYTICS_SERVER_URL", "https://analyticsapi.zoho.in"
            )
        ).rstrip("/")
        self.accounts_url = (
            accounts_url or os.getenv(
                "ACCOUNTS_SERVER_URL", "https://accounts.zoho.in"
            )
        ).rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.oauth = ZohoOAuthClient(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            accounts_url=self.accounts_url,
            timeout=timeout,
            session=self.session,
        )

    def get_access_token(self, force_refresh: bool = False) -> str:
        """Return a cached access token or refresh it before expiry."""
        if self.access_token and not force_refresh:
            return self.access_token
        self.access_token = self.oauth.get_access_token(force_refresh=force_refresh)
        return self.access_token

    @staticmethod
    def _id(item: dict[str, Any], *names: str) -> str | None:
        for name in names:
            value = item.get(name)
            if value is not None:
                return str(value)
        return None

    @staticmethod
    def _items(body: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
        if isinstance(body, list):
            return [item for item in body if isinstance(item, dict)]
        if not isinstance(body, dict):
            return []
        for key in keys:
            value = body.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        data = body.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            nested = ZohoMetadataExporter._items(data, keys)
            if nested:
                return nested
            for value in data.values():
                if isinstance(value, list) and all(isinstance(item, dict) for item in value):
                    return value
        return []

    def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        _rate_retry: int = 0,
    ) -> Any:
        for attempt in range(2):
            response = self.session.get(
                f"{self.analytics_url}{path}",
                params=params,
                headers={
                    "Authorization": f"Zoho-oauthtoken {self.get_access_token()}",
                    "ZANALYTICS-ORGID": self.org_id,
                },
                timeout=self.timeout,
            )
            if response.status_code != 401 or attempt:
                break
            self.get_access_token(force_refresh=True)

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit() and _rate_retry == 0:
                time.sleep(min(int(retry_after), 30))
                return self._get(path, params, _rate_retry=1)
        try:
            body = response.json()
        except ValueError:
            body = {"text": response.text}
        if not response.ok:
            error = body.get("message") or body.get("error") if isinstance(body, dict) else body
            raise RuntimeError(f"Zoho Analytics HTTP {response.status_code}: {error}")
        return body

    def _get_all(self, path: str, keys: tuple[str, ...]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            body = self._get(path, {"page": page, "limit": 200})
            page_items = self._items(body, keys)
            items.extend(page_items)
            if not isinstance(body, dict):
                break
            info = body.get("info") if isinstance(body.get("info"), dict) else body
            has_more = info.get("hasMore") or info.get("has_more")
            next_page = info.get("nextPage") or info.get("next_page")
            if next_page:
                page = int(next_page)
            elif has_more:
                page += 1
            else:
                break
        return items

    def get_organizations(self) -> list[dict[str, Any]]:
        return self._get_all("/restapi/v2/orgs", ("organizations", "orgs"))

    def get_workspaces(self, org_id: str | None = None) -> list[dict[str, Any]]:
        if org_id and org_id != self.org_id:
            raise ValueError("The requested org_id does not match the configured ANALYTICS_ORG_ID.")
        return self._get_all("/restapi/v2/workspaces", ("workspaces", "workspace", "items"))

    def get_tables(self, workspace_id: str) -> list[dict[str, Any]]:
        return self._get_all(
            f"/restapi/v2/workspaces/{quote(str(workspace_id))}/views",
            ("views", "view", "items"),
        )

    def get_columns(self, workspace_id: str, table_id: str) -> list[dict[str, Any]]:
        body = self._get(
            f"/restapi/v2/workspaces/{quote(str(workspace_id))}/views/"
            f"{quote(str(table_id))}/metadata"
        )
        return self._items(body, ("columns", "column", "items"))

    def collect(self) -> dict[str, Any]:
        catalog: dict[str, Any] = {
            "format": "zoho-analytics-metadata",
            "format_version": 2,
            "source": "Zoho Analytics REST API v2",
            "org_id": self.org_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "errors": [],
            "workspace_catalog": {},
        }
        try:
            organizations = self.get_organizations()
        except Exception as exc:
            organizations = []
            catalog["errors"].append({"endpoint": "/restapi/v2/orgs", "error": str(exc)})
        try:
            workspaces_response = self._get(
                "/restapi/v2/workspaces", {"page": 1, "limit": 200}
            )
            workspaces = self._items(
                workspaces_response, ("workspaces", "workspace", "items")
            )
            if not workspaces:
                catalog["raw_workspaces_response"] = workspaces_response
                catalog["errors"].append({
                    "endpoint": "/restapi/v2/workspaces",
                    "error": "HTTP 200 response did not contain a recognized workspace list.",
                })
        except Exception as exc:
            workspaces = []
            catalog["errors"].append({"endpoint": "/restapi/v2/workspaces", "error": str(exc)})

        organization = next(
            (
                item for item in organizations
                if self._id(item, "orgId", "organizationId", "id") == self.org_id
            ),
            {},
        )
        catalog["organizations"] = organizations
        catalog["workspaces"] = workspaces
        if self.workspace_id:
            workspaces = [
                workspace for workspace in workspaces
                if self._id(workspace, "workspaceId", "id") == self.workspace_id
            ]
            if not workspaces:
                raise RuntimeError(
                    f"Configured workspace ID '{self.workspace_id}' "
                    "was not found among accessible workspaces."
                )

        for workspace in workspaces:
            workspace_id = self._id(workspace, "workspaceId", "id")
            if not workspace_id:
                continue
            item: dict[str, Any] = {"summary": workspace, "view_catalog": {}}
            catalog["workspace_catalog"][workspace_id] = item
            try:
                views = self.get_tables(workspace_id)
            except Exception as exc:
                views = []
                catalog["errors"].append({
                    "endpoint": f"/restapi/v2/workspaces/{workspace_id}/views",
                    "error": str(exc),
                })
            item["views"] = views
            for view in views:
                view_id = self._id(view, "viewId", "tableId", "id")
                if not view_id:
                    continue
                view_item: dict[str, Any] = {"summary": view}
                item["view_catalog"][view_id] = view_item
                try:
                    view_item["metadata"] = {
                        "columns": self.get_columns(workspace_id, view_id)
                    }
                except Exception as exc:
                    view_item["metadata"] = None
                    catalog["errors"].append({
                        "endpoint": (
                            f"/restapi/v2/workspaces/{workspace_id}/views/"
                            f"{view_id}/metadata"
                        ),
                        "error": str(exc),
                    })

        catalog["metadata"] = {
            "organization": {
                "org_id": self.org_id,
                "org_name": organization.get("orgName") or organization.get("name"),
            },
            "workspaces": [
                {
                    "workspace_id": workspace_id,
                    "workspace_name": item["summary"].get("workspaceName")
                    or item["summary"].get("name"),
                    "tables": [
                        {
                            "table_id": view_id,
                            "table_name": view["summary"].get("viewName")
                            or view["summary"].get("tableName")
                            or view["summary"].get("name"),
                            "columns": (view.get("metadata") or {}).get("columns", []),
                        }
                        for view_id, view in item["view_catalog"].items()
                    ],
                }
                for workspace_id, item in catalog["workspace_catalog"].items()
            ],
        }
        if not catalog["workspace_catalog"]:
            raise RuntimeError(
                "Zoho metadata discovery returned no accessible workspaces. "
                f"Details: {catalog['errors']}"
            )
        return catalog

    def extract_complete_metadata(self) -> dict[str, Any]:
        """Return the normalized organization/workspace/table/column structure."""
        return self.collect()["metadata"]

    def export(self, output_path: str) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.collect(), indent=2), encoding="utf-8")
        return path
