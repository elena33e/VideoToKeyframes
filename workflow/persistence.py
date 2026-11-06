"""Salvarea sesiunilor, independentă de interfața grafică."""

import json
import tempfile
from pathlib import Path

from .jsonld import session_to_jsonld
from .models import WorkflowSession
from .service import get_frame_path


def save_session_jsonld(
    session: WorkflowSession,
    destination: str | Path,
) -> Path:
    """Salvează sesiunea și returnează calea absolută.

    Directorul destinației trebuie să existe.
    Un export existent este înlocuit după scrierea completă
    a fișierului temporar. Fișierele sursă sunt protejate.
    """
    destination = Path(destination).expanduser().resolve()

    if destination.suffix.lower() != ".jsonld":
        raise ValueError("Folosește extensia .jsonld.")

    protected = {
        get_frame_path(session, frame.frame_id, must_exist=False)
        for frame in session.keyframes
    }

    if session.extraction is not None:
        protected.update({
            session.extraction.input_video.resolve(),
            session.extraction.manifest.resolve(),
        })

    if session.ontology_path is not None:
        protected.add(session.ontology_path.resolve())

    if destination in protected:
        raise ValueError(
            "Sesiunea nu poate înlocui fișierele sursă."
        )

    content = json.dumps(
        session_to_jsonld(session),
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ) + "\n"

    temporary = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=".workflow_",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)

        temporary.replace(destination)
        return destination

    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass