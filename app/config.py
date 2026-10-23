"""Runtime configuration, read once from the environment.

Everything external is optional. The app is designed to boot and serve with no
credentials at all so that it can be run, tested and demoed offline; each
integration degrades to a documented fallback rather than raising at import.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RUNBOOK_DIR = DATA_DIR / "runbooks"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # --- LLM provider -----------------------------------------------------
    # "groq" and "anthropic" are both OpenAI-style chat/tool-call APIs as far
    # as this app is concerned; the adapter in app/llm.py normalises them.
    # "fake" is a deterministic in-process provider used by the test suite.
    llm_provider: str = "fake"
    llm_model: str = ""
    llm_api_key: str = ""

    # --- Slack ------------------------------------------------------------
    slack_signing_secret: str = ""
    slack_bot_token: str = ""

    # --- Langfuse ---------------------------------------------------------
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # --- Agent behaviour --------------------------------------------------
    # Hard ceiling on tool-call round trips for a single question. Without it
    # a model that keeps asking for the same tool will bill forever and never
    # answer; with it the loop fails loudly and returns a partial answer.
    max_tool_iterations: int = 4
    request_timeout_s: int = 30

    db_path: str = str(DATA_DIR / "relay.db")

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider != "fake" and bool(self.llm_api_key)

    @property
    def slack_enabled(self) -> bool:
        return bool(self.slack_signing_secret and self.slack_bot_token)

    @property
    def tracing_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


_DEFAULT_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "anthropic": "claude-sonnet-4-20250514",
    "openai": "gpt-4o-mini",
}


def load_settings() -> Settings:
    provider = _env("LLM_PROVIDER", "fake").lower()
    key_var = {
        "groq": "GROQ_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
    }.get(provider, "")

    return Settings(
        llm_provider=provider,
        llm_model=_env("LLM_MODEL", _DEFAULT_MODELS.get(provider, "")),
        llm_api_key=_env(key_var) if key_var else "",
        slack_signing_secret=_env("SLACK_SIGNING_SECRET"),
        slack_bot_token=_env("SLACK_BOT_TOKEN"),
        langfuse_public_key=_env("LANGFUSE_PUBLIC_KEY"),
        langfuse_secret_key=_env("LANGFUSE_SECRET_KEY"),
        langfuse_host=_env("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        max_tool_iterations=_env_int("MAX_TOOL_ITERATIONS", 4),
        request_timeout_s=_env_int("REQUEST_TIMEOUT_S", 30),
        db_path=_env("RELAY_DB_PATH", str(DATA_DIR / "relay.db")),
    )


settings = load_settings()
