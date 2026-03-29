"""
Central configuration loaded from environment variables and optional `.env`.

Who uses this module:
  - `app/main.py` — passes model name / paths into the HTML template and `/health`.
  - `app/chat.py` — reads API keys, model, and where to find behavior + trace files.

Design choice — `PROJECT_ROOT`:
  Paths in `.env` are often relative (e.g. `config/agent_behavior.md`). We anchor them
  to the repository root (parent of the `app/` folder) so imports still work when
  the process cwd differs slightly.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# `__file__` is this file; `.parent` is `app/`; `.parent.parent` is the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """
    Maps env vars to typed settings. pydantic-settings loads `.env` automatically
    (see `model_config` below) so local development does not require exporting
    variables in the shell.

    Variable names in `.env` use SCREAMING_SNAKE_CASE (e.g. OPENAI_API_KEY);
    Python fields here use snake_case — `Field(validation_alias=...)` connects them.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Ignore unknown env keys so the app tolerates extra `.env` noise.
    )

    openai_api_key: str = Field(validation_alias="OPENAI_API_KEY")
    # When unset, the OpenAI SDK talks to the official API host. When set (e.g. local
    # vLLM/Ollama bridge), the same code path speaks OpenAI-compatible HTTP. See `app/chat.py`.
    openai_base_url: str | None = Field(default=None, validation_alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4o-mini", validation_alias="OPENAI_MODEL")

    # Defaults point at the sample evaluator file and trace location documented in README.md.
    behavior_file: Path = Field(
        default=PROJECT_ROOT / "config" / "agent_behavior.md",
        validation_alias="BEHAVIOR_FILE",
    )
    traces_file: Path = Field(
        default=PROJECT_ROOT / "data" / "traces.json",
        validation_alias="TRACES_FILE",
    )

    def resolved_behavior_file(self) -> Path:
        """Absolute path to the markdown behavior layer (read in `app/behavior.py`)."""
        p = self.behavior_file
        return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()

    def resolved_traces_file(self) -> Path:
        """Absolute path to the JSON trace array (read/written in `app/tracing.py`)."""
        p = self.traces_file
        return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()


@lru_cache
def get_settings() -> Settings:
    """
    Single cached Settings instance for the process.

    Teaching note:
      If you change `.env` while the server runs, values here will NOT refresh until
      you restart Uvicorn — by design for simplicity. For hot-reload of config you
      would clear the cache or stop using `@lru_cache`.
    """
    return Settings()
