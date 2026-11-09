"""Funcții comune pentru API-uri compatibile Chat Completions."""

import base64
import json
import math
from time import perf_counter
from typing import Any

import httpx

from ..contracts import VLMError, VLMRequest, VLMResponse


# Limită conservatoare a aplicației, după codificarea Base64.
MAX_REQUEST_BYTES = 18_000_000


def validate_connection(
    api_key: str,
    model: str,
    timeout_seconds: float,
) -> None:
    if not api_key.strip():
        raise ValueError("Cheia API lipsește.")

    if not model.strip():
        raise ValueError("Identificatorul modelului lipsește.")

    if (
        not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError(
            "timeout_seconds trebuie să fie un număr pozitiv."
        )


def _error_detail(response: httpx.Response, api_key: str) -> str:
    try:
        body = response.json()
    except ValueError:
        body = None

    entries = body if isinstance(body, list) else [body]
    messages = []

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        error = entry.get("error")

        if isinstance(error, dict):
            message = (
                error.get("message")
                or error.get("status")
                or str(error)
            )
            messages.append(str(message))

        elif isinstance(error, str):
            messages.append(error)

    detail = (
        "\n".join(messages)
        or response.text.strip()
        or "Serviciul a returnat un răspuns gol."
    )

    return detail.replace(api_key, "[CHEIE ASCUNSĂ]")[:3000]


def execute_chat_request(
    *,
    endpoint: str,
    api_key: str,
    provider: str,
    model: str,
    request: VLMRequest,
    parameters: dict[str, Any],
    timeout_seconds: float,
    token_limit_parameter: str = "max_tokens",
) -> VLMResponse:
    """Execută o cerere fără să interpreteze observațiile generate."""

    content = [
        {
            "type": "text",
            "text": request.user_prompt,
        }
    ]

    for image in request.images:
        encoded = base64.b64encode(image.data).decode("ascii")

        content.extend([
            {
                "type": "text",
                "text": "FRAME_ID: " + json.dumps(image.frame_id),
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": (
                        f"data:{image.mime_type};base64,{encoded}"
                    ),
                },
            },
        ])

    effective_parameters = {
        token_limit_parameter: request.max_output_tokens,
        **parameters,
    }

    payload = {
        **effective_parameters,
        "model": model,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": request.system_prompt,
            },
            {
                "role": "user",
                "content": content,
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "image_observation_batch",
                "strict": True,
                "schema": request.response_schema,
            },
        },
    }

    encoded_payload = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

    if len(encoded_payload) > MAX_REQUEST_BYTES:
        raise VLMError(
            "Cererea depășește limita aplicației de 18 MB. "
            "Redu numărul imaginilor din grup."
        )

    started = perf_counter()

    try:
        response = httpx.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            content=encoded_payload,
            timeout=httpx.Timeout(
                timeout_seconds,
                connect=min(15.0, timeout_seconds),
            ),
        )

    except httpx.TimeoutException as exc:
        raise VLMError(
            f"{provider}: timpul de așteptare a fost depășit."
        ) from exc

    except httpx.RequestError as exc:
        raise VLMError(
            f"Nu s-a putut comunica cu {provider}."
        ) from exc

    elapsed = round(perf_counter() - started, 3)

    if response.is_error:
        raise VLMError(
            f"{provider} HTTP {response.status_code}\n"
            f"Model: {model}\n"
            f"Detalii: {_error_detail(response, api_key)}"
        )

    try:
        data = response.json()

        if not isinstance(data, dict):
            raise ValueError("Răspunsul nu este un obiect JSON.")

        # Unele servicii pot include o eroare în corpul unui HTTP 200.
        if data.get("error"):
            raise VLMError(
                f"{provider}: {_error_detail(response, api_key)}"
            )

        choice = data["choices"][0]
        finish_reason = choice.get("finish_reason")

        if finish_reason != "stop":
            raise VLMError(
                f"{provider}: răspuns incomplet sau oprit. "
                f"finish_reason={finish_reason!r}."
            )

        generated_content = choice["message"]["content"]

        if (
            not isinstance(generated_content, str)
            or not generated_content.strip()
        ):
            raise ValueError("Conținutul textual lipsește.")

        usage = data.get("usage") or {}

        if not isinstance(usage, dict):
            raise ValueError("Metadatele de consum sunt invalide.")

        resolved_model = data.get("model") or model
        request_id = data.get("id")
        backend_provider = data.get("provider")

        if not isinstance(resolved_model, str):
            raise ValueError("Identificatorul modelului este invalid.")

        for value in (request_id, backend_provider):
            if value is not None and not isinstance(value, str):
                raise ValueError("Metadatele răspunsului sunt invalide.")

    except (
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        AttributeError,
    ) as exc:
        raise VLMError(
            f"{provider}: răspunsul nu are structura așteptată."
        ) from exc

    return VLMResponse(
        content=generated_content,
        requested_model=model,
        resolved_model=resolved_model,
        provider=provider,
        api_request_id=request_id,
        finish_reason=finish_reason,
        elapsed_seconds=elapsed,
        usage=usage,
        request_parameters=effective_parameters,
        backend_provider=backend_provider,
    )