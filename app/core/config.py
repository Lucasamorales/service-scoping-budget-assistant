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
        populate_by_name=True,
    )

    environment: str = "local"
    log_level: str = "INFO"

    # Gemini Developer API (API key) — chat wording and dense embeddings.
    gemini_api_key: str = ""
    gemini_chat_model: str = "gemini-2.5-flash"
    gemini_embed_model: str = "gemini-embedding-001"
    gemini_embed_dimensions: int = 768
    """gemini-embedding-001 natives to 3072; we request 768 for a smaller index."""

    # GCP for Firestore / Sheets — not used for Gemini.
    gcp_project_id: str = ""
    google_application_credentials: str = ""
    """Optional path to a service-account JSON key (Sheets / Firestore local)."""

    use_llm_planner: bool = True
    """Let the model choose which lookups a turn needs (slots included).

    Off falls back to the pattern router, which is what runs anyway when no
    ``GEMINI_API_KEY`` is configured. The planner cannot state a verdict or a
    price; it only selects tools, and an invalid plan is discarded.
    """

    use_llm_composer: bool = True
    """Let the model word the answer from the facts the tools returned.

    Off uses the deterministic composer everywhere, which is also the automatic
    fallback when the model fails or writes a figure the facts do not contain.
    """

    use_dense_retrieval: bool = True
    """Let retrieval blend embedding similarity with keyword scoring.

    On is the intended configuration: dense search is what lets a request reach
    a service it does not share words with. Off is not a degraded mode so much
    as a narrower one — verdicts still resolve, from names and aliases — and it
    is what the offline eval and CI run, so that a failing build always means a
    change in behaviour rather than a model having a different day.

    Needs both halves present to do anything: an index built with ``--embed``
    and a configured key. Missing either, retrieval scores on words alone and
    says so in the startup log.
    """

    use_semantic_inventory: bool = False
    """Opt-in embedding classifier for “list the services” paraphrases.

    Off by default: false positives steal budget/scoping turns and, combined with
    a canned CAPABILITIES reply, made every answer look the same. Prefer the
    catalog-list regex until this is validated in production.
    """

    local_index_path: Path = Path("artifacts/index.json")
    documents_dir: Path = Path("documents")
    system_prompt_path: Path = Path("prompts/system.md")

    firestore_database: str = "(default)"

    budget_cache_ttl_seconds: int = 300
    """How long budget/spend figures may be served before the sheet is re-read.
    The tracker is edited during the day, so a store loaded once at startup
    answered "what is left?" from whenever the container happened to boot.

    Five minutes rather than fifteen because this is money and the edit that
    matters is immediate: a quote gets approved, someone writes it into the
    ledger, and until the next read the assistant reports a balance that has
    already been spent. The read is four small tabs, well inside the Sheets
    quota even at one instance per five minutes.

    It also bounds disagreement between instances. The cache is per-container
    and up to three serve at once, so this is the widest gap between the
    figures two people can be told at the same moment."""

    quote_cache_ttl_seconds: int = 300
    """How long tier prices and the service-to-tier map may be served before
    the sheet is re-read.

    Separate from the budget TTL because the two move on different rhythms:
    spend changes several times a day, a tier changes when the business decides
    to reprice. What they share is that both used to be read once, and the
    price half had no expiry at all — a re-tiered service kept quoting the old
    number until the container recycled."""

    budget_spreadsheet_id: str = ""
    budget_xlsx_path: Path = Path("fixtures/budget/acme_scope_db.xlsx")
    """Offline/dev fallback only. When ``BUDGET_SPREADSHEET_ID`` is set, Sheets wins."""

    quote_rate_card_path: Path = Path("fixtures/quote/rate_card.json")
    """Service→tier map. Live tier prices come from the sheet ``Pricing_tiers`` tab."""

    contacts_path: Path = Path("fixtures/contacts/country_ams.json")
    """Country → Account Manager email matrix (v1 also used for PO CTAs)."""

    audit_log_path: Path = Path("artifacts/audit")
    """Local directory for conversation audit JSON when Firestore is off."""

    audit_backend: str = "auto"
    """``auto`` (Firestore when GCP project set, else JSONL), ``firestore``, or ``jsonl``."""

    mail_provider: str = "resend"
    mail_api_key: str = ""
    mail_from_address: str = ""

    public_base_url: str = ""
    """Where this service answers from, as a mail client would reach it.

    The request emails carry a logo and a stylesheet, and an email has no
    origin to resolve a relative path against — every asset URL has to be
    absolute and publicly fetchable. Empty means the HTML part is still built
    and still correct, only without the logo image and the brand faces; the
    templates are designed to survive exactly that, because Gmail strips
    stylesheet links and proxies or blocks images regardless.
    """

    allowed_origins: str = ""
    session_token_secret: str = ""
    session_token_ttl_seconds: int = 3600
    internal_access_password: str = ""
    """Shared password for the internal MVP page to mint a session. Empty
    disables ``POST /api/session``. Not a substitute for IAP in production."""

    pending_action_ttl_seconds: int = 900
    """How long a sealed mail CTA stays confirmable. Short on purpose: a "Yes"
    typed into a tab left open since this morning should not send an email the
    user has forgotten proposing."""

    rate_limit_requests: int = 20
    rate_limit_window_seconds: int = 60

    max_output_tokens: int = 2048
    temperature: float = Field(default=0.55, ge=0.0, le=2.0)
    """Room for natural, conversational wording. Verdicts still come from the
    catalog, not from sampling — temperature only shapes how the facts are said."""

    @property
    def is_local(self) -> bool:
        return self.environment == "local"

    @property
    def gemini_api_key_configured(self) -> bool:
        return bool(self.gemini_api_key.strip())

    @property
    def gemini_configured(self) -> bool:
        """Whether Gemini chat/embed can be attempted (Developer API key)."""
        return self.gemini_api_key_configured

    @property
    def budget_configured(self) -> bool:
        return bool(self.budget_spreadsheet_id) or self.budget_xlsx_path.is_file()

    @property
    def mail_configured(self) -> bool:
        return bool(self.mail_api_key and self.mail_from_address)

    @property
    def origins(self) -> tuple[str, ...]:
        """The allowlist, normalised the way a browser sends an Origin.

        Lowercased and stripped of any trailing slash, because scheme and host
        are case-insensitive per RFC 3986 while both the origin check and
        Starlette's CORS middleware compare strings exactly. Normalising here
        rather than at each comparison means the two cannot disagree: doing it
        in only one of them turned a mixed-case entry into a 400 from the other,
        with nothing to suggest the capitalisation was the cause."""
        return tuple(
            part.strip().rstrip("/").casefold()
            for part in self.allowed_origins.split(",")
            if part.strip()
        )

    @property
    def session_auth_enabled(self) -> bool:
        """Chat requires a bearer token when a signing secret is configured."""
        return bool(self.session_token_secret)

    @property
    def session_issuance_enabled(self) -> bool:
        return bool(self.session_token_secret and self.internal_access_password)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
