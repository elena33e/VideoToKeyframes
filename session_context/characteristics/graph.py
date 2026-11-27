"""Păstrarea propunerilor de selecție în contextul sesiunii."""

import json
from hashlib import sha256
from typing import Literal as LiteralType

from pydantic import BaseModel, ConfigDict
from rdflib import (
    Graph,
    Literal,
    Namespace,
    RDF,
    URIRef,
)
from rdflib.compare import to_isomorphic

from interpretation.config import OBSERVATION_NAMESPACE

from .selection import (
    CharacteristicSelectionProposal,
    Text,
    check_selection_proposal,
)
from ..graph import entities_for_frame
from ..identity.models import AbsoluteIRI
from ..models import SessionContext
from ..population_provenance import (
    PopulationProvenance as SelectionProvenance,
)


CTX = Namespace(OBSERVATION_NAMESPACE)
FORMAT_VERSION = "characteristic-selection-v1"


class CharacteristicSelectionRecord(BaseModel):
    """Înregistrare verificabilă; interpretarea rămâne propunere."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: LiteralType["characteristic-selection-v1"]
    provenance: SelectionProvenance
    observations_digest: Text
    ontology_digest: Text
    proposal: CharacteristicSelectionProposal


def _graph_digest(graph: Graph) -> str:
    """Amprentă independentă de ordinea triplelor și de ID-urile BNode."""
    return str(to_isomorphic(graph).graph_digest())


def _record_iri(
    context: SessionContext,
    content: str,
) -> URIRef:
    digest = sha256(content.encode("utf-8")).hexdigest()
    return URIRef(
        f"{context.observations_iri}/characteristic-selections/{digest}"
    )


def _check_record(
    context: SessionContext,
    data: CharacteristicSelectionRecord,
    ontology: Graph,
) -> None:
    source = data.provenance

    if (
        source.session_id != context.session_id
        or source.observations_sha256 != context.source_sha256
    ):
        raise ValueError(
            "Propunerea nu corespunde observațiilor sesiunii."
        )

    frame = context.frame_iris.get(source.frame_id)
    if frame is None:
        raise ValueError("Cadrul propunerii nu există în context.")

    analyses = set(context.observations.objects(
        frame, CTX.observation
    ))

    if len(analyses) != 1:
        raise ValueError("Cadrul trebuie să aibă o singură analiză.")

    analysis = next(iter(analyses))
    if (
        not isinstance(analysis, URIRef)
        or set(context.observations.objects(
            analysis, CTX.analysisId
        )) != {Literal(source.analysis_id)}
    ):
        raise ValueError(
            "Analiza propunerii nu corespunde cadrului sursă."
        )

    if data.observations_digest != _graph_digest(
        context.observations
    ):
        raise ValueError(
            "Observațiile diferă de cele ale înregistrării."
        )

    if data.ontology_digest != _graph_digest(ontology):
        raise ValueError(
            "Ontologia diferă de cea a înregistrării."
        )

    check_selection_proposal(
        data.proposal,
        context=context,
        expected_occurrences=entities_for_frame(
            context, source.frame_id
        ),
        ontology=ontology,
    )


def _selection_graph(
    context: SessionContext,
    record: URIRef,
    content: str,
    data: CharacteristicSelectionRecord,
) -> Graph:
    graph = Graph(identifier=record)
    source = data.provenance

    for predicate, value in (
        (RDF.type, CTX.CharacteristicSelectionProposal),
        (CTX.selectionStatus, Literal(data.proposal.status)),
        (CTX.sessionId, Literal(source.session_id)),
        (CTX.sourceSha256, Literal(source.observations_sha256)),
        (CTX.sourceFrame, context.frame_iris[source.frame_id]),
        (CTX.analysisId, Literal(source.analysis_id)),
        (CTX.populationGraph, URIRef(source.population_graph_iri)),
        (CTX.selectionData, Literal(content, datatype=RDF.JSON)),
    ):
        graph.add((record, predicate, value))

    for appearance in data.proposal.appearances:
        graph.add((
            record,
            CTX.occurrence,
            URIRef(appearance.occurrence_iri),
        ))

        for item in appearance.characteristics:
            graph.add((
                record,
                CTX.sourceCharacteristic,
                URIRef(item.source_characteristic_iri),
            ))

    return graph


def record_characteristic_selection(
    context: SessionContext,
    proposal: CharacteristicSelectionProposal,
    *,
    provenance: SelectionProvenance,
    ontology: Graph,
) -> URIRef:
    """Verifică și înregistrează o propunere pentru un cadru.

    Verificarea privește structura și sursele.
    Nu acceptă interpretarea semantică sau identitatea obiectelor.
    """
    # Reconstruim din date pentru a reverifica și modelele primite.
    data = CharacteristicSelectionRecord.model_validate({
        "format_version": FORMAT_VERSION,
        "provenance": provenance.model_dump(mode="json"),
        "observations_digest": _graph_digest(context.observations),
        "ontology_digest": _graph_digest(ontology),
        "proposal": proposal.model_dump(mode="json"),
    })

    _check_record(context, data, ontology)

    content = json.dumps(
        data.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    record = _record_iri(context, content)
    prepared = _selection_graph(context, record, content, data)

    # Dataset-ul este accesat pentru scriere numai după validare.
    target = context.dataset.graph(record)
    if len(target) and set(target) != set(prepared):
        raise ValueError(
            "Înregistrarea existentă conține date incompatibile."
        )

    for triple in prepared:
        target.add(triple)

    return record


def read_characteristic_selection(
    context: SessionContext,
    record: str | URIRef,
    *,
    ontology: Graph,
) -> CharacteristicSelectionRecord:
    """Citește și reverifică o înregistrare, inclusiv după încărcare."""
    record = URIRef(record)
    graph = context.dataset.graph(record)
    values = set(graph.objects(record, CTX.selectionData))

    if len(values) != 1:
        raise ValueError(
            "Propunerea lipsește sau conține date repetate."
        )

    value = next(iter(values))
    if (
        not isinstance(value, Literal)
        or value.datatype != RDF.JSON
    ):
        raise ValueError("Datele propunerii trebuie să fie JSON.")

    content = str(value)
    if record != _record_iri(context, content):
        raise ValueError(
            "Conținutul nu corespunde identificatorului propunerii."
        )

    data = CharacteristicSelectionRecord.model_validate_json(content)
    _check_record(context, data, ontology)

    expected = _selection_graph(context, record, content, data)
    if set(graph) != set(expected):
        raise ValueError(
            "Rezumatul RDF nu corespunde datelor propunerii."
        )

    return data


def read_characteristic_selections(
    context: SessionContext,
    *,
    ontology: Graph,
) -> tuple[
    dict[URIRef, CharacteristicSelectionRecord],
    dict[URIRef, str],
]:
    """Citește înregistrările create de mecanismul de selecție.

    Returnează separat înregistrările verificate și problemele de citire.
    Ordinea este pentru afișare, fără prioritate semantică sau temporală.
    """
    prefix = (
        f"{context.observations_iri}/characteristic-selections/"
    )
    candidates = sorted(
        {
            graph.identifier
            for graph in context.dataset.graphs()
            if isinstance(graph.identifier, URIRef)
            and str(graph.identifier).startswith(prefix)
        },
        key=str,
    )

    records = {}
    issues = {}

    for record in candidates:
        try:
            records[record] = read_characteristic_selection(
                context,
                record,
                ontology=ontology,
            )
        except ValueError as exc:
            issues[record] = str(exc)

    return records, issues