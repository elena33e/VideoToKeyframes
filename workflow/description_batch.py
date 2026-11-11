"""Grupează cadrele și publică progresul individual pentru GUI."""

import hashlib
import math
from threading import Event
from time import monotonic

from interpretation.contracts import FrameInput, MAX_GROUP_SIZE
from interpretation.observations import FrameObservation
from .description import DescriptionProgress, _update_frame
from .models import WorkflowSession
from .service import get_frame_path, get_selected_frames
from interpretation.config import DEFAULT_MIN_REQUEST_INTERVAL_SECONDS


def describe_selected_batches(
    session,
    describer,
    *,
    batch_size=3,
    min_interval_seconds=DEFAULT_MIN_REQUEST_INTERVAL_SECONDS,
    regenerate=False,
    use_previous_group_context=False,
    cancel_event=None,
):
    if type(batch_size) is not int or not 1 <= batch_size <= MAX_GROUP_SIZE:
        raise ValueError(
            f"Numărul imaginilor per apel trebuie să fie între 1 și {MAX_GROUP_SIZE}."
        )
    if not math.isfinite(min_interval_seconds) or min_interval_seconds < 0:
        raise ValueError("Intervalul dintre cereri trebuie să fie nenegativ.")
    current = WorkflowSession.model_validate(session.model_dump())
    if any(s.description_status == "running" for s in current.frames):
        raise ValueError("Sesiunea conține deja cadre în procesare.")
    frames = get_selected_frames(current)
    if not frames:
        raise ValueError("Selectează cel puțin un cadru.")
    cancel = cancel_event if cancel_event is not None else Event()
    total = len(frames)
    processed = succeeded = failed = skipped = 0

    def progress(kind, frame_id=None):
        return DescriptionProgress(
            kind=kind, session=current, frame_id=frame_id,
            processed=processed, total=total, succeeded=succeeded,
            failed=failed, skipped=skipped,
        )

    yield progress("batch_started")
    pending = []
    for frame in frames:
        if cancel.is_set():
            yield progress("batch_cancelled")
            return
        previous = next(s for s in current.frames if s.frame_id == frame.frame_id)
        try:
            path = get_frame_path(current, frame.frame_id)
            if previous.observation is not None and not regenerate:
                if hashlib.sha256(path.read_bytes()).hexdigest() != previous.observation.image_sha256:
                    raise ValueError("Imaginea s-a schimbat. Activează explicit regenerarea.")
                skipped += 1
                processed += 1
                yield progress("frame_skipped", frame.frame_id)
            else:
                pending.append(FrameInput(path, frame.frame_id, frame.scene_index))
        except Exception as exc:
            current = _update_frame(current, frame.frame_id, "failed",
                                    error=f"{type(exc).__name__}: {exc}")
            failed += 1
            processed += 1
            yield progress("frame_failed", frame.frame_id)

    previous_group: tuple[FrameObservation, ...] = ()

    last_started = None
    for offset in range(0, len(pending), batch_size):
        delay = 0.0 if last_started is None else max(
            0.0, min_interval_seconds - (monotonic() - last_started)
        )
        if cancel.wait(delay):
            yield progress("batch_cancelled")
            return
        group = pending[offset:offset + batch_size]
        before = current
        for frame in group:
            current = _update_frame(current, frame.frame_id, "running")
            yield progress("frame_started", frame.frame_id)
        if cancel.is_set():
            current = before
            yield progress("batch_cancelled")
            return
        try:
            last_started = monotonic()
            if previous_group:
                results = describer.describe_batch(
                    group, previous_group=previous_group
                )
            else:
                results = describer.describe_batch(group)

            if set(results) != {f.frame_id for f in group}:
                raise ValueError("Rezultatele nu corespund grupului trimis.")

            # Validăm tot grupul înainte de a publica primul rezultat.
            results = {key: FrameObservation.model_validate(value) for key, value in results.items()}
            if any(results[f.frame_id].frame_id != f.frame_id or
                   results[f.frame_id].scene_index != f.scene_index for f in group):
                raise ValueError("Metadatele observațiilor nu corespund cadrelor.")
        except Exception as exc:
            previous_group = ()
            for frame in group:
                current = _update_frame(current, frame.frame_id, "failed",
                                        error=f"{type(exc).__name__}: {exc}")
                failed += 1
                processed += 1
                yield progress("frame_failed", frame.frame_id)
        else:
            if use_previous_group_context:
                previous_group = tuple(
                    results[frame.frame_id] for frame in group
                )
            # Un apel în curs nu se anulează. Păstrăm rezultatele deja primite.
            for frame in group:
                current = _update_frame(current, frame.frame_id, "completed",
                                        observation=results[frame.frame_id])
                succeeded += 1
                processed += 1
                yield progress("frame_completed", frame.frame_id)
        if cancel.is_set() and processed < total:
            yield progress("batch_cancelled")
            return
    yield progress("batch_finished")
