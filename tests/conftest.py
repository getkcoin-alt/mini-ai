from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from miniai.app import create_app
from miniai.config import Settings


class FakeVault:
    configured = True

    def __init__(self) -> None:
        self.remembered: list[dict[str, Any]] = []

    async def stats(self) -> dict[str, Any]:
        return {"user": "karnveer", "count": len(self.remembered)}

    async def context(self, query: str, *, limit: int = 6) -> dict[str, Any]:
        return {
            "query": query,
            "count": 1,
            "context": "<vault_memories>known preference</vault_memories>",
        }

    async def search(self, query: str, *, limit: int = 8) -> dict[str, Any]:
        return {"query": query, "count": 0, "memories": []}

    async def remember(self, content: str, **kwargs: Any) -> dict[str, Any]:
        row = {"content": content, **kwargs}
        self.remembered.append(row)
        return {"stored": True, "duplicate": False, "id": "memory-1", **row}


class FakeLLM:
    configured = True

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def reply(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return f"Mini heard: {kwargs['message']}"


@pytest.fixture
def app_client(tmp_path: Path):
    settings = Settings(
        mini_admin_api_key="admin-secret",
        mini_data_dir=tmp_path,
        llm_required=True,
        vault_mcp_required=True,
    )
    vault = FakeVault()
    llm = FakeLLM()
    app = create_app(settings, vault=vault, llm=llm)
    with TestClient(app) as client:
        yield client, vault, llm


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"Authorization": "Bearer admin-secret"}
