"""Înregistrarea deciziilor manuale în graful de identitate."""

from rdflib import DCTERMS, RDF, XSD, Graph, Literal, Namespace, URIRef
from rdflib.term import Node

from interpretation.config import OBSERVATION_NAMESPACE

from .identity import IdentityDecision, TrackedObject
from .models import SessionContext


CTX = Namespace(OBSERVATION_NAMESPACE)
Triple = tuple[URIRef, URIRef, Node]


def _node(
    context: SessionContext,
    kind: str,
    identifier: str,
) -> URIRef:
    return URIRef(
        f"{context.identities_iri}/{kind}/{identifier}"
    )


def _require_occurrence(
    context: SessionContext,
    occurrence: URIRef,
) -> None:
    graph = context.observations

    if (occurrence, RDF.type, CTX.EntityObservation) not in graph:
        raise ValueError(
            "Apariția nu există în observațiile sesiunii."
        )

    frames = {
        frame
        for image in graph.subjects(CTX.entities, occurrence)
        for analysis in graph.subjects(CTX.observation, image)
        for frame in graph.subjects(CTX.observation, analysis)
        if frame in context.frame_iris.values()
    }

    if len(frames) != 1:
        raise ValueError(
            "Apariția trebuie să aparțină unui singur cadru al sesiunii."
        )


def _check_subject(
    graph: Graph,
    node: URIRef,
    triples: set[Triple],
) -> None:
    existing = set(graph.triples((node, None, None)))

    if existing and existing != triples:
        raise ValueError(
            "Identificatorul este folosit pentru altă înregistrare."
        )


def _assigned_object(
    context: SessionContext,
    occurrence: URIRef,
) -> URIRef | None:
    graph = context.identities
    targets = set(
        graph.objects(occurrence, CTX.associatedObject)
    )

    if not targets:
        return None

    if len(targets) != 1:
        raise ValueError(
            "Apariția are mai multe identități active."
        )

    target = next(iter(targets))

    if (
        not isinstance(target, URIRef)
        or (target, RDF.type, CTX.TrackedObject) not in graph
        or (
            target,
            CTX.sessionId,
            Literal(context.session_id),
        ) not in graph
    ):
        raise ValueError(
            "Asocierea indică un obiect urmărit invalid."
        )

    return target


def object_for_occurrence(
    context: SessionContext,
    occurrence_iri: str | URIRef,
) -> URIRef | None:
    occurrence = URIRef(occurrence_iri)
    _require_occurrence(context, occurrence)

    return _assigned_object(context, occurrence)


def record_identity_decision(
    context: SessionContext,
    decision: IdentityDecision,
    *,
    new_object: TrackedObject | None = None,
) -> URIRef:
    if decision.session_id != context.session_id:
        raise ValueError(
            "Decizia aparține altei sesiuni."
        )

    if new_object is not None and (
        decision.outcome != "same_object"
        or new_object.session_id != context.session_id
        or new_object.object_id != decision.object_id
    ):
        raise ValueError(
            "Obiectul nou este incompatibil cu decizia."
        )

    left = URIRef(decision.left_occurrence_iri)
    right = URIRef(decision.right_occurrence_iri)

    _require_occurrence(context, left)
    _require_occurrence(context, right)

    graph = context.identities
    decision_iri = _node(
        context, "decisions", decision.decision_id
    )

    properties: dict[URIRef, Node] = {
        RDF.type: CTX.IdentityDecision,
        CTX.sessionId: Literal(decision.session_id),
        CTX.decisionId: Literal(decision.decision_id),
        CTX.leftOccurrence: left,
        CTX.rightOccurrence: right,
        CTX.identityOutcome: Literal(decision.outcome),
        CTX.decidedBy: Literal(decision.decided_by),
        CTX.justification: Literal(decision.justification),
        DCTERMS.created: Literal(
            decision.created_at,
            datatype=XSD.dateTime,
        ),
    }

    pending: set[Triple] = set()

    left_object = _assigned_object(context, left)
    right_object = _assigned_object(context, right)

    if decision.outcome == "same_object":
        if decision.object_id is None:
            raise ValueError(
                "Lipsește identificatorul obiectului urmărit."
            )

        target = _node(
            context, "objects", decision.object_id
        )

        if new_object is not None:
            object_properties: dict[URIRef, Node] = {
                RDF.type: CTX.TrackedObject,
                CTX.sessionId: Literal(new_object.session_id),
                CTX.objectId: Literal(new_object.object_id),
                DCTERMS.created: Literal(
                    new_object.created_at,
                    datatype=XSD.dateTime,
                ),
            }

            object_triples = {
                (target, predicate, value)
                for predicate, value in object_properties.items()
            }

            _check_subject(
                graph, target, object_triples
            )
            pending.update(object_triples)

        elif (
            (target, RDF.type, CTX.TrackedObject) not in graph
            or (
                target,
                CTX.sessionId,
                Literal(context.session_id),
            ) not in graph
            or (
                target,
                CTX.objectId,
                Literal(decision.object_id),
            ) not in graph
        ):
            raise ValueError(
                "Obiectul urmărit nu există în această sesiune."
            )

        if any(
            assigned is not None and assigned != target
            for assigned in (left_object, right_object)
        ):
            raise ValueError(
                "O apariție este deja asociată altui obiect urmărit."
            )

        members = set(
            graph.subjects(CTX.associatedObject, target)
        ) | {left, right}

        for rejected in graph.subjects(
            CTX.identityOutcome,
            Literal("different_objects"),
        ):
            pair = {
                graph.value(rejected, CTX.leftOccurrence),
                graph.value(rejected, CTX.rightOccurrence),
            }

            if pair <= members:
                raise ValueError(
                    "Asocierea contrazice o decizie de obiecte diferite."
                )

        properties[CTX.assignedObject] = target

        pending.update({
            (left, CTX.associatedObject, target),
            (right, CTX.associatedObject, target),
        })

    elif (
        decision.outcome == "different_objects"
        and left_object is not None
        and left_object == right_object
    ):
        raise ValueError(
            "Aparițiile sunt deja asociate aceluiași obiect."
        )

    decision_triples = {
        (decision_iri, predicate, value)
        for predicate, value in properties.items()
    }

    _check_subject(
        graph, decision_iri, decision_triples
    )
    pending.update(decision_triples)

    # Adăugăm triplele după verificarea tuturor condițiilor.
    for triple in pending:
        graph.add(triple)

    return decision_iri