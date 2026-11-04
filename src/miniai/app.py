import asyncio
import hmac
import json
import re
from importlib.resources import files
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from miniai import __version__
from miniai.config import Settings, get_settings
from miniai.limits import WindowLimiter
from miniai.llm import CompanionLLM, LLMUnavailable
from miniai.security import generate_pin
from miniai.store import Tenant, TenantStore
from miniai.vault import VaultClient, VaultUnavailable


class OnboardRequest(BaseModel):
    owner_name: str = Field(min_length=1, max_length=80)
    pin: str | None = None
    vault_enabled: bool = False


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    mode: str = Field(default="friend", pattern="^(friend|mentor)$")
    remember: bool = False
    remember_private: bool = False


class VaultSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    limit: int = Field(default=8, ge=1, le=50)


class VaultRememberRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    kind: str = Field(
        default="factual",
        pattern="^(episodic|semantic|factual|procedural|reflection)$",
    )
    importance: float = Field(default=0.7, ge=0.0, le=1.0)


class PreferencesRequest(BaseModel):
    tone: Literal["warm", "direct", "gentle"] = "warm"
    focus: str = Field(default="", max_length=500)
    mode: Literal["friend", "mentor"] = "friend"
    memory_enabled: bool = False


class MemoryRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class GoalRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    next_step: str = Field(min_length=1, max_length=500)


class CheckinRequest(BaseModel):
    note: str = Field(min_length=1, max_length=1000)
    next_step: str = Field(min_length=1, max_length=500)
    complete: bool = False


class PinRequest(BaseModel):
    pin: str = Field(pattern=r"^[0-9]{6,12}$")


class EraseRequest(BaseModel):
    confirmation: Literal["DELETE MY MINI DATA"]


def _bearer(authorization: str | None) -> str:
    value = (authorization or "").strip()
    if value.lower().startswith("bearer "):
        return value.split(" ", 1)[1].strip()
    return ""


