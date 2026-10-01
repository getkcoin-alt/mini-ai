from __future__ import annotations

import hmac
from importlib.resources import files
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from miniai import __version__
from miniai.config import Settings, get_settings
from miniai.llm import CompanionLLM, LLMUnavailable
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
        authorization: Annotated[str | None, Header()] = None,
        x_mini_pin: Annotated[str | None, Header()] = None,
    ) -> Tenant:
        pin = _bearer(authorization) or (x_mini_pin or "")
        tenant = tenant_store.authenticate(slug, pin)
        if tenant is None:
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
            "llm": "configured" if companion.configured else "not_configured",
            "vault": "configured" if vault_client.configured else "not_configured",
        }
        problems: list[str] = []
        try:
            tenant_store.check()
        except Exception:
            checks["storage"] = "error"
            problems.append("storage")
        if cfg.llm_required and not companion.configured:
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
    async def profile(tenant: Tenant = Depends(require_tenant)) -> dict[str, Any]:  # noqa: B008
        return {
            "slug": tenant.slug,
            "owner_name": tenant.owner_name,
            "vault_enabled": tenant.vault_enabled,
            "created_at": tenant.created_at,
        }

    @app.get("/v1/mini/t/{slug}/history")
    async def history(
        tenant: Tenant = Depends(require_tenant),  # noqa: B008
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
        tenant: Tenant = Depends(require_tenant),  # noqa: B008
    ) -> dict[str, Any]:
        text = body.message.strip()
        memory_result: dict[str, Any] | None = None
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
            )
        except LLMUnavailable as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
        tenant_store.append_message(tenant.slug, "user", text)
        tenant_store.append_message(tenant.slug, "assistant", reply)
        return {
            "reply": reply,
            "mode": body.mode,
            "vault_context_used": vault_context_used,
            "vault_memory": memory_result,
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
