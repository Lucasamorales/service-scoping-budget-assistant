"""Runtime settings, read once from the environment.

Every value has a default that works offline. Nothing here requires GCP, and
the properties at the bottom say plainly which subsystems are configured, so
the application can degrade one capability at a time instead of failing to
start because one credential is missing.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings", "get_settings"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: str = "local"
    log_level: str = "INFO"

    gcp_project_id: str = ""
    gcp_region: str = "europe-west2"

    vertex_chat_model: str = "gemini-2.5-flash"
    vertex_embed_model: str = "text-embedding-005"
    vertex_embed_dimensions: int = 768

    knowledge_bucket: str = ""
    knowledge_index_object: str = "index/latest.json"
    local_index_path: Path = Path("artifacts/index.json")
    documents_dir: Path = Path("documents")
    system_prompt_path: Path = Path("prompts/system.md")

    # Declared so the file stays in step with .env.example. None of these are
    # wired yet; the properties below are what decide whether a subsystem runs.
    firestore_database: str = "(default)"
    budget_cache_ttl_seconds: int = 900
    budget_spreadsheet_id: str = ""
    budget_sheet_range: str = ""
    mail_provider: str = "resend"
    mail_api_key: str = ""
    mail_from_address: str = ""

    allowed_origins: str = ""
    session_token_secret: str = ""
    session_token_ttl_seconds: int = 3600
    rate_limit_requests: int = 20
    rate_limit_window_seconds: int = 60

    max_output_tokens: int = 1024
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    """Low, because this assistant reports facts it has been handed. Wording
    should vary a little; verdicts should not vary at all."""

    @property
    def is_local(self) -> bool:
        return self.environment == "local"

    @property
    def vertex_configured(self) -> bool:
        """Whether a Gemini call can be attempted.

        When false the assistant still answers, from the deterministic
        composer, because the verdict never depended on the model.
        """
        return bool(self.gcp_project_id)

    @property
    def budget_configured(self) -> bool:
        return bool(self.budget_spreadsheet_id)

    @property
    def mail_configured(self) -> bool:
        return bool(self.mail_api_key and self.mail_from_address)

    @property
    def origins(self) -> tuple[str, ...]:
        return tuple(part.strip() for part in self.allowed_origins.split(",") if part.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
