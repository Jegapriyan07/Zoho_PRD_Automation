"""Strict client for the external Zoho Finance RAG MCP service."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

from pipeline.models import AtomicRequirement, RequirementRetrieval, RulebookChunk


class RAGUnavailableError(RuntimeError):
    pass


def _tool_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    content = getattr(value, "content", value)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                texts.append(str(block["text"]))
            elif hasattr(block, "text"):
                texts.append(str(block.text))
        if texts:
            return "".join(texts)
    return str(value)


class RAGMCPClient:
    def __init__(self, url: str | None = None):
        self.url = url or os.getenv("RAG_MCP_URL", "http://localhost:8100/sse")
        self.top_k = int(os.getenv("RAG_TOP_K", "5"))
        self.min_score = float(os.getenv("RAG_MIN_SCORE", "0.35"))
        self.max_context_chars = int(os.getenv("RAG_MAX_CONTEXT_CHARS", "12000"))

    async def _tools(self) -> dict[str, Any]:
        client = MultiServerMCPClient({
            "rag": {
                "transport": "sse",
                "url": self.url,
                "timeout": int(os.getenv("RAG_CONNECT_TIMEOUT", "20")),
                "sse_read_timeout": int(os.getenv("RAG_READ_TIMEOUT", "300")),
            }
        })
        try:
            tools = await client.get_tools()
        except Exception as exc:
            raise RAGUnavailableError(f"Cannot connect to RAG MCP at {self.url}: {exc}") from exc
        return {tool.name: tool for tool in tools}

    async def status(self) -> dict:
        tools = await self._tools()
        raw = await tools["list_categories"].ainvoke({})
        return json.loads(_tool_text(raw))

    @staticmethod
    def _queries(requirement: AtomicRequirement) -> list[str]:
        description = requirement.description.strip()
        finance_context = (
            "Zoho Finance profit and loss report metric formulas revenue expenses "
            "gross profit EBITDA cash flow occupancy current assets and required fields"
        )
        return [
            description,
            f"{finance_context} for {description}",
            f"report setup table columns filters and limitations for {description}",
        ]

    async def _retrieve_with_tools(
        self,
        requirement: AtomicRequirement,
        tools: dict[str, Any],
    ) -> tuple[RequirementRetrieval, list[dict]]:
        queries = self._queries(requirement)
        audit = []
        deduped: dict[str, RulebookChunk] = {}
        try:
            for query in queries:
                arguments = {"query": query, "k": self.top_k, "category": "", "min_score": self.min_score}
                raw = await tools["search_knowledge_base"].ainvoke(arguments)
                payload = json.loads(_tool_text(raw))
                audit.append({"request": arguments, "response": payload})
                for item in payload.get("results", []):
                    identity = "|".join([
                        str(item.get("category", "")), str(item.get("title", "")),
                        str(item.get("heading_path", "")), str(item.get("content", "")),
                    ])
                    chunk_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
                    chunk = RulebookChunk(
                        chunk_id=chunk_id,
                        category=item.get("category", "unknown"),
                        title=item.get("title", "Untitled"),
                        heading_path=item.get("heading_path", ""),
                        content=item.get("content", ""),
                        score=float(item.get("score", 0)),
                        retrieval_query=query,
                    )
                    existing = deduped.get(chunk_id)
                    if existing is None or chunk.score > existing.score:
                        deduped[chunk_id] = chunk
        except Exception as exc:
            return RequirementRetrieval(
                requirement_id=requirement.requirement_id,
                queries=queries,
                grounding_status="ERROR",
                message=str(exc),
            ), audit

        chunks = sorted(deduped.values(), key=lambda item: item.score, reverse=True)
        selected = []
        used_chars = 0
        for chunk in chunks:
            if selected and used_chars + len(chunk.content) > self.max_context_chars:
                continue
            selected.append(chunk)
            used_chars += len(chunk.content)
        return RequirementRetrieval(
            requirement_id=requirement.requirement_id,
            queries=queries,
            chunks=selected,
            grounding_status="GROUNDED" if selected else "NO_MATCH",
            message=None if selected else "No sufficiently relevant Zoho Finance rulebook content was found.",
        ), audit

    async def retrieve(self, requirement: AtomicRequirement) -> tuple[RequirementRetrieval, list[dict]]:
        return await self._retrieve_with_tools(requirement, await self._tools())

    async def retrieve_many(
        self,
        requirements: list[AtomicRequirement],
    ) -> list[tuple[RequirementRetrieval, list[dict]]]:
        tools = await self._tools()
        results = []
        for requirement in requirements:
            results.append(await self._retrieve_with_tools(requirement, tools))
        return results

    def retrieve_sync(self, requirement: AtomicRequirement) -> tuple[RequirementRetrieval, list[dict]]:
        return asyncio.run(self.retrieve(requirement))

    def retrieve_many_sync(
        self,
        requirements: list[AtomicRequirement],
    ) -> list[tuple[RequirementRetrieval, list[dict]]]:
        return asyncio.run(self.retrieve_many(requirements))

    def status_sync(self) -> dict:
        return asyncio.run(self.status())