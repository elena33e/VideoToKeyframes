"""Jurnal local pentru apelurile HTTP către modelele VLM."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import httpx


LOGGER = logging.getLogger(__name__)


def _write_entry(
    directory: Path,
    filename: str,
    value: bytes | dict[str, Any],
) -> None:
    try:
        path = directory / filename

        if isinstance(value, bytes):
            path.write_bytes(value)
        else:
            path.write_text(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    indent=2,
                    allow_nan=False,
                ),
                encoding="utf-8",
            )

    except (OSError, TypeError, ValueError) as exc:
        LOGGER.warning(
            "Nu s-a putut salva jurnalul %s (%s).",
            directory / filename,
            type(exc).__name__,
        )


def post_with_journal(
    endpoint: str,
    *,
    headers: dict[str, str],
    content: bytes,
    timeout: httpx.Timeout,
    journal_directory: Path | None = None,
) -> httpx.Response:
    directory: Path | None = None

    if journal_directory is not None:
        candidate = Path(journal_directory) / uuid4().hex

        try:
            candidate.mkdir(parents=True, exist_ok=False)
            directory = candidate
        except OSError as exc:
            LOGGER.warning(
                "Nu s-a putut crea jurnalul cererii (%s).",
                type(exc).__name__,
            )

    if directory is not None:
        _write_entry(directory, "request.json", content)
        _write_entry(directory, "request.meta.json", {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "endpoint": endpoint,
        })

    started = perf_counter()

    try:
        response = httpx.post(
            endpoint,
            headers=headers,
            content=content,
            timeout=timeout,
        )

    except httpx.RequestError as exc:
        if directory is not None:
            _write_entry(directory, "transport_error.json", {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "error_type": type(exc).__name__,
                "elapsed_seconds": round(
                    perf_counter() - started, 3
                ),
            })
        raise

    elapsed = round(perf_counter() - started, 3)

    if directory is not None:
        _write_entry(
            directory,
            "response.body",
            response.content,
        )
        _write_entry(directory, "response.meta.json", {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status_code": response.status_code,
            "elapsed_seconds": elapsed,
            "x_request_id": response.headers.get("x-request-id"),
        })

    return response