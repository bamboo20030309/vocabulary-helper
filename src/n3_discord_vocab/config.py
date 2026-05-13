from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    discord_token: str
    discord_user_id: int | None
    discord_channel_id: int | None
    discord_guild_id: int | None
    quiz_time: str
    timezone: str
    database_path: Path
    ollama_url: str
    ollama_model: str
    ollama_timeout: int
    llm_enabled: bool
    message_content_intent: bool
    dictionary_enabled: bool


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(encoding="utf-8-sig")


def _optional_int(value: str | None) -> int | None:
    if not value:
        return None
    return int(value)


def load_settings() -> Settings:
    _load_dotenv()
    return Settings(
        discord_token=os.getenv("DISCORD_TOKEN", ""),
        discord_user_id=_optional_int(os.getenv("DISCORD_USER_ID")),
        discord_channel_id=_optional_int(os.getenv("DISCORD_CHANNEL_ID")),
        discord_guild_id=_optional_int(os.getenv("DISCORD_GUILD_ID")),
        quiz_time=os.getenv("QUIZ_TIME", "08:00"),
        timezone=os.getenv("TIMEZONE", "Asia/Taipei"),
        database_path=Path(os.getenv("DATABASE_PATH", "data/vocab.sqlite3")),
        ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b"),
        ollama_timeout=int(os.getenv("OLLAMA_TIMEOUT", "60")),
        llm_enabled=os.getenv("LLM_ENABLED", "true").lower() in {"1", "true", "yes", "on"},
        message_content_intent=os.getenv("MESSAGE_CONTENT_INTENT", "false").lower()
        in {"1", "true", "yes", "on"},
        dictionary_enabled=os.getenv("DICTIONARY_ENABLED", "true").lower()
        in {"1", "true", "yes", "on"},
    )
