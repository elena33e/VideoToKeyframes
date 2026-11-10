"""Construirea strategiei VLM pentru furnizorul ales."""

from .base import VLMStrategy
from .gemini import GeminiStrategy
from .openai import OpenAIStrategy
from .openrouter import OpenRouterStrategy


def create_strategy(
    provider: str,
    *,
    api_key: str,
    model: str,
    timeout_seconds: float = 180.0,
) -> VLMStrategy:
    if provider == "gemini":
        return GeminiStrategy(
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
        )

    if provider == "openrouter":
        return OpenRouterStrategy(
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
        )

    if provider == "openai":
        return OpenAIStrategy(
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            reasoning_effort="low",
        )

    raise ValueError(f"Furnizor necunoscut: {provider}")