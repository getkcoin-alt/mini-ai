from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


class VaultUnavailable(RuntimeError):
    pass


class VaultClient:
    def __init__(self, url: str, api_key: str, *, timeout: float = 12.0) -> None:
        self.url = url.strip()
        self.api_key = api_key.strip()
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.url and self.api_key)

    @staticmethod
    def _payload(result: Any) -> dict[str, Any]:
        structured = getattr(result, "structuredContent", None)
        if isinstance(structured, dict):
            return structured
        for block in getattr(result, "content", []):
            text = getattr(block, "text", None)
            if not text:
                continue
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        raise VaultUnavailable("Vault MCP returned no structured result")

    async def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise VaultUnavailable("Vault MCP is not configured")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with asyncio.timeout(self.timeout):
                async with httpx2.AsyncClient(headers=headers) as http_client:
                    async with streamable_http_client(
                        self.url,
                        http_client=http_client,
                    ) as streams:
                        read_stream, write_stream = streams[0], streams[1]
                        async with ClientSession(read_stream, write_stream) as session:
                            await session.initialize()
                            result = await session.call_tool(tool, arguments=arguments)
            if getattr(result, "isError", False):
                raise VaultUnavailable("Vault MCP tool returned an error")
            return self._payload(result)
        except VaultUnavailable:
            raise
        except Exception as exc:
            raise VaultUnavailable(f"Vault MCP request failed: {type(exc).__name__}") from exc

    async def stats(self) -> dict[str, Any]:
        return await self.call("vault_memory_stats", {})

    async def context(self, query: str, *, limit: int = 6) -> dict[str, Any]:
        return await self.call(
            "vault_memory_context", {"query": query, "limit": limit, "max_chars": 4000}
        )

    async def search(self, query: str, *, limit: int = 8) -> dict[str, Any]:
        return await self.call("vault_memory_search", {"query": query, "limit": limit})

    async def remember(
        self,
        content: str,
        *,
        kind: str = "factual",
        importance: float = 0.7,
        client: str = "mini-ai",
    ) -> dict[str, Any]:
        return await self.call(
            "vault_memory_remember",
            {
                "content": content,
                "kind": kind,
                "importance": importance,
                "client": client,
            },
        )
