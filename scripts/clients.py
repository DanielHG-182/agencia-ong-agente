"""Factories for external service clients."""

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