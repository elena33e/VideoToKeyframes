"""Strategia text pentru OpenAI Chat Completions."""

from math import isfinite

import httpx

from .config import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
)
from .generation import GenerationError, GenerationResponse, GenerationStrategy


MESSAGES_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIClient(GenerationStrategy):
    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_OPENAI_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ):
        self._api_key = api_key.strip()
        self.model = model.strip()
        if not self._api_key:
            raise ValueError("OPENAI_API_KEY lipsește.")
        if not self.model:
            raise ValueError("Identificatorul modelului OpenAI lipsește.")
        if not isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds trebuie să fie pozitiv și finit.")
        if type(max_output_tokens) is not int or max_output_tokens <= 0:
            raise ValueError("max_output_tokens trebuie să fie un întreg pozitiv.")

        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens

    def generate(
        self,
        *,
        system_prompt: str,
        ontology_turtle: str,
        user_prompt: str,
    ) -> GenerationResponse:
        payload = {
            "model": self.model,
            "max_completion_tokens": self._max_output_tokens,
            "response_format": {"type": "json_object"},
            "store": False,
            "messages": [
                {"role": "developer", "content": system_prompt},
                {
                    "role": "user",
                    "content": "Ontologia furnizată în Turtle:\n" + ontology_turtle,
                },
                {
                    "role": "user",
                    "content": "Observațiile în JSON:\n" + user_prompt,
                },
            ],
        }

        try:
            response = httpx.post(
                MESSAGES_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
                timeout=self._timeout_seconds,
            )
        except httpx.RequestError as exc:
            raise GenerationError(
                f"Conexiunea cu OpenAI a eșuat ({type(exc).__name__})."
            ) from None

        try:
            body = response.json()
        except ValueError:
            body = None

        if not response.is_success:
            error = body.get("error") if isinstance(body, dict) else None
            message = error.get("message") if isinstance(error, dict) else None
            detail = message if isinstance(message, str) else response.reason_phrase
            detail = detail.replace(self._api_key, "[CHEIE ASCUNSĂ]")[:500]
            raise GenerationError(
                f"OpenAI a răspuns cu HTTP {response.status_code}: {detail}"
            )

        choices = body.get("choices") if isinstance(body, dict) else None
        if not isinstance(choices, list) or len(choices) != 1:
            raise GenerationError(
                "Răspunsul OpenAI trebuie să conțină un singur rezultat."
            )

        choice = choices[0]
        message = choice.get("message") if isinstance(choice, dict) else None
        if not isinstance(message, dict):
            raise GenerationError("Lipsește mesajul generat de OpenAI.")
        if message.get("refusal"):
            raise GenerationError("OpenAI a refuzat cererea.")

        finish_reason = choice.get("finish_reason")
        if finish_reason != "stop":
            raise GenerationError(
                f"Răspuns OpenAI incomplet: finish_reason={finish_reason!r}."
            )

        text = message.get("content")
        message_id = body.get("id")
        model = body.get("model")
        usage = body.get("usage")
        if (
            not isinstance(text, str) or not text.strip()
            or not isinstance(message_id, str) or not message_id
            or not isinstance(model, str) or not model
            or not isinstance(usage, dict)
        ):
            raise GenerationError(
                "Răspunsul OpenAI nu conține textul sau metadatele așteptate."
            )

        return GenerationResponse(
            text=text,
            message_id=message_id,
            model=model,
            usage=usage,
        )