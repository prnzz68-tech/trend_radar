
# src/settings.py

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    DATABASE_URL: str

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL_SCORE: str = "gpt-4o-mini"
    OPENAI_MODEL_DIGEST: str = "gpt-4o"
    OPENAI_PRICE_PER_1K_INPUT: float | None = None
    OPENAI_PRICE_PER_1K_OUTPUT: float | None = None

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_USER_ID: int = 0

    # Runtime
    TZ: str = "UTC"
    LOG_LEVEL: str = "INFO"

    # Schedule
    COLLECT_CRON: str = "0 7 * * *"
    DIGEST_CRON: str = "0 10 * * 1"

    # HTTP throttling
    HTTP_REQUESTS_PER_DOMAIN_PER_SEC: float = 1.0

    # Reddit (Этап 5)
    REDDIT_CLIENT_ID: str = ""
    REDDIT_CLIENT_SECRET: str = ""
    REDDIT_USER_AGENT: str = "trend-radar/0.1 by trend-radar"

    # Product Hunt (Этап 6)
    PRODUCTHUNT_TOKEN: str = ""

    # VK (Этап 7)
    VK_ACCESS_TOKEN: str = ""

    # Telegram channels (Этап 8)
    TG_API_ID: int = 0
    TG_API_HASH: str = ""

    # YouTube (Этап 9)
    YOUTUBE_API_KEY: str = ""


settings = Settings()  # type: ignore[call-arg]
