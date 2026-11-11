"""Rezultatele tipizate ale extragerii, independente de GUI și VLM."""

from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    field_validator,
    model_validator,
)


NonEmptyText = Annotated[str, Field(min_length=1)]

ExtractionStatus = Literal[
    "running",
    "success",
    "partial",
    "cancelled",
    "failed",
]

SceneStatus = Literal[
    "pending",
    "not_selected",
    "processing",
    "success",
    "failed",
    "cancelled",
]


class ExtractionModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class ExtractionSettings(ExtractionModel):
    allocation: Literal["duration_density"] = "duration_density"

    seconds_per_keyframe: PositiveFloat
    min_scene_duration_seconds: PositiveFloat = 0.5
    max_total_keyframes: PositiveInt | None = None

    threshold: float | None = Field(default=None, ge=0)
    max_workers: PositiveInt | None = None
    katna_window_frames: PositiveInt | None = None


class ExtractedFrame(ExtractionModel):
    frame_id: NonEmptyText
    scene_index: NonNegativeInt

    # Cale relativă la ExtractionResult.output_dir.
    image_path: Path

    @field_validator("image_path")
    @classmethod
    def validate_relative_path(cls, value: Path) -> Path:
        if (
            value.is_absolute()
            or value.drive
            or value.root
            or ".." in value.parts
            or value == Path(".")
        ):
            raise ValueError(
                "Calea cadrului trebuie să fie relativă la output_dir, "
                "fără componente '..'."
            )

        return value


class SceneExtractionResult(ExtractionModel):
    index: NonNegativeInt

    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)

    start_frame: NonNegativeInt
    end_frame: NonNegativeInt

    status: SceneStatus = "pending"
    requested_frames: NonNegativeInt = 0

    frames: tuple[ExtractedFrame, ...] = ()
    clip: Path | None = None
    error: str | None = None

    @model_validator(mode="after")
    def validate_scene(self) -> Self:
        if self.end_seconds <= self.start_seconds:
            raise ValueError(
                "Intervalul temporal al scenei este invalid."
            )

        if self.end_frame <= self.start_frame:
            raise ValueError(
                "Intervalul cadrelor scenei este invalid."
            )

        if any(
            frame.scene_index != self.index
            for frame in self.frames
        ):
            raise ValueError(
                "Un cadru este asociat altei scene."
            )

        ids = [frame.frame_id for frame in self.frames]
        paths = [frame.image_path for frame in self.frames]

        if (
            len(ids) != len(set(ids))
            or len(paths) != len(set(paths))
        ):
            raise ValueError(
                "Scena conține cadre duplicate."
            )

        return self


class ExtractionError(ExtractionModel):
    scene: NonNegativeInt | None = None
    message: str


class ExtractionResult(ExtractionModel):
    schema_version: Literal["2.0"] = "2.0"

    run_id: NonEmptyText
    status: ExtractionStatus = "running"

    input_video: Path
    output_dir: Path
    manifest: Path

    started_at: datetime
    finished_at: datetime | None = None

    settings: ExtractionSettings

    total_keyframes: NonNegativeInt = 0
    target_keyframes: NonNegativeInt = 0
    detected_scenes: NonNegativeInt = 0
    total_scenes: NonNegativeInt = 0
    selected_scenes: NonNegativeInt = 0
    processed_scenes: NonNegativeInt = 0
    covered_scenes: NonNegativeInt = 0
    omitted_scenes: NonNegativeInt = 0

    scenes: tuple[SceneExtractionResult, ...] = ()
    errors: tuple[ExtractionError, ...] = ()
    message: str = ""