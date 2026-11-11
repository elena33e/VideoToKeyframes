"""Strategia pentru OpenRouter API."""

import math

from ..contracts import VLMRequest, VLMResponse
from .base import VLMStrategy
from ._chat_completions import (
    execute_chat_request,
    validate_connection,
)


class OpenRouterStrategy(VLMStrategy):
    ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 180.0,
        temperature: float | None = None,
        reasoning_enabled: bool | None = None,
    ):
        validate_connection(api_key, model, timeout_seconds)

        if temperature is not None and (
            not math.isfinite(temperature)
            or not 0 <= temperature <= 2
        ):
            raise ValueError(
                "temperature trebuie să fie între 0 și 2."
            )

        if (
            reasoning_enabled is not None
            and type(reasoning_enabled) is not bool
        ):
            raise ValueError(
                "reasoning_enabled trebuie să fie bool sau None."
            )

        self._api_key = api_key.strip()
        self._model = model.strip()
        self._timeout_seconds = timeout_seconds
        self._temperature = temperature
        self._reasoning_enabled = reasoning_enabled

    @property
    def provider(self) -> str:
        return "openrouter"

    @property
    def model(self) -> str:
        return self._model

    def generate(self, request: VLMRequest) -> VLMResponse:
        parameters = {
            "provider": {
                "require_parameters": True,
            },
        }

        if self._temperature is not None:
            parameters["temperature"] = self._temperature

        if self._reasoning_enabled is not None:
            parameters["reasoning"] = {
                "enabled": self._reasoning_enabled,
            }

        return execute_chat_request(
            endpoint=self.ENDPOINT,
            api_key=self._api_key,
            provider=self.provider,
            model=self.model,
            request=request,
            parameters=parameters,
            timeout_seconds=self._timeout_seconds,
        )