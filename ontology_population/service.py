"""Pregătește un batch și asociază grafurile candidate cu observațiile."""

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from urllib.parse import quote
from uuid import uuid4
from pydantic import TypeAdapter
from rdflib import Graph, Literal, Namespace, RDFS, URIRef

from interpretation.config import OBSERVATION_NAMESPACE
from session_context.characteristic_selection import (
    CharacteristicSelectionProposal,
    check_selection_proposal,
)
from session_context.comparison import characteristics_for_occurrence
from session_context.graph import entities_for_frame
from session_context.models import SessionContext
from interpretation.observations import ImageObservation
from session_context.identity import AbsoluteIRI
from .generation import GenerationStrategy
from .config import MAX_BATCH_SIZE, POPULATION_BASE_IRI
from .prompting import PROMPT_VERSION, SYSTEM_PROMPT

CTX = Namespace(OBSERVATION_NAMESPACE)

class PopulationError(ValueError):
    """Răspunsul nu respectă contractul batch-ului."""


@dataclass(frozen=True)
class PopulationObservation:
    analysis_id: str
    observation: dict[str, Any]
    occurrence_iris_by_source_id: dict[str, str]
    characteristic_iris_by_source_id: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class PopulationGraph:
    jsonld: dict[str, Any]
    entity_iris_by_source_id: dict[str, str]
    characteristic_selection: dict[str, Any] | None = None


@dataclass(frozen=True)
class PopulationBatchResult:
    graphs: dict[str, PopulationGraph]
    message_id: str
    model: str
    prompt_version: str
    ontology_turtle_sha256: str
    usage: dict[str, Any]
    context_provenance: dict[str, str]


_IRI_ADAPTER = TypeAdapter(AbsoluteIRI)