def create_app(
    settings: Settings | None = None,
    *,
    store: TenantStore | None = None,
    vault: VaultClient | None = None,
    llm: CompanionLLM | None = None,
) -> FastAPI:
    cfg = settings or get_settings()
    tenant_store = store or TenantStore(cfg.mini_data_dir)
    vault_client = vault or VaultClient(
        cfg.vault_mcp_url, cfg.vault_api_key, timeout=cfg.vault_timeout_seconds
    )
    companion = llm or CompanionLLM(cfg.llm_base_url, cfg.llm_api_key, cfg.llm_model)

    app = FastAPI(
        title="Mini AI",
        version=__version__,
        docs_url=None if cfg.is_production else "/docs",
        redoc_url=None,
    )
    app.state.settings = cfg
    app.state.store = tenant_store
    app.state.vault = vault_client
    app.state.llm = companion
    limiter = WindowLimiter()
    tenant_locks: dict[str, asyncio.Lock] = {}

    @app.middleware("http")
    async def serialize_tenant_requests(request: Request, call_next):
        match = re.match(r"^/v1/mini/t/([^/]+)/", request.url.path)
        if match and tenant_store.get(match[1]):
            lock = tenant_locks.setdefault(match[1], asyncio.Lock())
            async with lock:
                return await call_next(request)
        return await call_next(request)

    static_root = files("miniai").joinpath("static")
    app.mount("/static", StaticFiles(directory=str(static_root)), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/v1/") or request.url.path.startswith("/health/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def require_admin(authorization: Annotated[str | None, Header()] = None) -> None:
        configured = cfg.mini_admin_api_key
        if not configured:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "admin API is disabled")
        if not hmac.compare_digest(_bearer(authorization), configured):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid admin token")

    def require_tenant(
        slug: str,
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        x_mini_pin: Annotated[str | None, Header()] = None,
    ) -> Tenant:
        host = request.client.host if request.client else "unknown"
        # Bound auth CPU work by both personal link and direct connection address.
        if not limiter.allow(f"auth:{slug}", 120, 60) or not limiter.allow(
            f"auth-host:{host}", 600, 60
        ):
            raise HTTPException(
                429, "Too many attempts. Try again in a minute.", headers={"Retry-After": "60"}
            )
        pin = _bearer(authorization) or (x_mini_pin or "")
        if limiter.blocked(f"failed:{slug}", 10, 300):
            raise HTTPException(
                429,
                "Too many incorrect PINs. Try again in five minutes.",
                headers={"Retry-After": "300"},
            )
        tenant = tenant_store.authenticate(slug, pin)
        if tenant is None:
            if not limiter.allow(f"failed:{slug}", 10, 300):
                raise HTTPException(
                    429,
                    "Too many incorrect PINs. Try again in five minutes.",
                    headers={"Retry-After": "300"},
                )
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid Mini link or PIN")
        return tenant

    @app.get("/", include_in_schema=False)
    async def home() -> FileResponse:
        return FileResponse(static_root.joinpath("index.html"))

    @app.get("/u/{slug}", include_in_schema=False)
    async def tenant_home(slug: str) -> FileResponse:
        if tenant_store.get(slug) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such Mini link")
        return FileResponse(static_root.joinpath("index.html"))

    @app.get("/health/live", tags=["health"])
    async def live() -> dict[str, str]:
        return {"status": "ok", "service": "mini-ai", "version": __version__}

    @app.get("/health/ready", tags=["health"])
    async def ready() -> JSONResponse:
        checks: dict[str, Any] = {
            "storage": "ok",
            "llm": "not_configured",
            "vault": "configured" if vault_client.configured else "not_configured",
        }
        problems: list[str] = []
        try:
            tenant_store.check()
        except Exception:
            checks["storage"] = "error"
            problems.append("storage")
        if companion.configured:
            try:
                await companion.check()
                checks["llm"] = "ok"
            except LLMUnavailable:
                checks["llm"] = "unavailable"
                if cfg.llm_required:
                    problems.append("llm")
        elif cfg.llm_required:
            problems.append("llm")
        if cfg.vault_mcp_required:
            if not vault_client.configured:
                problems.append("vault")
            else:
                try:
                    await vault_client.stats()
                    checks["vault"] = "ok"
                except VaultUnavailable:
                    checks["vault"] = "unavailable"
                    problems.append("vault")
        payload = {"status": "ready" if not problems else "not_ready", "checks": checks}
        return JSONResponse(payload, status_code=200 if not problems else 503)

    @app.get("/v1/status", tags=["meta"])
    async def service_status() -> dict[str, Any]:
        return {
            "service": "mini-ai",
            "version": __version__,
            "llm_configured": companion.configured,
            "vault_configured": vault_client.configured,
        }

    @app.post("/v1/mini/admin/onboard", dependencies=[Depends(require_admin)])
    async def onboard(body: OnboardRequest, request: Request) -> dict[str, Any]:
        try:
            tenant, pin = tenant_store.onboard(
                body.owner_name, pin=body.pin, vault_enabled=body.vault_enabled
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        base = cfg.public_url or str(request.base_url).rstrip("/")
        return {
            "slug": tenant.slug,
            "owner_name": tenant.owner_name,
            "pin": pin,
            "url": f"{base}/u/{tenant.slug}",
            "vault_enabled": tenant.vault_enabled,
        }

    @app.get("/v1/mini/admin/tenants", dependencies=[Depends(require_admin)])
    async def tenants() -> dict[str, Any]:
        rows = tenant_store.list()
        return {
            "count": len(rows),
            "tenants": [
                {
                    "slug": row.slug,
                    "owner_name": row.owner_name,
                    "vault_enabled": row.vault_enabled,
                    "active": row.active,
                    "created_at": row.created_at,
                }
                for row in rows
            ],
        }

    @app.delete("/v1/mini/admin/tenants/{slug}", dependencies=[Depends(require_admin)])
    async def deactivate_tenant(slug: str) -> dict[str, Any]:
        if not tenant_store.deactivate(slug):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such Mini link")
        return {"deactivated": True, "slug": slug}

    @app.get("/v1/mini/t/{slug}/profile")
    async def profile(tenant: Annotated[Tenant, Depends(require_tenant)]) -> dict[str, Any]:  # noqa: B008
        return {
            "slug": tenant.slug,
            "owner_name": tenant.owner_name,
            "vault_enabled": tenant.vault_enabled,
            "created_at": tenant.created_at,
            "preferences": tenant_store.preferences(tenant.slug),
        }

    @app.get("/v1/mini/t/{slug}/history")
    async def history(
        tenant: Annotated[Tenant, Depends(require_tenant)],  # noqa: B008
        limit: int = 20,
    ) -> dict[str, Any]:
        try:
            rows = tenant_store.history(tenant.slug, limit=limit)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        return {"count": len(rows), "messages": rows}

    @app.post("/v1/mini/t/{slug}/chat")
    async def chat(
        body: ChatRequest,
        tenant: Annotated[Tenant, Depends(require_tenant)],  # noqa: B008
    ) -> dict[str, Any]:
        text = body.message.strip()
        if not text:
            raise HTTPException(422, "Write a message first.")
        if not limiter.allow(
            f"chat-minute:{tenant.slug}", cfg.mini_chat_per_minute, 60
        ) or not limiter.allow(f"chat-day:{tenant.slug}", cfg.mini_chat_per_day, 86400):
            raise HTTPException(
                429, "Mini's pilot message limit has been reached. Try again later."
            )
        prefs = tenant_store.preferences(tenant.slug)
        if body.remember_private and not prefs["memory_enabled"]:
            raise HTTPException(403, "Enable personal memory in Your space first.")
        if body.remember_private and len(text) > 2000:
            raise HTTPException(422, "A saved memory can contain up to 2000 characters.")
        if body.remember and not tenant.vault_enabled:
            raise HTTPException(403, "Vault memory is disabled for this Mini")
        recalled = tenant_store.recall(tenant.slug, text) if prefs["memory_enabled"] else []
        goals = tenant_store.goals(tenant.slug)
        personal_context = json.dumps(
            {
                "tone": prefs["tone"],
                "focus": prefs["focus"],
                "personal_memories": [r["content"] for r in recalled],
                "active_goals": [
                    dict(g, checkins=g["checkins"][:5]) for g in goals if g["status"] == "active"
                ]
                if body.mode == "mentor"
                else [],
            },
            ensure_ascii=False,
        )

        memory_result: dict[str, Any] | None = None
        context = ""
        vault_context_used = False
        if tenant.vault_enabled and vault_client.configured:
            try:
                pack = await vault_client.context(text)
                context = str(pack.get("context", ""))
                vault_context_used = bool(context)
            except VaultUnavailable:
                pass
        previous = tenant_store.history(tenant.slug, limit=12)
        try:
            reply = await companion.reply(
                owner_name=tenant.owner_name,
                message=text,
                history=previous,
                mode=body.mode,
                vault_context=context,
                personal_context=personal_context,
            )
        except LLMUnavailable as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
        if body.remember:
            if not tenant.vault_enabled:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    "Vault memory is disabled for this Mini",
                )
            durable_content = (
                f"Mini AI tenant {tenant.slug} ({tenant.owner_name}) "
                f"explicitly asked to remember: {text}"
            )
            try:
                memory_result = await vault_client.remember(
                    durable_content,
                    client=f"mini-ai.{tenant.slug}",
                )
            except VaultUnavailable as exc:
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

        private_memory = None
        if body.remember_private:
            try:
                private_memory = tenant_store.save_memory(tenant.slug, text)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        tenant_store.append_message(tenant.slug, "user", text)
        tenant_store.append_message(tenant.slug, "assistant", reply)
        return {
            "reply": reply,
            "mode": body.mode,
            "vault_context_used": vault_context_used,
            "vault_memory": memory_result,
            "private_memory": private_memory,
            "personal_memories_used": len(recalled),
        }

    @app.put("/v1/mini/t/{slug}/preferences")
    async def preferences(
        body: PreferencesRequest, tenant: Annotated[Tenant, Depends(require_tenant)]
    ):
        return tenant_store.save_preferences(tenant.slug, {**body.model_dump(), "onboarded": True})

    @app.get("/v1/mini/t/{slug}/memories")
    async def memories(tenant: Annotated[Tenant, Depends(require_tenant)]):
        return {"memories": tenant_store.memories(tenant.slug)}

    def write_memory(tenant: Tenant, content: str, memory_id: str | None = None):
        if not tenant_store.preferences(tenant.slug)["memory_enabled"]:
            raise HTTPException(403, "Enable personal memory in Your space first.")
        try:
            return tenant_store.save_memory(tenant.slug, content, memory_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, "Memory not found") from exc

    @app.post("/v1/mini/t/{slug}/memories")
    async def add_memory(body: MemoryRequest, tenant: Annotated[Tenant, Depends(require_tenant)]):
        return write_memory(tenant, body.content)

    @app.put("/v1/mini/t/{slug}/memories/{memory_id}")
    async def edit_memory(
        memory_id: str, body: MemoryRequest, tenant: Annotated[Tenant, Depends(require_tenant)]
    ):
        return write_memory(tenant, body.content, memory_id)

    @app.delete("/v1/mini/t/{slug}/memories/{memory_id}")
    async def delete_memory(memory_id: str, tenant: Annotated[Tenant, Depends(require_tenant)]):
        if not tenant_store.delete_memory(tenant.slug, memory_id):
            raise HTTPException(404, "Memory not found")
        return {"deleted": True}

    @app.get("/v1/mini/t/{slug}/goals")
    async def goals(tenant: Annotated[Tenant, Depends(require_tenant)]):
        return {"goals": tenant_store.goals(tenant.slug)}

    @app.post("/v1/mini/t/{slug}/goals")
    async def create_goal(body: GoalRequest, tenant: Annotated[Tenant, Depends(require_tenant)]):
        if not body.title.strip() or not body.next_step.strip():
            raise HTTPException(422, "Write a goal and a next step.")
        try:
            return tenant_store.create_goal(tenant.slug, body.title, body.next_step)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/v1/mini/t/{slug}/goals/{goal_id}/checkins")
    async def checkin(
        goal_id: str, body: CheckinRequest, tenant: Annotated[Tenant, Depends(require_tenant)]
    ):
        if not body.note.strip() or not body.next_step.strip():
            raise HTTPException(422, "Write a progress note and a next step.")
        try:
            return tenant_store.checkin(
                tenant.slug, goal_id, body.note, body.next_step, body.complete
            )
        except KeyError as exc:
            raise HTTPException(404, "Active goal not found") from exc

    @app.get("/v1/mini/t/{slug}/export")
    async def export(tenant: Annotated[Tenant, Depends(require_tenant)]):
        return JSONResponse(
            tenant_store.export(tenant.slug),
            headers={"Content-Disposition": 'attachment; filename="mini-data.json"'},
        )

    @app.put("/v1/mini/t/{slug}/pin")
    async def change_pin(body: PinRequest, tenant: Annotated[Tenant, Depends(require_tenant)]):
        tenant_store.rotate_pin(tenant.slug, body.pin)
        return {"changed": True}

    @app.post("/v1/mini/admin/tenants/{slug}/reset-pin", dependencies=[Depends(require_admin)])
    async def reset_pin(slug: str):
        pin = generate_pin()
        if not tenant_store.rotate_pin(slug, pin):
            raise HTTPException(404, "Active Mini not found")
        return {"pin": pin, "slug": slug}

    @app.post("/v1/mini/t/{slug}/erase")
    async def erase(body: EraseRequest, tenant: Annotated[Tenant, Depends(require_tenant)]):
        tenant_store.erase(tenant.slug)
        return {
            "deleted": True,
            "scope": "Mini data erased. Shared Vault records and backups "
            "are managed separately; contact the operator for their removal.",
        }

    @app.get("/v1/vault/status", dependencies=[Depends(require_admin)])
    async def vault_status() -> dict[str, Any]:
        try:
            return await vault_client.stats()
        except VaultUnavailable as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    @app.post("/v1/vault/search", dependencies=[Depends(require_admin)])
    async def vault_search(body: VaultSearchRequest) -> dict[str, Any]:
        try:
            return await vault_client.search(body.query, limit=body.limit)
        except VaultUnavailable as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    @app.post("/v1/vault/remember", dependencies=[Depends(require_admin)])
    async def vault_remember(body: VaultRememberRequest) -> dict[str, Any]:
        try:
            return await vault_client.remember(
                body.content,
                kind=body.kind,
                importance=body.importance,
                client="mini-ai-admin",
            )
        except VaultUnavailable as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    return app


app = create_app()
