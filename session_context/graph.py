"""Construirea contextului dintr-un export JSON-LD al aplicației."""

import json
from hashlib import sha256
from typing import Any
from urllib.parse import quote

from rdflib import Dataset, Namespace, URIRef

from interpretation.config import (
    OBSERVATION_BASE_IRI,
    OBSERVATION_NAMESPACE,
    SESSION_BASE_IRI,
)
from interpretation.jsonld_context import build_observation_context

from .models import SessionContext


OBS = Namespace(OBSERVATION_NAMESPACE)


def build_session_context(session: dict[str, Any]) -> SessionContext:
    """Încarcă observațiile finalizate, indiferent de selecția pentru populare."""
    session_id = session["session_id"]
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Lipsește identificatorul sesiunii.")

    base_iri = SESSION_BASE_IRI + quote(session_id, safe="") + "/"
    frame_iris = {}
    analysis_ids = set()
    seen_frames = set()
    nodes = []

    for frame in session["frames"]:
        frame_id = frame["frame_id"]
        if frame_id in seen_frames:
            raise ValueError(f"Cadru duplicat: {frame_id}.")
        seen_frames.add(frame_id)

        if frame["description_status"] != "completed":
            continue

        saved = frame["observation"]
        if saved is None or saved["frame_id"] != frame_id:
            raise ValueError(
                f"Observație absentă sau incompatibilă: {frame_id}."
            )

        analysis_id = saved["analysis_id"]
        if analysis_id in analysis_ids:
            raise ValueError(f"Analiză duplicată: {analysis_id}.")
        analysis_ids.add(analysis_id)

        observation_base = OBSERVATION_BASE_IRI + analysis_id + "/"
        expected_context = build_observation_context(
            base_iri=observation_base
        )
        legacy_context = {
            key: value
            for key, value in expected_context.items()
            if key not in {
                "CharacteristicObservation",
                "characteristics",
                "value",
            }
        }

        if (
                saved["id"] != observation_base
                or saved.get("@context") not in (
                expected_context,
                legacy_context,
        )
        ):
            raise ValueError(
                f"Format de observație incompatibil: {frame_id}."
            )

        image = saved["observation"]
        entity_ids = [entity["id"] for entity in image["entities"]]
        if len(entity_ids) != len(set(entity_ids)) or any(
            not entity_id.startswith(observation_base + "entities/")
            for entity_id in entity_ids
        ):
            raise ValueError(
                f"Identificatori de apariții nevalizi: {frame_id}."
            )

        known_ids = set(entity_ids)
        references = {
            entity_id
            for relation in image["relations"]
            for entity_id in (
                relation["subject_id"],
                relation["object_id"],
            )
        }
        references.update(
            entity_id
            for action in image["actions"]
            for entity_id in action["entity_ids"]
        )
        if not references.issubset(known_ids):
            raise ValueError(
                f"Referință la o apariție necunoscută: {frame_id}."
            )

        frame_iri = URIRef(
            base_iri + "frames/" + quote(frame_id, safe="")
        )
        frame_iris[frame_id] = frame_iri
        nodes.append({
            "@id": str(frame_iri),
            "@type": str(OBS.KeyframeState),
            str(OBS.frameId): frame_id,
            str(OBS.observation): saved,
        })

    if not nodes:
        raise ValueError(
            "Sesiunea nu conține observații finalizate."
        )

    document = {
        "@context": build_observation_context(base_iri=base_iri),
        "@id": base_iri,
        "@type": str(OBS.WorkflowSession),
        str(OBS.sessionId): session_id,
        str(OBS.frames): {"@list": nodes},
    }
    content = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    )

    dataset = Dataset()
    observations_iri = URIRef(base_iri + "context/observations")
    dataset.graph(observations_iri).parse(
        data=content,
        format="json-ld",
    )

    return SessionContext(
        session_id=session_id,
        source_sha256=sha256(content.encode("utf-8")).hexdigest(),
        dataset=dataset,
        observations_iri=observations_iri,
        frame_iris=frame_iris,
    )


def entities_for_frame(
    context: SessionContext,
    frame_id: str,
) -> tuple[URIRef, ...]:
    """Returnează aparițiile cadrului, fără a stabili identitatea."""
    graph = context.observations
    entities = {
        entity
        for analysis in graph.objects(
            context.frame_iris[frame_id],
            OBS.observation,
        )
        for image in graph.objects(analysis, OBS.observation)
        for entity in graph.objects(image, OBS.entities)
        if isinstance(entity, URIRef)
    }
    return tuple(sorted(entities, key=str))