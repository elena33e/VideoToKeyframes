"""Operații asupra sesiunii, reutilizabile din GUI și API."""
from collections.abc import Iterable
from pathlib import Path
from uuid import uuid4

from PIL import Image

from extraction.models import ExtractedFrame, ExtractionResult

from .models import ImportedFrame, KeyframeState, WorkflowSession


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
) -> tuple[ExtractedFrame | ImportedFrame, ...]:
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


def create_session_from_images(
    image_paths: Iterable[str | Path],
) -> WorkflowSession:
    """Validează imaginile locale și creează o sesiune nouă."""
    if isinstance(image_paths, (str, Path)):
        raise ValueError(
            "Trimite o colecție de căi, nu o singură cale."
        )

    imported = []
    seen = set()

    for value in image_paths:
        path = Path(value).expanduser().resolve(strict=True)

        if not path.is_file():
            raise ValueError(f"Nu este un fișier: {path}")

        if path in seen:
            continue

        try:
            with Image.open(path) as image:
                image.verify()
        except (OSError, ValueError) as exc:
            raise ValueError(
                f"Imagine invalidă: {path.name}"
            ) from exc

        seen.add(path)
        imported.append(
            ImportedFrame(
                frame_id=f"image_{uuid4().hex}",
                image_path=path,
            )
        )

    if not imported:
        raise ValueError("Selectează cel puțin o imagine.")

    return WorkflowSession(
        imported_frames=tuple(imported),
        frames=tuple(
            KeyframeState(frame_id=frame.frame_id)
            for frame in imported
        ),
    )


def get_frame_path(
    session: WorkflowSession,
    frame_id: str,
    *,
    must_exist: bool = True,
) -> Path:
    """Rezolvă calea unei imagini din sesiune."""
    frame = next(
        (
            frame
            for frame in session.keyframes
            if frame.frame_id == frame_id
        ),
        None,
    )

    if frame is None:
        raise ValueError(f"Cadru necunoscut: {frame_id}")

    if session.extraction is None:
        path = frame.image_path.resolve(strict=must_exist)
    else:
        base = session.extraction.output_dir.resolve()
        path = (base / frame.image_path).resolve(
            strict=must_exist
        )

        if not path.is_relative_to(base):
            raise ValueError(
                "Imaginea trebuie să fie în directorul extragerii."
            )

    if must_exist and not path.is_file():
        raise ValueError(
            f"Imaginea nu este un fișier: {path}"
        )

    return path