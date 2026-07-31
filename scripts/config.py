"""
Central application configuration.

Environment variables are loaded once and converted into typed values.
Secrets are not validated at import time so local pipeline stages can run
without requiring external API credentials.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


class ConfigurationError(ValueError):
    """Raised when an environment variable contains an invalid value."""


def _get_int(name: str, default: int, *, minimum: int | None = None) -> int:
    raw_value = os.getenv(name)

    if raw_value is None:
        value = default
    else:
        try:
            value = int(raw_value)
        except ValueError as exc:
            raise ConfigurationError(
                f"{name} must be an integer, received: {raw_value!r}"
            ) from exc

    if minimum is not None and value < minimum:
        raise ConfigurationError(
            f"{name} must be greater than or equal to {minimum}, received: {value}"
        )

    return value


def _get_float(
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    raw_value = os.getenv(name)

    if raw_value is None:
        value = default
    else:
        try:
            value = float(raw_value)
        except ValueError as exc:
            raise ConfigurationError(
                f"{name} must be a number, received: {raw_value!r}"
            ) from exc

    if minimum is not None and value < minimum:
        raise ConfigurationError(
            f"{name} must be greater than or equal to {minimum}, received: {value}"
        )

    if maximum is not None and value > maximum:
        raise ConfigurationError(
            f"{name} must be less than or equal to {maximum}, received: {value}"
        )

    return value


@dataclass(frozen=True)
class Settings:
    """Typed application settings loaded from environment variables."""

    openai_api_key: str | None
    embedding_model: str
    llm_model: str
    llm_max_tokens: int
    llm_temperature: float
    retriever_top_k: int
    chroma_collection_name: str


def load_settings() -> Settings:
    """Build and validate the application settings."""

    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        embedding_model=os.getenv(
            "EMBEDDING_MODEL",
            "text-embedding-3-small",
        ),
        llm_model=os.getenv(
            "LLM_MODEL",
            "gpt-4o-mini",
        ),
        llm_max_tokens=_get_int(
            "LLM_MAX_TOKENS",
            2048,
            minimum=1,
        ),
        llm_temperature=_get_float(
            "LLM_TEMPERATURE",
            0.0,
            minimum=0.0,
            maximum=2.0,
        ),
        retriever_top_k=_get_int(
            "RETRIEVER_TOP_K",
            3,
            minimum=1,
        ),
        chroma_collection_name=os.getenv(
            "CHROMA_COLLECTION_NAME",
            "ong_documents",
        ),
    )


settings = load_settings()