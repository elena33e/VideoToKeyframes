"""Propuneri și asocieri automate între două cadre alese explicit."""

import json
from collections import Counter
from dataclasses import dataclass, replace
from typing import Literal as StatusLiteral
from unicodedata import normalize

from rdflib import RDF, RDFS, Dataset, Literal, Namespace, URIRef

from interpretation.config import OBSERVATION_NAMESPACE

from .comparison import OccurrenceComparison, compare_occurrences
from .graph import entities_for_frame
from .identity import IdentityDecision, TrackedObject
from .identity_graph import object_for_occurrence, record_identity_decision
from .models import SessionContext

from .identity_criteria import (
    CharacteristicAssessment,
    IdentityCriteria,
    assess_identity_characteristics,
)
from .type_alignment import (
    OccurrenceTypeComparison,
    SessionTypeMapper,
)

from collections.abc import Collection, Mapping

CTX = Namespace(OBSERVATION_NAMESPACE)
AssociationAction = StatusLiteral[
    "automatic", "confirmation", "unresolved", "already_associated"
]


def _key(value: str) -> str:
    return " ".join(normalize("NFC", value).split()).casefold()


@dataclass(frozen=True)
class IdentityCandidate:
    comparison: OccurrenceComparison
    object_iri: URIRef | None
    automatic_eligible: bool
    prior_unresolved: bool = False

    @property
    def reference_iri(self) -> URIRef:
        return self.comparison.left_occurrence_iri

    @property
    def identity_key(self) -> URIRef:
        return self.object_iri if self.object_iri is not None else self.reference_iri


@dataclass(frozen=True)
class AssociationAssessment:
    occurrence_iri: URIRef
    action: AssociationAction
    reason: str
    candidates: tuple[IdentityCandidate, ...] = ()


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

def _label(context: SessionContext, occurrence: URIRef) -> str:
    values = set(context.observations.objects(occurrence, RDFS.label))
    if len(values) != 1:
        raise ValueError("Apariția trebuie să aibă un singur nume.")
    value = next(iter(values))
    if not isinstance(value, Literal) or not isinstance(value.toPython(), str):
        raise ValueError("Numele apariției trebuie să fie text.")
    if not _key(str(value)):
        raise ValueError("Numele apariției este gol.")
    return _key(str(value))


def _certain(context: SessionContext, occurrence: URIRef) -> bool:
    return set(context.observations.objects(occurrence, CTX.uncertain)) == {
        Literal(False)
    }


def _members(
    context: SessionContext, occurrence: URIRef, object_iri: URIRef | None
) -> set[URIRef]:
    if object_iri is None:
        return {occurrence}
    return set(context.identities.subjects(CTX.associatedObject, object_iri))


