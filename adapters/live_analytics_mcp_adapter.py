"""Read-only Zoho Analytics metadata discovery through an MCP server."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

from pipeline.case_store import CaseStore


def _tool_payload(value: Any) -> Any:
    content = getattr(value, "content", value)
    if isinstance(content, str):
        return json.loads(content)
    if isinstance(content, list):
        text = "".join(
            str(block.get("text", "")) if isinstance(block, dict) else str(getattr(block, "text", ""))
            for block in content
        )
        return json.loads(text)
    return content


class LiveAnalyticsMCPAdapter:
    def __init__(self, workspace_name: str, store: CaseStore, url: str | None = None):
        self.workspace_name = workspace_name
        self.store = store
        self.url = url or os.getenv("ANALYTICS_MCP_URL", "http://localhost:8000/sse")

    async def _tools(self) -> dict[str, Any]:
        client = MultiServerMCPClient({
            "zoho_analytics": {
                "transport": "sse",
                "url": self.url,
                "timeout": int(os.getenv("ANALYTICS_MCP_CONNECT_TIMEOUT", "20")),
                "sse_read_timeout": int(os.getenv("ANALYTICS_MCP_READ_TIMEOUT", "300")),
            }
        })
        try:
            tools = await client.get_tools()
        except Exception as exc:
            raise RuntimeError(f"Cannot connect to Zoho Analytics MCP at {self.url}: {exc}") from exc
        return {tool.name: tool for tool in tools}

    async def _call(self, tools: dict[str, Any], name: str, arguments: dict) -> Any:
        payload = _tool_payload(await tools[name].ainvoke(arguments))
        self.store.log_mcp_call(f"analytics_{name}", arguments, {"result": payload})
        return payload

    async def _as_schema(self) -> dict[str, list[dict[str, str]]]:
        tools = await self._tools()
        workspaces = await self._call(
            tools, "get_workspaces_list", {"include_shared_workspaces": True, "contains_str": self.workspace_name}
        )
        matches = [
            item for item in workspaces
            if item.get("workspaceName", "").casefold() == self.workspace_name.casefold()
        ]
        if len(matches) != 1:
            names = ", ".join(item.get("workspaceName", "unknown") for item in workspaces)
            raise ValueError(
                f"Workspace '{self.workspace_name}' was not uniquely found. Matching workspaces: {names or 'none'}"
            )

        workspace_id = matches[0].get("workspaceId")
        views = await self._call(
            tools, "search_views", {"workspace_id": workspace_id, "allowedViewTypesIds": [0, 6]}
        )
        if not isinstance(views, list) or any("error" in view for view in views if isinstance(view, dict)):
            raise RuntimeError(f"Could not list metadata views for workspace '{self.workspace_name}': {views}")

        schema: dict[str, list[dict[str, str]]] = {}
        for view in views:
            details = await self._call(tools, "get_view_details", {"view_id": view["viewId"]})
            if not isinstance(details, dict) or details.get("error"):
                continue
            name = details.get("viewName") or view.get("viewName")
            if name:
                schema[name] = [
                    {"name": column.get("columnName", "unknown"), "type": column.get("dataType", "unknown")}
                    for column in details.get("columns", [])
                    if isinstance(column, dict)
                ]
        if not schema:
            raise RuntimeError(f"No table metadata could be retrieved for workspace '{self.workspace_name}'.")
        return schema

    def as_schema(self) -> dict[str, list[dict[str, str]]]:
        return asyncio.run(self._as_schema())