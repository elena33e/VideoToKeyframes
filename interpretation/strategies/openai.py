"""Strategia pentru OpenAI API."""

from ..contracts import VLMRequest, VLMResponse
from .base import VLMStrategy
from ._chat_completions import execute_chat_request, validate_connection


class OpenAIStrategy(VLMStrategy):
    ENDPOINT = "https://api.openai.com/v1/chat/completions"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 180.0,
        reasoning_effort: str | None = None,
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

    @property
    def provider(self) -> str:
        return "openai"

    @property
    def model(self) -> str:
        return self._model

    def generate(self, request: VLMRequest) -> VLMResponse:
        parameters = {"store": False}

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
        )