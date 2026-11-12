"""Pregătește un batch și asociază grafurile candidate cu observațiile."""

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from .generation import GenerationStrategy
from .config import MAX_BATCH_SIZE, POPULATION_BASE_IRI
from .prompting import PROMPT_VERSION, SYSTEM_PROMPT


class PopulationError(ValueError):
    """Răspunsul nu respectă contractul batch-ului."""


@dataclass(frozen=True)
class PopulationObservation:
    analysis_id: str
    observation: dict[str, Any]


@dataclass(frozen=True)
class PopulationGraph:
    jsonld: dict[str, Any]
    entity_iris_by_source_id: dict[str, str]


@dataclass(frozen=True)
class PopulationBatchResult:
    graphs: dict[str, PopulationGraph]
    message_id: str
    model: str
    prompt_version: str
    ontology_turtle_sha256: str
    usage: dict[str, Any]


def _unique_json_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Cheie JSON duplicată: {key!r}.")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Valoare JSON nevalidă: {value}.")


def _read_graphs(
    text: str,
    expected_iris: set[str],
) -> dict[str, dict[str, Any]]:
    try:
        document = json.loads(
            text,
            object_pairs_hook=_unique_json_members,
            parse_constant=_reject_json_constant,
        )
    except ValueError as exc:
        raise PopulationError(f"Modelul a returnat JSON nevalid. {exc}") from exc

    if not isinstance(document, dict) or set(document) - {"@context", "@graph"}:
        raise PopulationError(
            "Se așteaptă un obiect JSON-LD cu @graph și @context opțional."
        )

    context = document.get("@context", {})
    if not isinstance(context, dict) or "" in context or "@import" in context:
        raise PopulationError(
            "@context trebuie să fie un obiect local cu termeni valizi."
        )

    items = document.get("@graph")
    if not isinstance(items, list):
        raise PopulationError("@graph trebuie să fie o listă de grafuri numite.")

    graphs = {}
    for item in items:
        if not isinstance(item, dict) or set(item) != {"@id", "@graph"}:
            raise PopulationError("Fiecare graf numit trebuie să aibă @id și @graph.")

        graph_iri = item["@id"]
        nodes = item["@graph"]
        if not isinstance(graph_iri, str) or graph_iri not in expected_iris:
            raise PopulationError("Răspunsul conține un IRI de graf necunoscut.")
        if graph_iri in graphs:
            raise PopulationError("Răspunsul conține un IRI de graf duplicat.")
        if not isinstance(nodes, list) or not all(isinstance(node, dict) for node in nodes):
            raise PopulationError("Nodurile unui graf trebuie să fie o listă de obiecte.")

        graphs[graph_iri] = {"@context": context, **item}

    if set(graphs) != expected_iris:
        raise PopulationError("Din răspuns lipsesc grafuri cerute.")

    return graphs


def populate_batch(
    observations: list[PopulationObservation],
    *,
    ontology_turtle: str,
    client: GenerationStrategy,
) -> PopulationBatchResult:
    if not 1 <= len(observations) <= MAX_BATCH_SIZE:
        raise ValueError(
            f"Batch-ul trebuie să conțină între 1 și {MAX_BATCH_SIZE} observații."
        )
    if not ontology_turtle.strip():
        raise ValueError("Ontologia Turtle este goală.")

    analysis_ids = [item.analysis_id for item in observations]
    if any(not analysis_id.strip() for analysis_id in analysis_ids):
        raise ValueError("Fiecare observație trebuie să aibă un analysis_id.")
    if len(set(analysis_ids)) != len(analysis_ids):
        raise ValueError("Batch-ul conține analysis_id duplicate.")

    run_iri = f"{POPULATION_BASE_IRI}{uuid4().hex}:"
    entries = []
    for item in observations:
        graph_iri = run_iri + quote(item.analysis_id, safe="")
        instance_prefix = f"{graph_iri}:instance:"
        entity_iris = {
            entity["id"]: f"{instance_prefix}source:{quote(entity['id'], safe='')}"
            for entity in item.observation.get("entities", [])
        }
        entries.append({
            "analysis_id": item.analysis_id,
            "graph_iri": graph_iri,
            "instance_iri_prefix": instance_prefix,
            "entity_iris_by_source_id": entity_iris,
            "observation": item.observation,
        })

    response = client.generate(
        system_prompt=SYSTEM_PROMPT,
        ontology_turtle=ontology_turtle,
        user_prompt=json.dumps(
            {"observations": entries},
            ensure_ascii=False,
            allow_nan=False,
        ),
    )
    documents = _read_graphs(
        response.text,
        {entry["graph_iri"] for entry in entries},
    )

    return PopulationBatchResult(
        graphs={
            entry["analysis_id"]: PopulationGraph(
                jsonld=documents[entry["graph_iri"]],
                entity_iris_by_source_id=entry["entity_iris_by_source_id"],
            )
            for entry in entries
        },
        message_id=response.message_id,
        model=response.model,
        prompt_version=PROMPT_VERSION,
        ontology_turtle_sha256=sha256(ontology_turtle.encode("utf-8")).hexdigest(),
        usage=response.usage,
    )