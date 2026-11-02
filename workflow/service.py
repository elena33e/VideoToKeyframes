"""Operații asupra sesiunii, reutilizabile din GUI și API."""

from collections.abc import Iterable

from extraction.models import ExtractedFrame, ExtractionResult

from .models import KeyframeState, WorkflowSession


def create_session(
    extraction: ExtractionResult,
) -> WorkflowSession:
    # Copie validată: sesiunea nu modifică obiectul primit de la pipeline.
    snapshot = ExtractionResult.model_validate(
        extraction.model_dump()
    )

    states = tuple(
        KeyframeState(frame_id=frame.frame_id)
        for scene in snapshot.scenes
        if scene.status == "success"
        for frame in scene.frames
    )

    return WorkflowSession(
        extraction=snapshot,
        frames=states,
    )


def set_selection(
    session: WorkflowSession,
    frame_ids: Iterable[str],
) -> WorkflowSession:
    """Înlocuiește selecția completă și returnează o sesiune nouă."""
    if isinstance(frame_ids, str):
        raise ValueError(
            "Trimite o colecție de ID-uri, nu un singur text."
        )

    if any(
        state.description_status == "running"
        for state in session.frames
    ):
        raise ValueError(
            "Selecția nu poate fi schimbată în timpul descrierii."
        )

    selected_ids = set(frame_ids)
    known_ids = {
        state.frame_id
        for state in session.frames
    }

    unknown_ids = selected_ids - known_ids
    if unknown_ids:
        raise ValueError(
            f"Cadre necunoscute: {unknown_ids}"
        )

    data = session.model_dump()

    for state in data["frames"]:
        state["selected"] = (
            state["frame_id"] in selected_ids
        )

    return WorkflowSession.model_validate(data)


def get_selected_frames(
    session: WorkflowSession,
) -> tuple[ExtractedFrame, ...]:
    selected_ids = {
        state.frame_id
        for state in session.frames
        if state.selected
    }

    return tuple(
        frame
        for frame in session.keyframes
        if frame.frame_id in selected_ids
    )