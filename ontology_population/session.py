"""Popularea observațiilor selectate dintr-un export de sesiune."""

from collections.abc import Iterator
from dataclasses import asdict
from typing import Any
from urllib.parse import unquote

from interpretation.observations import ImageObservation
from ontology.reader import OntologySource

from .config import MAX_BATCH_SIZE
from .generation import GenerationStrategy
from .service import PopulationObservation, populate_batch

def _population_observation(saved: dict) -> PopulationObservation:
    source = saved["observation"]
    data = {field: source[field] for field in ImageObservation.model_fields}

    ids = {
        entity["id"]: unquote(entity["id"].rsplit("/", 1)[-1])
        for entity in data["entities"]
    }
    data["entities"] = [
        {
            **{key: value for key, value in entity.items() if key != "type"},
            "id": ids[entity["id"]],
        }
        for entity in data["entities"]
    ]
    data["relations"] = [
        {
            "subject_id": ids[relation["subject_id"]],
            "predicate": relation["predicate"],
            "object_id": ids[relation["object_id"]],
            "uncertain": relation.get("uncertain"),
        }
        for relation in data["relations"]
    ]
    data["actions"] = [
        {
            "description": action["description"],
            "entity_ids": [ids[entity_id] for entity_id in action["entity_ids"]],
            "uncertain": action["uncertain"],
        }
        for action in data["actions"]
    ]

    observation = ImageObservation.model_validate(data)
    return PopulationObservation(
        analysis_id=saved["analysis_id"],
        observation=observation.model_dump(mode="json"),
    )

def iter_population_reports(
    session: dict[str, Any],
    *,
    ontology_source: OntologySource,
    client: GenerationStrategy,
    provider: str,
    requested_model: str,
    batch_size: int = MAX_BATCH_SIZE,
    offset: int = 0,
) -> Iterator[dict[str, Any]]:
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError(f"Grupul trebuie să aibă între 1 și {MAX_BATCH_SIZE} cadre.")
    if offset < 0:
        raise ValueError("Offsetul trebuie să fie nenegativ.")

    selected = [
        frame for frame in session["frames"]
        if frame["selected"]
        and frame["description_status"] == "completed"
        and frame["observation"] is not None
    ][offset:]
    if not selected:
        raise ValueError("Nu există observații selectate și finalizate la offsetul cerut.")

    analysis_ids = [frame["observation"]["analysis_id"] for frame in selected]
    if len(analysis_ids) != len(set(analysis_ids)):
        raise ValueError("Sesiunea conține ID-uri de analiză duplicate.")

    ontology_turtle = ontology_source.graph.serialize(format="turtle")
    paths = {
        frame["frame_id"]: frame["image_path"]
        for frame in session.get("imported_frames", [])
    }

    for start in range(0, len(selected), batch_size):
        batch = selected[start:start + batch_size]
        observations = [_population_observation(frame["observation"]) for frame in batch]
        result = populate_batch(observations, ontology_turtle=ontology_turtle, client=client)
        yield {
            "ontology_source_sha256": ontology_source.source_sha256,
            "provider": provider,
            "requested_model": requested_model,
            "sources": {
                observation.analysis_id: {
                    "frame_id": frame["frame_id"],
                    "image_path": paths.get(frame["frame_id"]),
                    "image_sha256": frame["observation"]["image_sha256"],
                }
                for observation, frame in zip(observations, batch, strict=True)
            },
            **asdict(result),
        }

