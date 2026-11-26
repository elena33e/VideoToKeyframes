"""Salvarea și reîncărcarea contextului unei sesiuni."""

import re
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import TypeVar
from urllib.parse import quote

from rdflib import DCTERMS, RDF, Dataset, Graph, Literal, Namespace, URIRef
from rdflib.term import Node

from interpretation.config import OBSERVATION_NAMESPACE, SESSION_BASE_IRI

from .identity import IdentityDecision, TrackedObject
from .identity_graph import record_identity_decision
from .models import SessionContext


CTX = Namespace(OBSERVATION_NAMESPACE)
METADATA_IRI = URIRef("urn:videotokeyframes:context:metadata")
SNAPSHOT_IRI = URIRef("urn:videotokeyframes:context:snapshot")
FORMAT_VERSION = "1"
T = TypeVar("T", bound=Node)


def _one(
    graph: Graph, subject: Node, predicate: URIRef, kind: type[T]
) -> T:
    values = set(graph.objects(subject, predicate))
    if len(values) != 1:
        raise ValueError(f"Câmp absent sau repetat: {predicate}.")

    value = next(iter(values))
    if not isinstance(value, kind):
        raise ValueError(f"Tip RDF incompatibil: {predicate}.")

    return value


def _validate_identities(context: SessionContext) -> None:
    """Reconstituie în memorie deciziile, folosind validările existente."""
    graph = context.identities
    objects = {}

    for node in graph.subjects(RDF.type, CTX.TrackedObject):
        objects[node] = TrackedObject.model_validate({
            "session_id": str(_one(graph, node, CTX.sessionId, Literal)),
            "object_id": str(_one(graph, node, CTX.objectId, Literal)),
            "created_at": str(_one(graph, node, DCTERMS.created, Literal)),
        })

    scratch = Dataset()
    for triple in context.observations:
        scratch.graph(context.observations_iri).add(triple)

    rebuilt = replace(context, dataset=scratch)

    for node in sorted(
        set(graph.subjects(RDF.type, CTX.IdentityDecision)), key=str
    ):
        outcome = str(_one(graph, node, CTX.identityOutcome, Literal))
        tracked = None

        if outcome == "same_object":
            target = _one(graph, node, CTX.assignedObject, URIRef)
            tracked = objects.get(target)
            if tracked is None:
                raise ValueError("Decizia indică un obiect necunoscut.")
        elif list(graph.objects(node, CTX.assignedObject)):
            raise ValueError("Decizia nu permite un obiect asociat.")

        decision = IdentityDecision.model_validate({
            "session_id": str(_one(graph, node, CTX.sessionId, Literal)),
            "decision_id": str(_one(graph, node, CTX.decisionId, Literal)),
            "left_occurrence_iri": str(
                _one(graph, node, CTX.leftOccurrence, URIRef)
            ),
            "right_occurrence_iri": str(
                _one(graph, node, CTX.rightOccurrence, URIRef)
            ),
            "outcome": outcome,
            "object_id": tracked.object_id if tracked is not None else None,
            "decided_by": str(_one(graph, node, CTX.decidedBy, Literal)),
            "justification": str(
                _one(graph, node, CTX.justification, Literal)
            ),
            "created_at": str(_one(graph, node, DCTERMS.created, Literal)),
        })

        record_identity_decision(rebuilt, decision, new_object=tracked)

    if set(rebuilt.identities) != set(graph):
        raise ValueError(
            "Graful de identitate conține date incompatibile "
            "sau asocieri fără o decizie validă."
        )


