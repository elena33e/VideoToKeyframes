from copy import deepcopy
from urllib.parse import urlsplit
from .config import OBSERVATION_NAMESPACE


_CONTEXT = {
    "@version": 1.1,

    "obs": OBSERVATION_NAMESPACE,
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "dcterms": "http://purl.org/dc/terms/",
    "xsd": "http://www.w3.org/2001/XMLSchema#",

    # Aliasuri: păstrăm nume de câmpuri ușor de folosit în Python.
    "id": "@id",
    "type": "@type",

    # Tipurile de informații reprezentate.
    "FrameObservation": "obs:FrameObservation",
    "ImageObservation": "obs:ImageObservation",
    "EntityObservation": "obs:EntityObservation",
    "RelationObservation": "obs:RelationObservation",
    "ActionObservation": "obs:ActionObservation",

    # Descrierea imaginii.
    "observation": "obs:observation",
    "description": "dcterms:description",
    "entities": {
        "@id": "obs:entities",
        "@container": "@set",
    },
    "relations": {
        "@id": "obs:relations",
        "@container": "@set",
    },
    "actions": {
        "@id": "obs:actions",
        "@container": "@set",
    },
    "visible_text": {
        "@id": "obs:visibleText",
        "@container": "@set",
    },
    "uncertainties": {
        "@id": "obs:uncertainties",
        "@container": "@set",
    },

    # Entitățile observate.
    "name": "rdfs:label",
    "features": {
        "@id": "obs:features",
        "@container": "@set",
    },
    "location": "obs:location",
    "visibility": "obs:visibility",

    # Relațiile dintre entități.
    "subject_id": {
        "@id": "obs:subject",
        "@type": "@id",
    },
    "predicate": "obs:relationLabel",
    "object_id": {
        "@id": "obs:object",
        "@type": "@id",
    },

    # Acțiunile observate.
    "entity_ids": {
        "@id": "obs:participants",
        "@type": "@id",
        "@container": "@set",
    },
    "uncertain": "obs:uncertain",

    # Proveniența și metadatele rezultatului.
    "analysis_id": "obs:analysisId",
    "schema_version": "obs:schemaVersion",
    "frame_id": "obs:frameId",
    "scene_index": {
        "@id": "obs:sceneIndex",
        "@type": "xsd:integer",
    },
    "image_sha256": "obs:imageSha256",
    "created_at": {
        "@id": "dcterms:created",
        "@type": "xsd:dateTime",
    },
    "prompt_version": "obs:promptVersion",
    "requested_model": "obs:requestedModel",
    "resolved_model": "obs:resolvedModel",
    "provider": "obs:provider",
    "api_request_id": "obs:apiRequestId",
    "elapsed_seconds": {
        "@id": "obs:elapsedSeconds",
        "@type": "xsd:double",
    },

    # Păstrăm aceste dicționare ca valori JSON integrale.
    "parameters": {
        "@id": "obs:parameters",
        "@type": "@json",
    },
    "usage": {
        "@id": "obs:usage",
        "@type": "@json",
    },
}


def build_observation_context(*, base_iri: str) -> dict:
    """Returnează un context independent pentru analiza unui cadru."""
    parts = urlsplit(base_iri)

    if (
        parts.scheme not in {"http", "https"}
        or not parts.netloc
        or parts.query
        or parts.fragment
        or not base_iri.endswith("/")
    ):
        raise ValueError(
            "base_iri trebuie să fie un IRI HTTP(S) absolut, "
            "fără query sau fragment și terminat cu '/'."
        )

    context = deepcopy(_CONTEXT)
    context["@base"] = base_iri
    return context