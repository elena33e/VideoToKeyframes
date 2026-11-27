"""Evaluarea identității pe baza candidaților, fără modificarea grafului."""

from collections.abc import Mapping
from dataclasses import dataclass

from rdflib import URIRef

from session_context.models import SessionContext
from session_context.type_alignment import SessionTypeMapper
from ._matching import AssociationAction
from .criteria import IdentityCriteria
from .selection import IdentityCandidateSelection, select_frame_candidates


@dataclass(frozen=True)
class IdentityAssessment:
    """Rezultatul evaluării, împreună cu dovezile disponibile."""

    selection: IdentityCandidateSelection
    action: AssociationAction
    reasons: tuple[str, ...]
    evaluator_version: str = "identity-assessment-v3"

    @property
    def occurrence_iri(self) -> URIRef:
        return self.selection.occurrence_iri


def _assess_candidate_selection(
    selection: IdentityCandidateSelection,
) -> IdentityAssessment:
    if selection.existing_object_iri is not None:
        return IdentityAssessment(
            selection=selection,
            action="already_associated",
            reasons=("existing_identity",),
        )

    candidates = selection.candidates

    if not candidates:
        reason = (
            "all_candidates_rejected"
            if selection.excluded_candidates
            else "no_candidate"
        )

        return IdentityAssessment(
            selection=selection,
            action="unresolved",
            reasons=(reason,),
        )

    reasons = []

    if len(candidates) > 1:
        reasons.append("multiple_candidates")

    prior_unresolved = any(
        candidate.unresolved_decisions
        for candidate in candidates
    )

    if prior_unresolved:
        reasons.append("previous_unresolved_decision")

    different = False
    missing_required = False

    for candidate in candidates:
        for assessment in candidate.assessments:
            characteristics = assessment.characteristics
            types = assessment.type_comparison

            if characteristics.different_characteristics:
                different = True

            if characteristics.unknown_required_characteristics:
                missing_required = True

            proposals = (types.left, types.right)

            requirements = (
                characteristics.criteria.identity_requirements
            )

            if requirements is None:
                reasons.append("criteria_scope_not_configured")

            elif any(
                proposal.alignment.status != "unique"
                or proposal.uncertain is not False
                for proposal in proposals
            ):
                reasons.append("criteria_scope_unresolved")

            elif any(
                proposal.alignment.candidates[0].class_iri
                not in requirements.applicable_class_iris
                for proposal in proposals
            ):
                reasons.append("criteria_scope_not_supported")

            else:
                reasons.append("criteria_scope_proposed")

            if any(
                proposal.alignment.status == "unmapped"
                for proposal in proposals
            ):
                reasons.append("unmapped_types")

            if any(
                proposal.alignment.status == "ambiguous"
                for proposal in proposals
            ):
                reasons.append("ambiguous_types")

            if any(
                proposal.uncertain is not False
                for proposal in proposals
            ):
                reasons.append("uncertain_types")

            if any(
                proposal.alignment.imports_not_loaded
                for proposal in proposals
            ):
                reasons.append("incomplete_ontology")

            for relation in types.class_relations:
                if relation.declared_disjoint:
                    reasons.append("declared_disjoint_types")

                if (
                    not relation.left_known
                    or not relation.right_known
                    or (
                        relation.left_to_right is None
                        and relation.right_to_left is None
                    )
                ):
                    reasons.append("unknown_type_relation")

    if different:
        reasons.append("characteristic_difference")

    if missing_required:
        reasons.append("insufficient_characteristics")

    if (
        len(candidates) == 1
        and different
        and not prior_unresolved
    ):
        action: AssociationAction = "confirmation"
    else:
        action = "unresolved"

    if (
        len(candidates) == 1
        and not different
        and not missing_required
        and not prior_unresolved
    ):
        reasons.append("identity_evidence_required")

    return IdentityAssessment(
        selection=selection,
        action=action,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def assess_frame_identity(
    context: SessionContext,
    reference_frame_id: str,
    current_frame_id: str,
    *,
    mapper: SessionTypeMapper,
    criteria_by_occurrence: Mapping[URIRef, IdentityCriteria],
    language: str | None = None,
) -> tuple[IdentityAssessment, ...]:
    """Evaluează identitatea fără să creeze sau să modifice asocieri.

    Diferențele pot necesita verificare manuală.
    Ambiguitatea singură nu declanșează confirmarea.
    Concordanța caracteristicilor nu demonstrează identitatea.
    """
    selections = select_frame_candidates(
        context,
        reference_frame_id,
        current_frame_id,
        mapper=mapper,
        criteria_by_occurrence=criteria_by_occurrence,
        language=language,
    )

    results = []

    for selection in selections.values():
        if (
                selection.existing_object_iri is None
                and selection.occurrence_iri not in criteria_by_occurrence
        ):
            assessment = IdentityAssessment(
                selection=selection,
                action="unresolved",
                reasons=("criteria_not_configured",),
            )
        else:
            assessment = _assess_candidate_selection(selection)

        results.append(assessment)

    return tuple(results)
