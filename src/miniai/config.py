from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    mini_admin_api_key: str = ""
    mini_data_dir: Path = Path("data")
    mini_public_url: str = ""
    railway_public_domain: str = ""

    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_required: bool = False

    vault_mcp_url: str = ""
    vault_api_key: str = ""
    vault_mcp_required: bool = False
    vault_timeout_seconds: float = Field(default=12.0, ge=1.0, le=60.0)

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)

    @property
    def vault_configured(self) -> bool:
        return bool(self.vault_mcp_url and self.vault_api_key)

    @property
    def public_url(self) -> str:
        if self.mini_public_url:
            return self.mini_public_url.rstrip("/")
        if self.railway_public_domain:
            return f"https://{self.railway_public_domain}"
        return ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
