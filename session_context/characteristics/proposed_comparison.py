"""Comparații bazate pe interpretări propuse ale caracteristicilor."""

from dataclasses import dataclass, field
from typing import Literal
from unicodedata import normalize

from rdflib import Graph, URIRef

from .comparison import (
    CharacteristicEvidence,
    characteristics_for_occurrence,
)
from .graph import (
    CharacteristicSelectionRecord,
    read_characteristic_selection,
)
from .selection import CharacteristicInterpretation
from ..models import SessionContext


ProposedComparisonStatus = Literal[
    "same_proposed_value",
    "different_proposed_values",
    "unknown",
]


def _text(value: str) -> str:
    return " ".join(normalize("NFC", value).split())


def _name(value: str) -> str:
    return _text(value).casefold()


@dataclass(frozen=True)
class CharacteristicMatchKey:
    reference_kind: Literal["property", "meaning"]
    reference: str
    target_kind: Literal["entity", "part"]
    part_name: str | None


@dataclass(frozen=True)
class ProposedCharacteristicEvidence:
    observed: CharacteristicEvidence
    interpretation: CharacteristicInterpretation


@dataclass(frozen=True)
class ProposedCharacteristicComparison:
    key: CharacteristicMatchKey
    left: tuple[ProposedCharacteristicEvidence, ...]
    right: tuple[ProposedCharacteristicEvidence, ...]
    status: ProposedComparisonStatus
    reason: str


@dataclass(frozen=True)
class ProposedOccurrenceComparison:
    left_occurrence_iri: URIRef
    right_occurrence_iri: URIRef
    left_record_iri: URIRef
    right_record_iri: URIRef

    characteristics: tuple[ProposedCharacteristicComparison, ...]
    unresolved_left: tuple[ProposedCharacteristicEvidence, ...]
    unresolved_right: tuple[ProposedCharacteristicEvidence, ...]

    status: Literal["proposal"] = field(
        default="proposal", init=False
    )


def _appearance_evidence(
    context: SessionContext,
    record: CharacteristicSelectionRecord,
    occurrence: URIRef,
) -> tuple[ProposedCharacteristicEvidence, ...]:
    appearance = next(
        (
            item
            for item in record.proposal.appearances
            if item.occurrence_iri == str(occurrence)
        ),
        None,
    )
    if appearance is None:
        raise ValueError(
            "Înregistrarea aleasă nu conține apariția cerută."
        )

    sources = {
        str(item.iri): item
        for item in characteristics_for_occurrence(
            context, occurrence
        )
    }

    return tuple(
        ProposedCharacteristicEvidence(
            observed=sources[item.source_characteristic_iri],
            interpretation=item,
        )
        for item in appearance.characteristics
    )


def _match_key(
    item: CharacteristicInterpretation,
) -> CharacteristicMatchKey | None:
    if item.target_kind == "unresolved":
        return None

    part_name = (
        _name(item.part_name)
        if item.part_name is not None
        else None
    )

    if item.property_iri is not None:
        return CharacteristicMatchKey(
            reference_kind="property",
            reference=item.property_iri,
            target_kind=item.target_kind,
            part_name=part_name,
        )

    if item.meaning is None:
        return None

    return CharacteristicMatchKey(
        reference_kind="meaning",
        reference=_name(item.meaning),
        target_kind=item.target_kind,
        part_name=part_name,
    )


def _group_evidence(
    items: tuple[ProposedCharacteristicEvidence, ...],
) -> tuple[
    dict[CharacteristicMatchKey, list[ProposedCharacteristicEvidence]],
    tuple[ProposedCharacteristicEvidence, ...],
]:
    groups: dict[
        CharacteristicMatchKey,
        list[ProposedCharacteristicEvidence],
    ] = {}
    unresolved = []

    for item in items:
        key = _match_key(item.interpretation)
        if key is None:
            unresolved.append(item)
        else:
            groups.setdefault(key, []).append(item)

    return groups, tuple(unresolved)


def _comparison_status(
    left: tuple[ProposedCharacteristicEvidence, ...],
    right: tuple[ProposedCharacteristicEvidence, ...],
) -> tuple[ProposedComparisonStatus, str]:
    items = left + right

    if any(
        item.interpretation.use == "unresolved"
        for item in items
    ):
        return "unknown", "interpretation_unresolved"

    if any(
        item.interpretation.use not in {
            "comparison", "comparison_and_state"
        }
        for item in items
    ):
        return "unknown", "not_selected_for_comparison"

    if not left or not right:
        return "unknown", "missing_counterpart"

    if len(left) != 1 or len(right) != 1:
        return "unknown", "ambiguous_characteristics"

    if any(
        item.observed.uncertain is not False
        or item.interpretation.uncertain
        for item in items
    ):
        return "unknown", "uncertain"

    left_value = left[0].interpretation.normalized_value
    right_value = right[0].interpretation.normalized_value

    if left_value is None or right_value is None:
        return "unknown", "missing_normalized_value"

    if _text(left_value) == _text(right_value):
        return "same_proposed_value", "normalized_text_equal"

    if _text(left[0].observed.value) == _text(
        right[0].observed.value
    ):
        return "unknown", "conflicting_normalization"

    return "different_proposed_values", "normalized_text_different"


def compare_proposed_characteristics(
    context: SessionContext,
    left_occurrence_iri: str | URIRef,
    right_occurrence_iri: str | URIRef,
    *,
    left_record_iri: str | URIRef,
    right_record_iri: str | URIRef,
    ontology: Graph,
) -> ProposedOccurrenceComparison:
    """Compară două apariții folosind înregistrări alese explicit.

    Corespondențele și normalizările rămân propuneri.
    Funcția nu decide identitatea și nu modifică grafurile.
    """
    left_occurrence = URIRef(left_occurrence_iri)
    right_occurrence = URIRef(right_occurrence_iri)

    if left_occurrence == right_occurrence:
        raise ValueError("Compară două apariții distincte.")

    left_record = read_characteristic_selection(
        context, left_record_iri, ontology=ontology
    )
    right_record = read_characteristic_selection(
        context, right_record_iri, ontology=ontology
    )

    left, unresolved_left = _group_evidence(
        _appearance_evidence(
            context, left_record, left_occurrence
        )
    )
    right, unresolved_right = _group_evidence(
        _appearance_evidence(
            context, right_record, right_occurrence
        )
    )

    keys = sorted(
        left.keys() | right.keys(),
        key=lambda item: (
            item.target_kind,
            item.part_name or "",
            item.reference_kind,
            item.reference,
        ),
    )

    comparisons = []
    for key in keys:
        left_items = tuple(left.get(key, ()))
        right_items = tuple(right.get(key, ()))
        status, reason = _comparison_status(
            left_items, right_items
        )
        comparisons.append(ProposedCharacteristicComparison(
            key=key,
            left=left_items,
            right=right_items,
            status=status,
            reason=reason,
        ))

    return ProposedOccurrenceComparison(
        left_occurrence_iri=left_occurrence,
        right_occurrence_iri=right_occurrence,
        left_record_iri=URIRef(left_record_iri),
        right_record_iri=URIRef(right_record_iri),
        characteristics=tuple(comparisons),
        unresolved_left=unresolved_left,
        unresolved_right=unresolved_right,
    )