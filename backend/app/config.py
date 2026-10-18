from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Telegram ---
    bot_token: str = ""
    # Comma-separated chat ids where the bot accepts receipts. Empty = any chat (dev only).
    allowed_chat_ids: str = ""
    # Chat for monthly reports, budget alerts and recurring notices. Defaults to first allowed chat.
    report_chat_id: int | None = None

    # --- LLM (any OpenAI-compatible API: OpenRouter, Gemini, Ollama, ...) ---
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: str = ""
    # Comma-separated list, tried in order. First one that answers wins.
    llm_models: str = (
        "deepseek/deepseek-v4.1-flash,"
        "nvidia/nemotron-3.5-super-vl:free,"
        "google/gemma-4-31b-it:free,"
        "google/gemma-4-26b-a4b-it:free"
    )
    # Model for short text tasks (manual entries, bank messages, comments). Empty = use llm_models.
    llm_text_models: str = ""
    # Cascade: a receipt whose sums do not add up is re-read by these (stronger) models.
    # Empty = no second reading.
    llm_strong_models: str = ""
    # Models that understand audio, for voice messages. Empty = voice messages are ignored.
    llm_audio_models: str = ""
    # Models for questions in the web UI; they must support tool calling. Empty = text models.
    llm_ask_models: str = ""
    llm_timeout: float = 120.0
    llm_max_image_side: int = 2000

    # --- Storage ---
    database_url: str = f"sqlite+aiosqlite:///{PROJECT_ROOT / 'data' / 'app.db'}"
    data_dir: Path = PROJECT_ROOT / "data"

    # --- Web ---
    web_host: str = "0.0.0.0"
    web_port: int = 8000
    # Public URL of the web UI, used for "Открыть" buttons in the bot.
    web_base_url: str = ""
    secret_key: str = "change-me"
    # Fallback login when Telegram Login Widget is unavailable (no domain). Empty = disabled.
    web_password: str = ""
    # Skip auth entirely. Local development only!
    auth_disabled: bool = False

    # --- Receipts by e-mail (IMAP). Empty host = disabled. ---
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"
    imap_poll_minutes: int = 10

    # --- LLM balance ---
    # warn in the group when the OpenRouter balance or the key's limit drops below this, USD; 0 = off
    llm_balance_alert: float = 1.0
    # DeepSeek's own API key, only to show its balance (requests go through LLM_BASE_URL)
    deepseek_api_key: str = ""

    # --- Warranty ---
    # remind in the group this many days before a warranty ends
    warranty_remind_days: int = 30

    # --- Money / time ---
    timezone: str = "Europe/Sofia"
    review_tolerance: float = 0.05

    @field_validator("web_base_url")
    @classmethod
    def _url_scheme(cls, v: str) -> str:
        """'example.com' -> 'https://example.com' (Telegram rejects URL buttons without a scheme)."""
        v = v.strip().rstrip("/")
        if v and "://" not in v:
            v = "https://" + v
        return v

    @property
    def allowed_chats(self) -> set[int]:
        return {int(x) for x in self.allowed_chat_ids.replace(" ", "").split(",") if x}

    @property
    def notify_chat_id(self) -> int | None:
        if self.report_chat_id:
            return self.report_chat_id
        chats = sorted(self.allowed_chats)
        return chats[0] if chats else None

    @property
    def models(self) -> list[str]:
        return [m.strip() for m in self.llm_models.split(",") if m.strip()]

    @staticmethod
    def _split(value: str) -> list[str]:
        return [m.strip() for m in value.split(",") if m.strip()]

    @property
    def text_models(self) -> list[str]:
        return self._split(self.llm_text_models) or self.models

    @property
    def strong_models(self) -> list[str]:
        return self._split(self.llm_strong_models)

    @property
    def audio_models(self) -> list[str]:
        return self._split(self.llm_audio_models)

    @property
    def ask_models(self) -> list[str]:
        return self._split(self.llm_ask_models) or self.text_models

    @property
    def receipts_dir(self) -> Path:
        return self.data_dir / "receipts"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"


@lru_cache
def get_settings() -> Settings:
    return Settings()
