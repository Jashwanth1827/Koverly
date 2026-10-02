"""AI provider factory.

Selection is configuration-driven so the product is not coupled to a vendor.
"""

from __future__ import annotations

import logging

from app.ai.base import AIProvider
from app.ai.null_provider import NullProvider
from app.core.config import settings

logger = logging.getLogger("koverly.ai")

_provider: AIProvider | None = None


def get_ai_provider() -> AIProvider:
    global _provider
    if _provider is not None:
        return _provider

    choice = (settings.AI_PROVIDER or "null").lower()
    if choice in {"openai", "anthropic", "azure", "compatible"}:
        try:
            from app.ai.openai_provider import OpenAICompatibleProvider

            _provider = OpenAICompatibleProvider()
            logger.info("ai_provider_selected provider=%s", _provider.name)
            return _provider
        except Exception:  # noqa: BLE001
            logger.exception(
                "ai_provider_init_failed falling back to null provider"
            )
    _provider = NullProvider()
    return _provider


def set_ai_provider(provider: AIProvider | None) -> None:
    """Test/DI hook."""
    global _provider
    _provider = provider
