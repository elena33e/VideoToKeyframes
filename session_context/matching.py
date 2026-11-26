"""Propuneri și asocieri automate între două cadre alese explicit."""

import json
from collections import Counter
from collections.abc import Collection
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

        # Un candidat concordant suficient susținut are prioritate față
        # de cei cu diferențe. Candidații cu date necunoscute rămân rivali.
        if any(candidate.automatic_eligible for candidate in candidates):
            candidates = [
                candidate for candidate in candidates
                if not candidate.comparison.requires_confirmation
            ]

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
