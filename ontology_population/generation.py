"""Contractul strategiilor de generare pentru popularea ontologiei."""

from dataclasses import dataclass
from typing import Any, Protocol


class GenerationError(RuntimeError):
    """Apelul a eșuat sau răspunsul furnizorului este incomplet."""


@dataclass(frozen=True)
class GenerationResponse:
    text: str
    message_id: str
    model: str
    usage: dict[str, Any]


class GenerationStrategy(Protocol):
    def generate(
        self,
        *,
        system_prompt: str,
        ontology_turtle: str,
        user_prompt: str,
    ) -> GenerationResponse:
        ...