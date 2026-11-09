"""Date comune serviciului de interpretare și strategiilor VLM."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


MAX_GROUP_SIZE = 4


class VLMError(RuntimeError):
    """Eroare de comunicare sau răspuns neacceptabil de la furnizor."""


@dataclass(frozen=True)
class FrameInput:
    """Un cadru pe care serviciul trebuie să îl interpreteze."""

    image_path: Path
    frame_id: str
    scene_index: int | None = None

    def __post_init__(self):
        if not self.frame_id.strip():
            raise ValueError("frame_id nu poate fi gol.")

        if self.scene_index is not None and (
            type(self.scene_index) is not int
            or self.scene_index < 0
        ):
            raise ValueError(
                "scene_index trebuie să fie un întreg nenegativ sau None."
            )


@dataclass(frozen=True)
class VLMImage:
    """Imagine citită și validată, pregătită pentru trimitere."""

    frame_id: str
    mime_type: str
    data: bytes = field(repr=False)

    def __post_init__(self):
        if not self.frame_id.strip():
            raise ValueError("Imaginea trebuie să aibă un frame_id.")

        if self.mime_type not in {
            "image/jpeg",
            "image/png",
            "image/webp",
        }:
            raise ValueError(
                f"Tip de imagine nesuportat: {self.mime_type}"
            )

        if not self.data:
            raise ValueError("Conținutul imaginii este gol.")


@dataclass(frozen=True)
class VLMRequest:
    """Cererea independentă de formatul API al furnizorului."""

    system_prompt: str
    user_prompt: str
    images: tuple[VLMImage, ...]
    response_schema: dict[str, Any]

    # Buget pentru răspunsul întregului grup.
    max_output_tokens: int

    def __post_init__(self):
        if not self.system_prompt.strip():
            raise ValueError("Promptul de sistem este gol.")

        if not self.user_prompt.strip():
            raise ValueError("Promptul utilizatorului este gol.")

        if not 1 <= len(self.images) <= MAX_GROUP_SIZE:
            raise ValueError(
                f"Cererea trebuie să conțină între 1 și "
                f"{MAX_GROUP_SIZE} imagini."
            )

        frame_ids = [image.frame_id for image in self.images]

        if len(set(frame_ids)) != len(frame_ids):
            raise ValueError(
                "Identificatorii imaginilor trebuie să fie unici."
            )

        if not self.response_schema:
            raise ValueError("Schema răspunsului lipsește.")

        if (
            type(self.max_output_tokens) is not int
            or self.max_output_tokens <= 0
        ):
            raise ValueError(
                "max_output_tokens trebuie să fie un întreg pozitiv."
            )


@dataclass(frozen=True)
class VLMResponse:
    """Răspuns normalizat, înainte de validarea observațiilor."""

    content: str
    requested_model: str
    resolved_model: str

    # Furnizorul API ales în aplicație: gemini sau openrouter.
    provider: str

    api_request_id: str | None
    finish_reason: str | None
    elapsed_seconds: float

    # Consumul întregii cereri, nu consumul unei singure imagini.
    usage: dict[str, Any] = field(default_factory=dict)

    # Parametrii efectiv utilizați, fără chei API sau imagini.
    request_parameters: dict[str, Any] = field(default_factory=dict)

    # Opțional: furnizorul efectiv de inferență raportat de OpenRouter.
    backend_provider: str | None = None