def assess_frame_associations(
    context: SessionContext,
    reference_frame_id: str,
    current_frame_id: str,
    *,
    identity_names: Collection[str],
    min_matching: int = 2,
) -> tuple[AssociationAssessment, ...]:
    """Evaluează candidații, fără să modifice graful."""
    if (
        isinstance(identity_names, str)
        or not identity_names
        or any(not isinstance(name, str) or not _key(name) for name in identity_names)
    ):
        raise ValueError("Specifică o colecție nevidă de caracteristici.")
    names = tuple(sorted({_key(name) for name in identity_names}))
    if type(min_matching) is not int or not 1 <= min_matching <= len(names):
        raise ValueError("min_matching trebuie să fie între 1 și numărul trăsăturilor.")
    if (
        reference_frame_id == current_frame_id
        or reference_frame_id not in context.frame_iris
        or current_frame_id not in context.frame_iris
    ):
        raise ValueError("Alege două cadre distincte existente în context.")

    references = entities_for_frame(context, reference_frame_id)
    current = entities_for_frame(context, current_frame_id)
    assigned = {
        occurrence: object_for_occurrence(context, occurrence)
        for occurrence in (*references, *current)
    }
    labels = {
        occurrence: _label(context, occurrence)
        for occurrence in (*references, *current)
    }
    rejected_pairs = [
        {
            context.identities.value(node, CTX.leftOccurrence, any=False),
            context.identities.value(node, CTX.rightOccurrence, any=False),
        }
        for node in context.identities.subjects(
            CTX.identityOutcome, Literal("different_objects")
        )
    ]
    unresolved_pairs = [
        {
            context.identities.value(node, CTX.leftOccurrence, any=False),
            context.identities.value(node, CTX.rightOccurrence, any=False),
        }
        for node in context.identities.subjects(
            CTX.identityOutcome, Literal("unresolved")
        )
    ]
    assessments = []

    for occurrence in current:
        if assigned[occurrence] is not None:
            assessments.append(AssociationAssessment(
                occurrence, "already_associated", "existing_identity"
            ))
            continue

        candidates = []
        for reference in references:
            if labels[reference] != labels[occurrence]:
                continue
            members = _members(context, reference, assigned[reference])
            if members.intersection(current):
                continue
            if any(pair <= members | {occurrence} for pair in rejected_pairs):
                continue

            comparison = compare_occurrences(
                context, reference, occurrence, identity_names=names
            )
            matching = sum(
                item.status == "unchanged"
                for item in comparison.characteristics
            )
            prior_unresolved = any(
                occurrence in pair and bool((pair - {occurrence}) & members)
                for pair in unresolved_pairs
            )
            eligible = (
                not prior_unresolved
                and not comparison.requires_confirmation
                and matching >= min_matching
                and _certain(context, reference)
                and _certain(context, occurrence)
            )
            candidates.append(IdentityCandidate(
                comparison, assigned[reference], eligible, prior_unresolved
            ))


        options = tuple(candidates)
        action: AssociationAction
        reason: str
        if not options:
            action, reason = "unresolved", "no_candidate"
        elif len(options) != 1:
            action, reason = "unresolved", "multiple_candidates"
        elif options[0].prior_unresolved:
            action, reason = "unresolved", "previous_unresolved_decision"
        elif options[0].comparison.requires_confirmation:
            action, reason = "confirmation", "characteristic_difference"
        elif options[0].automatic_eligible:
            action, reason = "automatic", "unique_candidate_with_evidence"
        else:
            action, reason = "unresolved", "insufficient_evidence"

        assessments.append(AssociationAssessment(
            occurrence, action, reason, options
        ))

    # Verificăm întregul cadru înainte de a accepta o asociere.
    usage = Counter(
        key
        for assessment in assessments
        for key in {candidate.identity_key for candidate in assessment.candidates}
    )
    return tuple(
        replace(
            assessment,
            action="unresolved",
            reason="competing_current_appearances",
        )
        if (
            assessment.action in {"automatic", "confirmation"}
            and usage[assessment.candidates[0].identity_key] > 1
        )
        else assessment
        for assessment in assessments
    )


def apply_automatic_associations(
    context: SessionContext,
    reference_frame_id: str,
    current_frame_id: str,
    *,
    identity_names: Collection[str],
    min_matching: int = 2,
) -> tuple[URIRef, ...]:
    """Reevaluează și înregistrează numai asocierile automate acceptabile."""
    assessments = assess_frame_associations(
        context,
        reference_frame_id,
        current_frame_id,
        identity_names=identity_names,
        min_matching=min_matching,
    )
    scratch = Dataset()
    for iri in (context.observations_iri, context.identities_iri):
        for triple in context.dataset.graph(iri):
            scratch.graph(iri).add(triple)
    staged = replace(context, dataset=scratch)
    decisions = []

    for assessment in assessments:
        if assessment.action != "automatic":
            continue
        candidate = assessment.candidates[0]
        tracked = None
        if candidate.object_iri is None:
            tracked = TrackedObject(session_id=context.session_id)
            object_id = tracked.object_id
        else:
            identifier = staged.identities.value(
                candidate.object_iri, CTX.objectId, any=False
            )
            if not isinstance(identifier, Literal):
                raise ValueError("Obiectul urmărit nu are un identificator valid.")
            object_id = str(identifier)

        evidence = [
            {
                "name": item.name,
                "status": item.status,
                "left": [str(value.iri) for value in item.left],
                "right": [str(value.iri) for value in item.right],
            }
            for item in candidate.comparison.characteristics
        ]
        decision = IdentityDecision(
            session_id=context.session_id,
            left_occurrence_iri=str(candidate.reference_iri),
            right_occurrence_iri=str(assessment.occurrence_iri),
            outcome="same_object",
            object_id=object_id,
            decided_by="automatic:frame-matching-v1",
            justification=json.dumps({
                "method": "frame-matching-v1",
                "reference_frame_id": reference_frame_id,
                "current_frame_id": current_frame_id,
                "min_matching": min_matching,
                "evidence": evidence,
            }, ensure_ascii=False, sort_keys=True),
        )
        decisions.append(record_identity_decision(
            staged, decision, new_object=tracked
        ))

    # Nicio asociere nu ajunge în context înainte de validarea lotului.
    for triple in staged.identities:
        context.identities.add(triple)
    return tuple(decisions)
