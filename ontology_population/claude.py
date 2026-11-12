"""Apeluri text către Claude Messages API."""

from math import isfinite

import httpx

from .config import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_CLAUDE_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
)
from .generation import GenerationError, GenerationResponse

MESSAGES_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2026-10-21"

class ClaudeError(GenerationError):
    """Cerere eșuată sau răspuns incomplet de la Claude."""


class ClaudeClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_CLAUDE_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ):
        self._api_key = api_key.strip()
        self.model = model.strip()
        if not self._api_key:
            raise ValueError("ANTHROPIC_API_KEY lipsește.")
        if not self.model:
            raise ValueError("Identificatorul modelului Claude lipsește.")
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
            "max_tokens": self._max_output_tokens,
            "system": [
                {"type": "text", "text": system_prompt},
                {
                    "type": "text",
                    "text": "Ontologia furnizată în Turtle:\n" + ontology_turtle,
                    "cache_control": {"type": "ephemeral"},
                },
            ],
            "messages": [{"role": "user", "content": user_prompt}],
        }
        try:
            response = httpx.post(
                MESSAGES_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "anthropic-version": API_VERSION,
                },
                json=payload,
                timeout=self._timeout_seconds,
            )
        except httpx.RequestError as exc:
            raise ClaudeError(
                f"Conexiunea cu Claude a eșuat ({type(exc).__name__})."
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
            raise ClaudeError(f"Claude a răspuns cu HTTP {response.status_code}: {detail}")

        if not isinstance(body, dict):
            raise ClaudeError("Claude nu a returnat un obiect JSON.")

        stop_details = body.get("stop_details")
        if isinstance(stop_details, dict) and stop_details.get("type") == "refusal":
            raise ClaudeError("Claude a refuzat cererea.")

        stop_reason = body.get("stop_reason")
        if stop_reason != "end_turn":
            raise ClaudeError(f"Răspuns Claude incomplet: stop_reason={stop_reason!r}.")

        content = body.get("content")
        if not isinstance(content, list):
            raise ClaudeError("Lipsește conținutul răspunsului Claude.")
        text = "".join(
            block["text"]
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        )
        message_id = body.get("id")
        model = body.get("model")
        usage = body.get("usage")
        if (
            not text.strip()
            or not isinstance(message_id, str) or not message_id
            or not isinstance(model, str) or not model
            or not isinstance(usage, dict)
        ):
            raise ClaudeError("Răspunsul Claude nu conține textul sau metadatele așteptate.")

        return GenerationResponse(text=text, message_id=message_id, model=model, usage=usage)
