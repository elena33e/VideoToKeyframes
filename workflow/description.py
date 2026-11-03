"""Descriere secvențială, independentă de GUI și de furnizorul VLM."""

import hashlib
from collections.abc import Iterator
from pathlib import Path
from threading import Event
from typing import Literal, Protocol

from pydantic import Field
from interpretation.observations import FrameObservation

from .models import DescriptionStatus, WorkflowModel, WorkflowSession
from .service import get_frame_path, get_selected_frames


class FrameDescriber(Protocol):
    def describe(
        self,
        image_path: str | Path,
        *,
        frame_id: str,
        scene_index: int | None = None,
    ) -> FrameObservation:
        ...


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



def describe_selected(
    session: WorkflowSession,
    describer: FrameDescriber,
    *,
    regenerate: bool = False,
    cancel_event: Event | None = None,
) -> Iterator[DescriptionProgress]:
    """Produce progres și versiuni actualizate ale sesiunii.

    Nu salvează fișiere și nu pornește fire de execuție.
    Anularea oprește procesarea înaintea următorului apel.
    """
    current = WorkflowSession.model_validate(
        session.model_dump()
    )

    if any(
        state.description_status == "running"
        for state in current.frames
    ):
        raise ValueError(
            "Sesiunea conține deja un cadru în procesare."
        )

    frames = get_selected_frames(current)

    if not frames:
        raise ValueError(
            "Selectează cel puțin un cadru."
        )

    cancel = cancel_event if cancel_event is not None else Event()

    total = len(frames)
    processed = succeeded = failed = skipped = 0

    def progress(kind, frame_id=None):
        return DescriptionProgress(
            kind=kind,
            session=current,
            frame_id=frame_id,
            processed=processed,
            total=total,
            succeeded=succeeded,
            failed=failed,
            skipped=skipped,
        )

    yield progress("batch_started")

    for frame in frames:
        if cancel.is_set():
            yield progress("batch_cancelled")
            return

        before = current

        previous = next(
            state
            for state in current.frames
            if state.frame_id == frame.frame_id
        )

        current = _update_frame(
            current,
            frame.frame_id,
            "running",
        )

        yield progress("frame_started", frame.frame_id)

        if cancel.is_set():
            current = before
            yield progress("batch_cancelled")
            return

        try:
            path = get_frame_path(current, frame.frame_id)

            if previous.observation is not None and not regenerate:
                current_hash = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()

                if current_hash != previous.observation.image_sha256:
                    raise ValueError(
                        "Imaginea diferă de cea descrisă anterior. "
                        "Selectează explicit regenerarea descrierii."
                    )

                # Păstrăm observația și starea anterioară.
                current = before
                skipped += 1
                kind = "frame_skipped"

            else:
                observation = FrameObservation.model_validate(
                    describer.describe(
                        path,
                        frame_id=frame.frame_id,
                        scene_index=frame.scene_index,
                    )
                )

                current = _update_frame(
                    current,
                    frame.frame_id,
                    "completed",
                    observation=observation,
                )

                succeeded += 1
                kind = "frame_completed"

        except Exception as exc:
            message = str(exc).strip() or type(exc).__name__

            current = _update_frame(
                current,
                frame.frame_id,
                "failed",
                error=f"{type(exc).__name__}: {message}",
            )

            failed += 1
            kind = "frame_failed"

        processed += 1
        yield progress(kind, frame.frame_id)

    yield progress("batch_finished")