def _prepare_observation(
    item: PopulationObservation,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Pregătește observația și referințele fără modificarea intrării."""
    try:
        observation = ImageObservation.model_validate(
            item.observation
        )
    except ValueError as exc:
        raise PopulationError(
            f"Observație nevalidă pentru analiza {item.analysis_id}."
        ) from exc

    entity_ids = {
        entity.id
        for entity in observation.entities
    }

    if (
        set(item.occurrence_iris_by_source_id) != entity_ids
        or set(item.characteristic_iris_by_source_id) != entity_ids
    ):
        raise PopulationError(
            "Referințele trebuie să corespundă exact "
            "entităților observației."
        )

    references = {}

    for entity in observation.entities:
        characteristic_iris = (
            item.characteristic_iris_by_source_id[entity.id]
        )

        if not isinstance(characteristic_iris, (tuple, list)):
            raise PopulationError(
                "Referințele caracteristicilor trebuie "
                "transmise ca o listă sau un tuplu."
            )

        if len(characteristic_iris) != len(entity.characteristics):
            raise PopulationError(
                "Numărul referințelor nu corespunde "
                "caracteristicilor observate."
            )

        try:
            occurrence_iri = _IRI_ADAPTER.validate_python(
                item.occurrence_iris_by_source_id[entity.id]
            )
            checked_characteristics = [
                _IRI_ADAPTER.validate_python(iri)
                for iri in characteristic_iris
            ]

        except ValueError as exc:
            raise PopulationError(
                "Referințele sursă trebuie să fie IRI-uri absolute."
            ) from exc

        references[entity.id] = {
            "occurrence_iri": occurrence_iri,
            "characteristic_iris": checked_characteristics,
        }

    return observation.model_dump(mode="json"), references


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

def _check_bound_observations(
    observations: list[PopulationObservation],
    prepared: list[
        tuple[dict[str, Any], dict[str, dict[str, Any]]]
    ],
    context: SessionContext,
) -> None:
    """Verifică legătura dintre datele trimise și observațiile sursă."""
    graph = context.observations

    for item, (observation, references) in zip(
        observations,
        prepared,
        strict=True,
    ):
        frames = [
            frame_id
            for frame_id, frame_iri in context.frame_iris.items()
            for analysis in graph.objects(
                frame_iri, CTX.observation
            )
            if graph.value(
                analysis, CTX.analysisId, any=False
            ) == Literal(item.analysis_id)
        ]

        if len(frames) != 1:
            raise PopulationError(
                "Analiza nu aparține unui singur cadru al contextului."
            )

        expected = set(entities_for_frame(context, frames[0]))
        supplied = {
            URIRef(reference["occurrence_iri"])
            for reference in references.values()
        }

        if supplied != expected:
            raise PopulationError(
                "Aparițiile trimise nu corespund observației sursă."
            )

        for entity in observation["entities"]:
            reference = references[entity["id"]]
            occurrence = URIRef(reference["occurrence_iri"])

            label = graph.value(
                occurrence, RDFS.label, any=False
            )
            expected_uncertainty = (
                set()
                if entity["uncertain"] is None
                else {Literal(entity["uncertain"])}
            )

            if (
                label is None
                or str(label) != entity["name"]
                or set(graph.objects(occurrence, CTX.uncertain))
                != expected_uncertainty
            ):
                raise PopulationError(
                    "Datele apariției diferă de observația sursă."
                )

            sources = {
                characteristic.iri: characteristic
                for characteristic in characteristics_for_occurrence(
                    context, occurrence
                )
            }
            iris = tuple(
                URIRef(iri)
                for iri in reference["characteristic_iris"]
            )

            if set(iris) != set(sources):
                raise PopulationError(
                    "Referințele caracteristicilor nu corespund "
                    "apariției sursă."
                )

            for characteristic, iri in zip(
                entity["characteristics"],
                iris,
                strict=True,
            ):
                source = sources[iri]

                if (
                    characteristic["name"],
                    characteristic["value"],
                    characteristic["uncertain"],
                ) != (
                    source.name,
                    source.value,
                    source.uncertain,
                ):
                    raise PopulationError(
                        "Caracteristica trimisă diferă "
                        "de caracteristica sursă."
                    )


def _population_context(context: SessionContext) -> dict[str, str]:
    """Pregătește contextul fără metadatele voluminoase ale cererilor VLM."""
    observations = Graph()
    observations.bind("obs", CTX)

    for triple in context.observations:
        if triple[1] not in {CTX.parameters, CTX.usage}:
            observations.add(triple)

    return {
        "session_id": context.session_id,
        "observations_graph_iri": str(context.observations_iri),
        "identities_graph_iri": str(context.identities_iri),
        "observations_turtle": observations.serialize(format="turtle"),
        "identities_turtle": context.identities.serialize(format="turtle"),
    }


def _read_population_response(
    text: str,
    *,
    expected_graphs: set[str],
    expected_occurrences: set[str],
    context: SessionContext,
    ontology: Graph,
) -> tuple[
    dict[str, dict[str, Any]],
    CharacteristicSelectionProposal,
]:
    try:
        document = json.loads(
            text,
            object_pairs_hook=_unique_json_members,
            parse_constant=_reject_json_constant,
        )

        if (
            not isinstance(document, dict)
            or set(document)
            != {"graphs", "characteristic_selection"}
        ):
            raise PopulationError(
                "Răspunsul trebuie să conțină exact graphs "
                "și characteristic_selection."
            )

        graphs = _read_graphs(
            json.dumps(
                document["graphs"],
                ensure_ascii=False,
                allow_nan=False,
            ),
            expected_graphs,
        )

        selection = CharacteristicSelectionProposal.model_validate(
            document["characteristic_selection"]
        )
        check_selection_proposal(
            selection,
            context=context,
            expected_occurrences=expected_occurrences,
            ontology=ontology,
        )

    except ValueError as exc:
        raise PopulationError(
            f"Răspuns de interpretare nevalid: {exc}"
        ) from exc

    return graphs, selection


def populate_batch(
    observations: list[PopulationObservation],
    *,
    ontology_turtle: str,
    client: GenerationStrategy,
    context: SessionContext,
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

    prepared = [
        _prepare_observation(item)
        for item in observations
    ]

    used_source_iris = set()

    for _, references in prepared:
        for reference in references.values():
            source_iris = (
                reference["occurrence_iri"],
                *reference["characteristic_iris"],
            )

            for iri in source_iris:
                if iri in used_source_iris:
                    raise PopulationError(
                        "Un identificator sursă este reutilizat "
                        "pentru mai multe apariții sau caracteristici."
                    )

                used_source_iris.add(iri)

    _check_bound_observations(
        observations,
        prepared,
        context,
    )

    ontology = Graph().parse(
        data=ontology_turtle,
        format="turtle",
    )
    context_data = _population_context(context)

    run_iri = f"{POPULATION_BASE_IRI}{uuid4().hex}:"
    entries = []

    for item, (observation, references) in zip(
            observations,
            prepared,
            strict=True,
    ):
        graph_iri = run_iri + quote(item.analysis_id, safe="")
        instance_prefix = f"{graph_iri}:instance:"

        entity_iris = {
            entity["id"]: (
                f"{instance_prefix}source:"
                f"{quote(entity['id'], safe='')}"
            )
            for entity in observation["entities"]
        }

        entries.append({
            "analysis_id": item.analysis_id,
            "graph_iri": graph_iri,
            "instance_iri_prefix": instance_prefix,
            "entity_iris_by_source_id": entity_iris,
            "source_references_by_source_id": references,
            "observation": observation,
        })

    response = client.generate(
        system_prompt=SYSTEM_PROMPT,
        ontology_turtle=ontology_turtle,
        user_prompt=json.dumps(
            {
                "session_context": context_data,
                "observations": entries,
            },
            ensure_ascii=False,
            allow_nan=False,
        ),
    )
    expected_occurrences = {
        reference["occurrence_iri"]
        for entry in entries
        for reference in entry[
            "source_references_by_source_id"
        ].values()
    }

    documents, selection = _read_population_response(
        response.text,
        expected_graphs={
            entry["graph_iri"]
            for entry in entries
        },
        expected_occurrences=expected_occurrences,
        context=context,
        ontology=ontology,
    )

    selections_by_occurrence = {
        appearance.occurrence_iri: appearance
        for appearance in selection.appearances
    }

    return PopulationBatchResult(
        graphs={
            entry["analysis_id"]: PopulationGraph(
                jsonld=documents[entry["graph_iri"]],
                entity_iris_by_source_id=entry["entity_iris_by_source_id"],
                characteristic_selection=(
                    CharacteristicSelectionProposal(
                        appearances=tuple(
                            selections_by_occurrence[
                                reference["occurrence_iri"]
                            ]
                            for reference in entry[
                                "source_references_by_source_id"
                            ].values()
                        ),
                    ).model_dump(mode="json")
                ),
            )
            for entry in entries
        },
        message_id=response.message_id,
        model=response.model,
        prompt_version=PROMPT_VERSION,
        ontology_turtle_sha256=sha256(ontology_turtle.encode("utf-8")).hexdigest(),
        usage=response.usage,
        context_provenance={
            "session_id": context.session_id,
            "observations_sha256": context.source_sha256,
            "observations_turtle_sha256": sha256(
                context_data["observations_turtle"].encode("utf-8")
            ).hexdigest(),
            "identities_turtle_sha256": sha256(
                context_data["identities_turtle"].encode("utf-8")
            ).hexdigest(),
        },
    )