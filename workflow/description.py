"""Progresul descrierii și actualizarea stării cadrelor."""

from typing import Literal

from pydantic import Field

from interpretation.observations import FrameObservation

from .models import DescriptionStatus, WorkflowModel, WorkflowSession


class DescriptionProgress(WorkflowModel):
    kind: Literal[
        "batch_started",
        "frame_started",
        "frame_completed",
        "frame_failed",
        "frame_skipped",
        "batch_finished",
        "batch_cancelled",
    ]

    session: WorkflowSession
    frame_id: str | None = None

    processed: int = Field(ge=0)
    total: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    skipped: int = Field(ge=0)


def _update_frame(
    session: WorkflowSession,
    frame_id: str,
    status: DescriptionStatus,
    *,
    observation: FrameObservation | None = None,
    error: str | None = None,
) -> WorkflowSession:
    data = session.model_dump()

    for state in data["frames"]:
        if state["frame_id"] == frame_id:
            state["description_status"] = status
            state["error"] = error

            if observation is not None:
                state["observation"] = observation.model_dump()

            break
    else:
        raise ValueError(f"Cadru necunoscut: {frame_id}")

    return WorkflowSession.model_validate(data)