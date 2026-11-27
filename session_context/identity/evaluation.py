"""Înregistrarea evaluărilor în contextul sesiunii."""

import json
from collections.abc import Mapping
from dataclasses import (
    asdict,
    is_dataclass,
)
from hashlib import sha256

from pydantic import BaseModel
from rdflib import (
    Graph,
    Literal,
    Namespace,
    RDF,
    URIRef,
)
from rdflib.compare import to_isomorphic

from interpretation.config import OBSERVATION_NAMESPACE

from .criteria import IdentityCriteria
from .assessment import (
    IdentityAssessment,
    assess_frame_identity,
)
from ..models import SessionContext
from ..type_alignment import SessionTypeMapper


CTX = Namespace(OBSERVATION_NAMESPACE)
FORMAT_VERSION = "identity-evaluation-v1"


def _graph_digest(graph: Graph) -> str:
    return str(to_isomorphic(graph).graph_digest())


def _json_default(value):
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")

    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)

    raise TypeError(
        f"Tip nesuportat la serializare: {type(value).__name__}."
    )


def _record_iri(
    context: SessionContext,
    content: str,
) -> URIRef:
    digest = sha256(content.encode("utf-8")).hexdigest()

    return URIRef(
        f"{context.observations_iri}/identity-evaluations/{digest}"
    )


def _evaluation_graph(
    record: URIRef,
    content: str,
    data: dict,
) -> Graph:
    graph = Graph(identifier=record)

    for predicate, value in (
        (RDF.type, CTX.IdentityEvaluation),
        (CTX.sessionId, Literal(data["session_id"])),
        (CTX.sourceSha256, Literal(data["observations_sha256"])),
        (
            CTX.referenceFrame,
            URIRef(data["reference_frame_iri"]),
        ),
        (
            CTX.currentFrame,
            URIRef(data["current_frame_iri"]),
        ),
        (
            CTX.evaluationData,
            Literal(content, datatype=RDF.JSON),
        ),
    ):
        graph.add((record, predicate, value))

    for index, assessment in enumerate(data["assessments"]):
        node = URIRef(f"{record}/results/{index}")
        selection = assessment["selection"]

        graph.add((record, CTX.assessments, node))
        graph.add((node, RDF.type, CTX.IdentityAssessment))
        graph.add((
            node,
            CTX.occurrence,
            URIRef(selection["occurrence_iri"]),
        ))
        graph.add((
            node,
            CTX.assessmentAction,
            Literal(assessment["action"]),
        ))

        for reason in assessment["reasons"]:
            graph.add((
                node,
                CTX.assessmentReason,
                Literal(reason),
            ))

        for field, predicate in (
            ("candidates", CTX.candidateIdentity),
            ("excluded_candidates", CTX.excludedCandidateIdentity),
        ):
            for candidate in selection[field]:
                graph.add((
                    node,
                    predicate,
                    URIRef(candidate["key"]),
                ))

    return graph


def record_frame_identity_evaluation(
    context: SessionContext,
    reference_frame_id: str,
    current_frame_id: str,
    *,
    mapper: SessionTypeMapper,
    criteria_by_occurrence: Mapping[URIRef, IdentityCriteria],
    language: str | None = None,
) -> tuple[URIRef, tuple[IdentityAssessment, ...]]:
    """Evaluează și înregistrează rezultatele într-un graf separat.

    Nu modifică observațiile sau identitățile acceptate.
    Repetarea aceleiași evaluări nu creează o copie nouă.
    """
    assessments = assess_frame_identity(
        context,
        reference_frame_id,
        current_frame_id,
        mapper=mapper,
        criteria_by_occurrence=criteria_by_occurrence,
        language=language,
    )

    data = {
        "format_version": FORMAT_VERSION,
        "session_id": context.session_id,
        "observations_sha256": context.source_sha256,
        "observations_digest": _graph_digest(context.observations),
        "identities_digest": _graph_digest(context.identities),
        "reference_frame_iri": str(
            context.frame_iris[reference_frame_id]
        ),
        "current_frame_iri": str(
            context.frame_iris[current_frame_id]
        ),
        "criteria_by_occurrence": {
            str(occurrence): criteria
            for occurrence, criteria in criteria_by_occurrence.items()
        },
        "language": language,
        "assessments": assessments,
    }

    content = json.dumps(
        data,
        default=_json_default,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    serialized = json.loads(content)

    record = _record_iri(context, content)
    prepared = _evaluation_graph(record, content, serialized)
    target = context.dataset.graph(record)

    if len(target) and set(target) != set(prepared):
        raise ValueError(
            "Înregistrarea existentă conține date incompatibile."
        )

    for triple in prepared:
        target.add(triple)

    return record, assessments


def read_identity_evaluation(
    context: SessionContext,
    record: str | URIRef,
) -> dict:
    """Citește o evaluare înregistrată, inclusiv una istorică."""
    record = URIRef(record)
    graph = context.dataset.graph(record)

    values = set(graph.objects(record, CTX.evaluationData))

    if len(values) != 1:
        raise ValueError(
            "Evaluarea lipsește sau conține date repetate."
        )

    content = next(iter(values))

    if (
        not isinstance(content, Literal)
        or content.datatype != RDF.JSON
    ):
        raise ValueError("Datele evaluării trebuie să fie JSON.")

    text = str(content)

    if record != _record_iri(context, text):
        raise ValueError(
            "Conținutul nu corespunde identificatorului evaluării."
        )

    try:
        data = json.loads(text)

        if (
            data["format_version"] != FORMAT_VERSION
            or data["session_id"] != context.session_id
            or data["observations_sha256"] != context.source_sha256
        ):
            raise ValueError(
                "Evaluarea nu corespunde contextului."
            )

        expected = _evaluation_graph(record, text, data)

    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(
            "Structură de evaluare incompatibilă."
        ) from exc

    if set(graph) != set(expected):
        raise ValueError(
            "Rezumatul RDF nu corespunde detaliilor evaluării."
        )

    return data


def identity_evaluation_is_current(
    context: SessionContext,
    record: str | URIRef,
) -> bool:
    """Verifică dacă observațiile și deciziile sunt încă aceleași."""
    data = read_identity_evaluation(context, record)

    return (
        data["observations_digest"]
        == _graph_digest(context.observations)
        and data["identities_digest"]
        == _graph_digest(context.identities)
    )