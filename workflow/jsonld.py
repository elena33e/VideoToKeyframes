from typing import Any
from urllib.parse import quote

from interpretation.config import SESSION_BASE_IRI
from interpretation.jsonld_context import build_observation_context

from .models import WorkflowSession


def session_to_jsonld(session: WorkflowSession) -> dict[str, Any]:
    """Construiește documentul JSON-LD al sesiunii, fără operații de fișier."""
    base_iri = (
        SESSION_BASE_IRI
        + quote(session.session_id, safe="")
        + "/"
    )

    context = build_observation_context(base_iri=base_iri)

    context.update({
        "WorkflowSession": "obs:WorkflowSession",
        "KeyframeState": "obs:KeyframeState",

        "session_id": "obs:sessionId",

        # Păstrăm explicit ordinea cadrelor.
        "frames": {
            "@id": "obs:frames",
            "@container": "@list",
        },

        "selected": "obs:selected",
        "description_status": "obs:descriptionStatus",
        "error": "obs:error",
        "ontology_path": "obs:ontologyPath",

        # Păstrăm structura completă a rezultatului extragerii.
        "extraction": {
            "@id": "obs:extraction",
            "@type": "@json",
        },

        "imported_frames": {
            "@id": "obs:importedFrames",
            "@type": "@json",
        },
    })

    data = session.model_dump(mode="json")

    data["@context"] = context
    data["id"] = base_iri
    data["type"] = "WorkflowSession"

    for frame_data, state in zip(
        data["frames"],
        session.frames,
        strict=True,
    ):
        frame_data["id"] = (
            base_iri
            + "frames/"
            + quote(state.frame_id, safe="")
        )
        frame_data["type"] = "KeyframeState"

        frame_data["observation"] = (
            state.observation.to_jsonld()
            if state.observation is not None
            else None
        )

    return data