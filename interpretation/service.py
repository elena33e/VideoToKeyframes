"""Interpretarea grupurilor folosind o strategie VLM injectată."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from .config import InterpretationConfig
from .contracts import (
    MAX_GROUP_SIZE,
    FrameInput,
    VLMError,
    VLMImage,
    VLMRequest,
    VLMResponse,
)
from .images import read_validated_image
from .observations import BatchResponse, FrameObservation
from .prompting import PROMPT_VERSION, build_prompts
from .strategies.base import VLMStrategy

def _previous_group_actions(
    previous_group: tuple[FrameObservation, ...],
) -> list[dict[str, str | bool]]:
    actions = []
    for frame in previous_group:
        for uncertain in (False, True):
            action = next(
                (item for item in frame.observation.actions
                 if item.uncertain == uncertain),
                None,
            )
            if action is not None:
                description = " ".join(action.description.split())
                if len(description) > 160:
                    description = description[:159].rstrip() + "…"
                actions.append({
                    "description": description,
                    "uncertain": uncertain,
                })
    return actions


class BatchInterpretationService:
    """Contextul din patternul Strategy."""

    def __init__(
        self,
        strategy: VLMStrategy,
        config: InterpretationConfig,
    ):
        self._strategy = strategy
        self._config = config

    def describe_batch(
        self,
        frames: list[FrameInput],
        *,
        previous_group: tuple[FrameObservation, ...] = (),
    ) -> dict[str, FrameObservation]:
        """Generează și validează observațiile unui grup."""

        if not 1 <= len(frames) <= MAX_GROUP_SIZE:
            raise ValueError(
                f"Grupul trebuie să conțină între 1 și "
                f"{MAX_GROUP_SIZE} cadre."
            )

        frame_ids = [frame.frame_id for frame in frames]

        if len(set(frame_ids)) != len(frame_ids):
            raise ValueError(
                "Grupul conține identificatori de cadre duplicați."
            )

        images = []
        image_hashes = {}

        for frame in frames:
            path = Path(frame.image_path).expanduser().resolve(
                strict=True
            )
            raw, mime_type = read_validated_image(path)

            images.append(
                VLMImage(
                    frame_id=frame.frame_id,
                    mime_type=mime_type,
                    data=raw,
                )
            )

            image_hashes[frame.frame_id] = hashlib.sha256(
                raw
            ).hexdigest()

        previous_group_actions = _previous_group_actions(previous_group)
        system_prompt, user_prompt = build_prompts(
            self._config,
            previous_group_actions=previous_group_actions,
        )

        request = VLMRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            images=tuple(images),
            response_schema=BatchResponse.vlm_json_schema(),
            max_output_tokens=(
                self._config.max_output_tokens_per_image
                * len(frames)
            ),
        )

        # Singurul punct în care serviciul apelează strategia.
        response = self._strategy.generate(request)

        if not isinstance(response, VLMResponse):
            raise VLMError(
                "Strategia nu a returnat un VLMResponse."
            )

        if response.finish_reason != "stop":
            raise VLMError(
                "Răspunsul grupului nu este complet: "
                f"{response.finish_reason!r}."
            )

        try:
            batch_response = BatchResponse.model_validate_json(
                response.content
            )

        except ValidationError as exc:
            details = json.dumps(
                exc.errors(
                    include_input=False,
                    include_context=False,
                ),
                ensure_ascii=False,
            )

            raise VLMError(
                f"Observații invalide în grup: {details[:2000]}"
            ) from exc

        received_ids = [
            item.frame_id for item in batch_response.frames
        ]

        if (
            len(received_ids) != len(frame_ids)
            or set(received_ids) != set(frame_ids)
        ):
            raise VLMError(
                "Rezultatul conține cadre lipsă, duplicate "
                "sau identificatori necunoscuți."
            )

        observations_by_id = {
            item.frame_id: item.observation
            for item in batch_response.frames
        }

        group_id = uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()

        ontology_context = self._ontology_metadata()

        results = {}

        for frame in frames:
            results[frame.frame_id] = FrameObservation(
                schema_version="1.0",
                frame_id=frame.frame_id,
                scene_index=frame.scene_index,
                image_sha256=image_hashes[frame.frame_id],
                created_at=created_at,
                prompt_version=PROMPT_VERSION,
                requested_model=response.requested_model,
                resolved_model=response.resolved_model,
                provider=response.provider,
                api_request_id=response.api_request_id,
                elapsed_seconds=response.elapsed_seconds,
                parameters={
                    **response.request_parameters,
                    "language": self._config.language,
                    "domain_context": (
                        self._config.domain_context.strip() or None
                    ),
                    "ontology_context": ontology_context,
                    "backend_provider": response.backend_provider,
                    "previous_group_frame_ids": [
                        item.frame_id for item in previous_group
                    ],
                    "previous_group_actions": previous_group_actions,
                    "batch": {
                        "id": group_id,
                        "size": len(frames),
                        "frame_ids": frame_ids,
                        "image_sha256_by_frame": image_hashes,
                    },
                },
                usage={
                    "scope": "request",
                    "request_group_id": group_id,
                    "request_usage": response.usage,
                },
                observation=observations_by_id[frame.frame_id],
            )

        return results

    def _ontology_metadata(self) -> dict | None:
        config = self._config

        if not config.ontology_context:
            return None

        return {
            "turtle": config.ontology_context,
            "namespace": config.ontology_namespace,
            "source_sha256": config.ontology_source_sha256,
            "extraction_version": config.ontology_extraction_version,
            "context_sha256": hashlib.sha256(
                config.ontology_context.encode("utf-8")
            ).hexdigest(),
        }