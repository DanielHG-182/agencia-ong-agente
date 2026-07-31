"""Factories for external service clients."""

from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings
from openai import OpenAI

from scripts.config import settings


class ClientConfigurationError(RuntimeError):
    """Raised when an external service client cannot be configured."""


def create_openai_client() -> OpenAI:
    """
    Create an OpenAI client using the configured API key.

    Raises:
        ClientConfigurationError: If OPENAI_API_KEY is not configured.
    """

    if not settings.openai_api_key:
        raise ClientConfigurationError(
            "OPENAI_API_KEY is not configured. "
            "Add it to the environment or to the local .env file."
        )

    return OpenAI(api_key=settings.openai_api_key)

def create_chroma_client(
    persist_directory: str | Path,
) -> chromadb.PersistentClient:
    """
    Create a persistent ChromaDB client.

    Args:
        persist_directory: Directory where ChromaDB stores its data.
    """

    return chromadb.PersistentClient(
        path=str(persist_directory),
        settings=ChromaSettings(anonymized_telemetry=False),
    )