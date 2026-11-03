"""Starea fluxului, independentă de interfața utilizatorului."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from extraction.models import ExtractedFrame, ExtractionResult
from interpretation.observations import FrameObservation


NonEmptyText = Annotated[str, Field(min_length=1)]

DescriptionStatus = Literal[
    "pending",
    "running",
    "completed",
    "failed",
]


class WorkflowModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class KeyframeState(WorkflowModel):
    frame_id: NonEmptyText
    selected: bool = False

    # Starea ultimei încercări de descriere.
    description_status: DescriptionStatus = "pending"

    # Ultima observație validă, păstrată inclusiv dacă o regenerare eșuează.
    observation: FrameObservation | None = None
    error: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if (
            self.description_status == "completed"
            and self.observation is None
        ):
            raise ValueError(
                "Lipsește observația cadrului finalizat."
            )

        if self.description_status == "failed":
            if self.error is None:
                raise ValueError(
                    "Lipsește eroarea ultimei încercări."
                )
        elif self.error is not None:
            raise ValueError(
                "Eroarea este permisă numai pentru starea failed."
            )

        if (
            self.description_status == "pending"
            and self.observation is not None
        ):
            raise ValueError(
                "Un cadru nedescris nu poate avea observație."
            )

        if (
            self.observation is not None
            and self.observation.frame_id != self.frame_id
        ):
            raise ValueError(
                "Observația aparține altui cadru."
            )

        return self


class ImportedFrame(WorkflowModel):
    frame_id: NonEmptyText
    image_path: Path
    scene_index: None = None

    @model_validator(mode="after")
    def validate_path(self) -> Self:
        if not self.image_path.is_absolute():
            raise ValueError(
                "Imaginea importată trebuie să aibă o cale absolută."
            )
        return self


class WorkflowSession(WorkflowModel):
    schema_version: Literal["2.0", "2.1"] = "2.1"

    session_id: NonEmptyText = Field(
        default_factory=lambda: uuid4().hex
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    extraction: ExtractionResult | None = None
    imported_frames: tuple[ImportedFrame, ...] = ()
    frames: tuple[KeyframeState, ...] = ()

    # Independentă de descrierea imaginilor.
    ontology_path: Path | None = None

    @property
    def keyframes(self) -> tuple[ExtractedFrame | ImportedFrame, ...]:
        if self.extraction is None:
            return self.imported_frames

        return tuple(
            frame
            for scene in self.extraction.scenes
            if scene.status == "success"
            for frame in scene.frames
        )

    @model_validator(mode="after")
    def validate_session(self) -> Self:
        if self.extraction is None:
            if not self.imported_frames:
                raise ValueError(
                    "Sesiunea trebuie să conțină o extragere "
                    "sau imagini importate."
                )
        else:
            if self.imported_frames:
                raise ValueError(
                    "Sesiunea nu poate combina o extragere "
                    "cu imagini importate."
                )

            if self.extraction.status == "running":
                raise ValueError(
                    "Așteaptă încheierea extragerii."
                )

            scene_ids = [
                scene.index
                for scene in self.extraction.scenes
            ]

            if len(scene_ids) != len(set(scene_ids)):
                raise ValueError(
                    "Rezultatul conține scene duplicate."
                )

        keyframes = self.keyframes
        source_ids = [
            frame.frame_id
            for frame in keyframes
        ]
        paths = [
            frame.image_path
            for frame in keyframes
        ]
        state_ids = [
            state.frame_id
            for state in self.frames
        ]

        if len(source_ids) != len(set(source_ids)):
            raise ValueError(
                "Există ID-uri de cadru duplicate."
            )

        if len(paths) != len(set(paths)):
            raise ValueError(
                "Aceeași imagine apare de mai multe ori."
            )

        if len(state_ids) != len(set(state_ids)):
            raise ValueError(
                "Există mai multe stări pentru același cadru."
            )

        if set(state_ids) != set(source_ids):
            raise ValueError(
                "Fiecare imagine trebuie să aibă exact o stare."
            )

        by_id = {
            frame.frame_id: frame
            for frame in keyframes
        }

        for state in self.frames:
            if (
                state.observation is not None
                and state.observation.scene_index
                != by_id[state.frame_id].scene_index
            ):
                raise ValueError(
                    "Observația aparține altei scene."
                )

        return self