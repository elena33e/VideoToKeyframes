"""Strategia pentru OpenAI API."""

from ..contracts import VLMRequest, VLMResponse
from .base import VLMStrategy
from ._chat_completions import execute_chat_request, validate_connection
from typing import Any
from pathlib import Path


class OpenAIStrategy(VLMStrategy):
    ENDPOINT = "https://api.openai.com/v1/chat/completions"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 180.0,
        reasoning_effort: str | None = None,
        journal_directory: Path | None = None,
    ):
        validate_connection(api_key, model, timeout_seconds)

        if reasoning_effort not in {
            None,
            "none",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        }:
            raise ValueError("Valoare reasoning_effort neacceptată.")

        self._api_key = api_key.strip()
        self._model = model.strip()
        self._timeout_seconds = timeout_seconds
        self._reasoning_effort = reasoning_effort
        self._journal_directory = journal_directory

    @property
    def provider(self) -> str:
        return "openai"

    @property
    def model(self) -> str:
        return self._model

    def generate(self, request: VLMRequest) -> VLMResponse:
        parameters: dict[str, Any] = {"store": False}

        cache_stable_prefix = self.model == "gpt-6.1-sol"

        if cache_stable_prefix:
            parameters["prompt_cache_options"] = {
                "mode": "explicit",
                "ttl": "30m",
            }

        if self._reasoning_effort is not None:
            parameters["reasoning_effort"] = self._reasoning_effort

        return execute_chat_request(
            endpoint=self.ENDPOINT,
            api_key=self._api_key,
            provider=self.provider,
            model=self.model,
            request=request,
            parameters=parameters,
            timeout_seconds=self._timeout_seconds,
            token_limit_parameter="max_completion_tokens",
            cache_stable_prefix=cache_stable_prefix,
            journal_directory=self._journal_directory,
        )