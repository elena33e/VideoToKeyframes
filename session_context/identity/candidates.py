"""Evaluarea dovezilor pentru perechi de apariții și cadre."""

from collections.abc import Mapping
from dataclasses import dataclass

from rdflib import URIRef

from session_context.characteristics.comparison import compare_occurrences
from session_context.graph import entities_for_frame
from session_context.models import SessionContext
from session_context.type_alignment import OccurrenceTypeComparison, SessionTypeMapper
from .criteria import CharacteristicAssessment, IdentityCriteria, assess_identity_characteristics


@dataclass(frozen=True)
class IdentityCandidateAssessment:
    """Dovezile despre o pereche, fără decizie de identitate."""

    type_comparison: OccurrenceTypeComparison
    characteristics: CharacteristicAssessment


def assess_identity_candidate(
    context: SessionContext,
    reference_occurrence_iri: str | URIRef,
    current_occurrence_iri: str | URIRef,
    *,
    mapper: SessionTypeMapper,
    criteria: IdentityCriteria,
    language: str | None = None,
) -> IdentityCandidateAssessment:
    """Examinează tipurile și caracteristicile fără să modifice graful.

    Numele diferite nu elimină perechea.
    Propunerile de clase și toate alternativele lor sunt păstrate.
    Absența unei relații cunoscute nu înseamnă incompatibilitate.
    Rezultatul nu autorizează singur asocierea automată.
    """
    comparison = compare_occurrences(
        context,
        reference_occurrence_iri,
        current_occurrence_iri,
        identity_names=criteria.characteristics,
    )

    reference_type = mapper.propose(
        context,
        reference_occurrence_iri,
        language=language,
    )
    current_type = mapper.propose(
        context,
        current_occurrence_iri,
        language=language,
    )

    type_comparison = mapper.compare(
        reference_type,
        current_type,
    )

    characteristics = assess_identity_characteristics(
        comparison,
        criteria=criteria,
    )

    return IdentityCandidateAssessment(
        type_comparison=type_comparison,
        characteristics=characteristics,
    )


def assess_frame_candidates(
    context: SessionContext,
    reference_frame_id: str,
    current_frame_id: str,
    *,
    mapper: SessionTypeMapper,
    criteria_by_occurrence: Mapping[URIRef, IdentityCriteria],
    language: str | None = None,
) -> dict[URIRef, tuple[IdentityCandidateAssessment, ...]]:
    """Compară aparițiile curente care au criterii configurate.

    Fiecare apariție configurată este comparată cu toate aparițiile
    de referință. Diferențele și informațiile necunoscute sunt păstrate.

    Aparițiile curente fără criterii sunt tratate separat
    în evaluarea identității.
    """
    if (
        reference_frame_id == current_frame_id
        or reference_frame_id not in context.frame_iris
        or current_frame_id not in context.frame_iris
    ):
        raise ValueError(
            "Alege două cadre distincte existente în context."
        )

    references = entities_for_frame(
        context,
        reference_frame_id,
    )
    current = entities_for_frame(
        context,
        current_frame_id,
    )

    selected_criteria = dict(criteria_by_occurrence)

    if not set(selected_criteria).issubset(set(current)):
        raise ValueError(
            "Criteriile indică apariții care nu aparțin "
            "cadrului comparat."
        )

    if any(
        not isinstance(criteria, IdentityCriteria)
        for criteria in selected_criteria.values()
    ):
        raise ValueError(
            "Criteriile trebuie să fie instanțe IdentityCriteria."
        )

    return {
        occurrence: tuple(
            assess_identity_candidate(
                context,
                reference,
                occurrence,
                mapper=mapper,
                criteria=selected_criteria[occurrence],
                language=language,
            )
            for reference in references
        )
        for occurrence in current
        if occurrence in selected_criteria
    }
