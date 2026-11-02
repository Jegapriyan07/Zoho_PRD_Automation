"""Read-only Zoho Analytics workspace metadata export.

The export intentionally stores raw endpoint responses so new projects retain
catalog information that is not needed by the SQL discovery stage yet.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


class ZohoMetadataExporter:
    def __init__(
        self,
        org_id: str,
        client_id: str | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
        access_token: str | None = None,
        analytics_url: str | None = None,
        accounts_url: str | None = None,
        timeout: int = 30,
    ):
        self.org_id = org_id
        self.client_id = client_id or os.getenv("ANALYTICS_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("ANALYTICS_CLIENT_SECRET")
        self.refresh_token = refresh_token or os.getenv("ANALYTICS_REFRESH_TOKEN")
        self.access_token = access_token or os.getenv("ANALYTICS_ACCESS_TOKEN")
        self.analytics_url = (analytics_url or os.getenv(
            "ANALYTICS_SERVER_URL", "https://analyticsapi.zoho.com"
        )).rstrip("/")
        self.accounts_url = (accounts_url or os.getenv(
            "ACCOUNTS_SERVER_URL", "https://accounts.zoho.com"
        )).rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def _get_access_token(self) -> str:
        if self.access_token:
            return self.access_token
        if not all((self.client_id, self.client_secret, self.refresh_token)):
            raise ValueError(
                "Set ANALYTICS_ACCESS_TOKEN or ANALYTICS_CLIENT_ID, "
                "ANALYTICS_CLIENT_SECRET, and ANALYTICS_REFRESH_TOKEN."
            )
        response = self.session.post(
            f"{self.accounts_url}/oauth/v2/token",
            params={
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        self.access_token = response.json()["access_token"]
        return self.access_token

    @staticmethod
    def _id(item: dict[str, Any], *names: str) -> str | None:
        for name in names:
            value = item.get(name)
            if value is not None:
                return str(value)
        return None

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.get(
            f"{self.analytics_url}{path}",
            params=params,
            headers={
                "Authorization": f"Zoho-oauthtoken {self._get_access_token()}",
                "ZANALYTICS-ORGID": self.org_id,
            },
            timeout=self.timeout,
        )
        try:
            body = response.json()
        except ValueError:
            body = {"text": response.text}
        if not response.ok:
            raise RuntimeError(f"HTTP {response.status_code}: {body}")
        return body

    def _capture(
        self,
        catalog: dict[str, Any],
        key: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        try:
            value = self._get(path, params)
            catalog[key] = value
            return value
        except Exception as exc:
            catalog.setdefault("errors", []).append({"endpoint": path, "error": str(exc)})
            catalog[key] = None
            return None

    def get_table_metadata(self, workspace_id: str, view_id: str) -> dict[str, Any]:
        """Fetch one table's columns using Zoho's documented metadata endpoint."""
        return self._get(
            f"/restapi/v2/workspaces/{quote(str(workspace_id))}/views/"
            f"{quote(str(view_id))}/metadata"
        )

    def collect(self) -> dict[str, Any]:
        catalog: dict[str, Any] = {
            "format": "zoho-analytics-metadata",
            "format_version": 1,
            "source": "Zoho Analytics REST API v2",
            "org_id": self.org_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "errors": [],
        }
        self._capture(catalog, "organizations", "/restapi/v2/orgs")
        self._capture(catalog, "organization_users", "/restapi/v2/users")
        self._capture(catalog, "organization_admins", "/restapi/v2/orgadmins")
        workspaces = self._capture(catalog, "workspaces", "/restapi/v2/workspaces") or {}
        self._capture(catalog, "owned_workspaces", "/restapi/v2/workspaces/owned")
        self._capture(catalog, "shared_workspaces", "/restapi/v2/workspaces/shared")
        self._capture(catalog, "dashboards", "/restapi/v2/dashboards")
        self._capture(catalog, "owned_dashboards", "/restapi/v2/dashboards/owned")
        self._capture(catalog, "shared_dashboards", "/restapi/v2/dashboards/shared")
        self._capture(catalog, "recent_views", "/restapi/v2/recentviews")

        workspace_items = workspaces.get("data", workspaces) if isinstance(workspaces, dict) else workspaces
        if isinstance(workspace_items, dict):
            workspace_items = workspace_items.get("workspaces", [])
        catalog["workspace_catalog"] = {}
        for workspace in workspace_items or []:
            workspace_id = self._id(workspace, "workspaceId", "id")
            if not workspace_id:
                continue
            prefix = f"workspace_catalog.{workspace_id}"
            item: dict[str, Any] = {"summary": workspace}
            catalog["workspace_catalog"][workspace_id] = item
            for key, suffix in (
                ("details", ""),
                ("admins", "/admins"),
                ("users", "/users"),
                ("sharing", "/share"),
                ("folders", "/folders"),
                ("groups", "/groups"),
                ("variables", "/variables"),
                ("datasources", "/datasources"),
                ("aggregate_formulas", "/aggregateformulas"),
            ):
                item[key] = self._capture(catalog, f"{prefix}.{key}", f"/restapi/v2/workspaces/{quote(workspace_id)}{suffix}")
            views = item["views"] = self._capture(
                catalog, f"{prefix}.views", f"/restapi/v2/workspaces/{quote(workspace_id)}/views"
            )
            view_items = views.get("data", views) if isinstance(views, dict) else views
            if isinstance(view_items, dict):
                view_items = view_items.get("views", [])
            item["view_catalog"] = {}
            for view in view_items or []:
                view_id = self._id(view, "viewId", "id")
                if not view_id:
                    continue
                view_item: dict[str, Any] = {"summary": view}
                item["view_catalog"][view_id] = view_item
                view_path = f"/restapi/v2/views/{quote(view_id)}"
                view_item["metadata"] = self._capture(
                    catalog,
                    f"{prefix}.view_catalog.{view_id}.metadata",
                    f"/restapi/v2/workspaces/{quote(workspace_id)}/views/{quote(view_id)}/metadata",
                )
                for key, path in (
                    ("details", view_path),
                    ("permissions", f"/restapi/v2/workspaces/{quote(workspace_id)}/views/{quote(view_id)}/share/userpermissions"),
                    ("formula_columns", f"/restapi/v2/workspaces/{quote(workspace_id)}/views/{quote(view_id)}/formulacolumns"),
                    ("aggregate_formulas", f"/restapi/v2/workspaces/{quote(workspace_id)}/views/{quote(view_id)}/aggregateformulas"),
                    ("dependents", f"{view_path}/dependents"),
                    ("import_details", f"/restapi/v2/workspaces/{quote(workspace_id)}/views/{quote(view_id)}/importdetails"),
                ):
                    view_item[key] = self._capture(catalog, f"{prefix}.view_catalog.{view_id}.{key}", path)
            self._capture(
                catalog,
                f"{prefix}.shared_view_details",
                f"/restapi/v2/workspaces/{quote(workspace_id)}/share/shareddetails",
            )
        return catalog

    def export(self, output_path: str) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.collect(), indent=2), encoding="utf-8")
        return path