def _restore(dataset: Dataset) -> SessionContext:
    metadata = dataset.graph(METADATA_IRI)

    def field(predicate: URIRef, kind: type[T]) -> T:
        return _one(metadata, SNAPSHOT_IRI, predicate, kind)

    if field(RDF.type, URIRef) != CTX.SessionContextSnapshot:
        raise ValueError("Fișierul nu este un context de sesiune.")

    if field(CTX.contextFormatVersion, Literal) != Literal(FORMAT_VERSION):
        raise ValueError("Versiune de context nesuportată.")

    session_id = str(field(CTX.sessionId, Literal))
    source_sha256 = str(field(CTX.sourceSha256, Literal))

    if (
        not session_id.strip()
        or not re.fullmatch(r"[0-9a-f]{64}", source_sha256)
    ):
        raise ValueError("Metadatele contextului sunt invalide.")

    base = SESSION_BASE_IRI + quote(session_id, safe="") + "/"
    observations_iri = field(CTX.observationsGraph, URIRef)
    identities_iri = field(CTX.identitiesGraph, URIRef)

    if (
        observations_iri != URIRef(base + "context/observations")
        or identities_iri != URIRef(base + "context/identities")
    ):
        raise ValueError("Grafurile nu corespund sesiunii.")

    graph = dataset.graph(observations_iri)
    root = URIRef(base)

    if (
        (root, RDF.type, CTX.WorkflowSession) not in graph
        or _one(graph, root, CTX.sessionId, Literal) != Literal(session_id)
    ):
        raise ValueError("Lipsesc observațiile sesiunii.")

    head = _one(graph, root, CTX.frames, Node)
    frames = list(graph.items(head))

    if not frames or len(set(frames)) != len(frames):
        raise ValueError("Lista cadrelor este goală sau conține duplicate.")

    if set(frames) != set(graph.subjects(RDF.type, CTX.KeyframeState)):
        raise ValueError("Lista cadrelor nu corespunde observațiilor.")

    frame_iris = {}

    for frame in frames:
        frame_id = str(_one(graph, frame, CTX.frameId, Literal))

        if (
            not isinstance(frame, URIRef)
            or not frame_id.strip()
            or frame_id in frame_iris
            or frame != URIRef(base + "frames/" + quote(frame_id, safe=""))
        ):
            raise ValueError("Identificator de cadru invalid sau duplicat.")

        _one(graph, frame, CTX.observation, URIRef)
        frame_iris[frame_id] = frame

    context = SessionContext(
        session_id=session_id,
        source_sha256=source_sha256,
        dataset=dataset,
        observations_iri=observations_iri,
        identities_iri=identities_iri,
        frame_iris=frame_iris,
    )

    _validate_identities(context)
    return context


def save_session_context(
    context: SessionContext, destination: str | Path
) -> Path:
    """Salvează un snapshot TriG; directorul trebuie să existe."""
    destination = Path(destination).expanduser().resolve()

    if destination.suffix.lower() != ".trig":
        raise ValueError("Folosește extensia .trig.")

    # Lucrăm pe o copie; metadatele nu modifică dataset-ul din memorie.
    snapshot = Dataset()

    for subject, predicate, value, graph in context.dataset.quads(
        (None, None, None, None)
    ):
        if graph != METADATA_IRI:
            snapshot.add((subject, predicate, value, graph))

    metadata = snapshot.graph(METADATA_IRI)

    for predicate, value in (
        (RDF.type, CTX.SessionContextSnapshot),
        (CTX.contextFormatVersion, Literal(FORMAT_VERSION)),
        (CTX.sessionId, Literal(context.session_id)),
        (CTX.sourceSha256, Literal(context.source_sha256)),
        (CTX.observationsGraph, context.observations_iri),
        (CTX.identitiesGraph, context.identities_iri),
    ):
        metadata.add((SNAPSHOT_IRI, predicate, value))

    restored = _restore(snapshot)

    if restored.frame_iris != context.frame_iris:
        raise ValueError("Indexul cadrelor nu corespunde dataset-ului.")

    content = snapshot.serialize(format="trig")
    temporary = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=".session_context_",
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


def load_session_context(
    source: str | Path,
    *,
    expected_session_id: str | None = None,
    expected_source_sha256: str | None = None,
) -> SessionContext:
    """Reîncarcă identificatorii existenți, fără a genera alții."""
    source = Path(source).expanduser().resolve()

    if source.suffix.lower() != ".trig":
        raise ValueError("Folosește extensia .trig.")

    dataset = Dataset()
    dataset.parse(data=source.read_text(encoding="utf-8"), format="trig")
    context = _restore(dataset)

    if (
        expected_session_id is not None
        and context.session_id != expected_session_id
    ):
        raise ValueError("Contextul aparține altei sesiuni.")

    if (
        expected_source_sha256 is not None
        and context.source_sha256 != expected_source_sha256
    ):
        raise ValueError("Contextul provine din alte observații.")

    return context