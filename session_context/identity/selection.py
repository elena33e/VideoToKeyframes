"""Gruparea candidaților și aplicarea deciziilor deja înregistrate."""

from collections.abc import Mapping
from dataclasses import dataclass

from rdflib import RDF, Literal, URIRef

from session_context.graph import entities_for_frame
from session_context.models import SessionContext
from session_context.type_alignment import SessionTypeMapper
from ._matching import CTX, _members
from .candidates import IdentityCandidateAssessment, assess_frame_candidates
from .criteria import IdentityCriteria
from .graph import object_for_occurrence


@dataclass(frozen=True)
class IdentityCandidateGroup:
    """Apariții care reprezintă același candidat de identitate."""

    key: URIRef
    object_iri: URIRef | None
    assessments: tuple[IdentityCandidateAssessment, ...]
    rejection_decisions: tuple[URIRef, ...]
    unresolved_decisions: tuple[URIRef, ...]


@dataclass(frozen=True)
class IdentityCandidateSelection:
    occurrence_iri: URIRef
    existing_object_iri: URIRef | None
    candidates: tuple[IdentityCandidateGroup, ...]
    excluded_candidates: tuple[IdentityCandidateGroup, ...]


def _identity_decisions(
    context: SessionContext,
    outcome: str,
) -> tuple[tuple[URIRef, URIRef, URIRef], ...]:
    """Citește deciziile și păstrează identificatorii lor."""
    graph = context.identities
    result = []

    for node in sorted(
        set(graph.subjects(
            CTX.identityOutcome,
            Literal(outcome),
        )),
        key=str,
    ):
        left = graph.value(
            node, CTX.leftOccurrence, any=False
        )
        right = graph.value(
            node, CTX.rightOccurrence, any=False
        )
        session_id = graph.value(
            node, CTX.sessionId, any=False
        )

        if (
            not isinstance(node, URIRef)
            or not isinstance(left, URIRef)
            or not isinstance(right, URIRef)
            or left == right
            or (node, RDF.type, CTX.IdentityDecision) not in graph
            or session_id != Literal(context.session_id)
        ):
            raise ValueError(
                "Decizie de identitate invalidă în context."
            )

        result.append((node, left, right))

    return tuple(result)


def select_frame_candidates(
    context: SessionContext,
    reference_frame_id: str,
    current_frame_id: str,
    *,
    mapper: SessionTypeMapper,
    criteria_by_occurrence: Mapping[URIRef, IdentityCriteria],
    language: str | None = None,
) -> dict[URIRef, IdentityCandidateSelection]:
    """Grupează candidații și respectă deciziile existente.

    Exclude numai asocierile respinse explicit, inclusiv cele
    respinse față de un membru al identității candidatului.

    Nu elimină candidați pe baza numelui, a diferențelor vizuale
    sau a lipsei unei relații cunoscute între tipuri.
    Nu creează asocieri.
    """
    comparisons = assess_frame_candidates(
        context,
        reference_frame_id,
        current_frame_id,
        mapper=mapper,
        criteria_by_occurrence=criteria_by_occurrence,
        language=language,
    )

    rejected = _identity_decisions(
        context, "different_objects"
    )
    unresolved = _identity_decisions(
        context, "unresolved"
    )

    selections = {}

    for occurrence in entities_for_frame(context, current_frame_id):
        assessments = comparisons.get(occurrence, ())
        existing_object = object_for_occurrence(
            context, occurrence
        )

        if existing_object is not None:
            selections[occurrence] = IdentityCandidateSelection(
                occurrence_iri=occurrence,
                existing_object_iri=existing_object,
                candidates=(),
                excluded_candidates=(),
            )
            continue

        groups: dict[
            URIRef, list[IdentityCandidateAssessment]
        ] = {}
        objects: dict[URIRef, URIRef | None] = {}

        for assessment in assessments:
            reference = (
                assessment.type_comparison.left.occurrence_iri
            )
            object_iri = object_for_occurrence(
                context, reference
            )
            key = (
                object_iri
                if object_iri is not None
                else reference
            )

            groups.setdefault(key, []).append(assessment)
            objects[key] = object_iri

        candidates = []
        excluded = []

        for key in sorted(groups, key=str):
            group_assessments = tuple(groups[key])
            reference = (
                group_assessments[0]
                .type_comparison.left.occurrence_iri
            )
            object_iri = objects[key]
            members = _members(
                context, reference, object_iri
            )

            rejection_decisions = tuple(
                node
                for node, left, right in rejected
                if (
                    left == occurrence and right in members
                ) or (
                    right == occurrence and left in members
                )
            )

            unresolved_decisions = tuple(
                node
                for node, left, right in unresolved
                if (
                    left == occurrence and right in members
                ) or (
                    right == occurrence and left in members
                )
            )

            candidate = IdentityCandidateGroup(
                key=key,
                object_iri=object_iri,
                assessments=group_assessments,
                rejection_decisions=rejection_decisions,
                unresolved_decisions=unresolved_decisions,
            )

            if rejection_decisions:
                excluded.append(candidate)
            else:
                candidates.append(candidate)

        selections[occurrence] = IdentityCandidateSelection(
            occurrence_iri=occurrence,
            existing_object_iri=None,
            candidates=tuple(candidates),
            excluded_candidates=tuple(excluded),
        )

    return selections
