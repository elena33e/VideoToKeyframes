"""Compararea caracteristicilor de identitate ale două apariții."""

from collections.abc import Collection
from dataclasses import dataclass
from typing import Literal as StatusLiteral
from unicodedata import normalize

from rdflib import RDF, RDFS, XSD, Literal, Namespace, URIRef

from interpretation.config import OBSERVATION_NAMESPACE

from .graph import entities_for_frame
from .models import SessionContext


CTX = Namespace(OBSERVATION_NAMESPACE)

ComparisonStatus = StatusLiteral["unchanged", "different", "unknown"]
ComparisonReason = StatusLiteral[
    "same_value",
    "different_values",
    "missing",
    "uncertain",
    "multiple_values",
]


def _text(value: str) -> str:
    return " ".join(normalize("NFC", value).split())


def _name(value: str) -> str:
    return _text(value).casefold()


@dataclass(frozen=True)
class CharacteristicEvidence:
    iri: URIRef
    name: str
    value: str
    uncertain: bool | None


@dataclass(frozen=True)
class CharacteristicComparison:
    name: str
    left: tuple[CharacteristicEvidence, ...]
    right: tuple[CharacteristicEvidence, ...]
    status: ComparisonStatus
    reason: ComparisonReason


@dataclass(frozen=True)
class OccurrenceComparison:
    left_occurrence_iri: URIRef
    right_occurrence_iri: URIRef
    characteristics: tuple[CharacteristicComparison, ...]

    @property
    def requires_confirmation(self) -> bool:
        return any(
            item.status == "different"
            for item in self.characteristics
        )

    @property
    def has_comparable_evidence(self) -> bool:
        return any(
            item.status != "unknown"
            for item in self.characteristics
        )


def characteristics_for_occurrence(
    context: SessionContext,
    occurrence: URIRef,
) -> tuple[CharacteristicEvidence, ...]:
    graph = context.observations

    frames = [
        frame_id
        for frame_id in context.frame_iris
        if occurrence in entities_for_frame(context, frame_id)
    ]

    if (
        len(frames) != 1
        or (occurrence, RDF.type, CTX.EntityObservation) not in graph
    ):
        raise ValueError(
            "Apariția nu aparține unui singur cadru al sesiunii."
        )

    result = []

    for node in sorted(
        set(graph.objects(occurrence, CTX.characteristics)),
        key=str,
    ):
        if (
            not isinstance(node, URIRef)
            or (
                node,
                RDF.type,
                CTX.CharacteristicObservation,
            ) not in graph
        ):
            raise ValueError("Caracteristică RDF invalidă.")

        fields = []

        for predicate in (RDFS.label, CTX.characteristicValue):
            values = set(graph.objects(node, predicate))

            if len(values) != 1:
                raise ValueError(
                    "Caracteristica trebuie să aibă un nume și o valoare."
                )

            value = next(iter(values))

            if (
                not isinstance(value, Literal)
                or not isinstance(value.toPython(), str)
                or not _text(str(value))
            ):
                raise ValueError(
                    "Numele și valoarea trebuie să fie texte nevide."
                )

            fields.append(str(value))

        markers = set(graph.objects(node, CTX.uncertain))
        uncertain: bool | None = None

        if markers:
            marker = next(iter(markers))

            if (
                len(markers) != 1
                or not isinstance(marker, Literal)
                or marker.datatype != XSD.boolean
                or type(marker.toPython()) is not bool
            ):
                raise ValueError("Marcaj de incertitudine invalid.")

            uncertain = marker.toPython()

        result.append(CharacteristicEvidence(
            iri=node,
            name=fields[0],
            value=fields[1],
            uncertain=uncertain,
        ))

    return tuple(result)


def compare_occurrences(
    context: SessionContext,
    left_occurrence_iri: str | URIRef,
    right_occurrence_iri: str | URIRef,
    *,
    identity_names: Collection[str],
) -> OccurrenceComparison:
    """Compară valorile descrise; nu stabilește singură identitatea."""
    if isinstance(identity_names, str):
        raise ValueError(
            "identity_names trebuie să fie o colecție de nume."
        )

    if not identity_names or any(
        not isinstance(name, str) or not _name(name)
        for name in identity_names
    ):
        raise ValueError(
            "Specifică cel puțin o caracteristică de identitate."
        )

    names = sorted({_name(name) for name in identity_names})

    left_iri = URIRef(left_occurrence_iri)
    right_iri = URIRef(right_occurrence_iri)

    if left_iri == right_iri:
        raise ValueError("Compară două apariții distincte.")

    left = characteristics_for_occurrence(context, left_iri)
    right = characteristics_for_occurrence(context, right_iri)

    comparisons = []

    for name in names:
        left_items = tuple(
            item for item in left if _name(item.name) == name
        )
        right_items = tuple(
            item for item in right if _name(item.name) == name
        )

        status: ComparisonStatus
        reason: ComparisonReason

        if not left_items or not right_items:
            status, reason = "unknown", "missing"

        elif any(
            item.uncertain is not False
            for item in (*left_items, *right_items)
        ):
            status, reason = "unknown", "uncertain"

        else:
            left_values = {
                _text(item.value) for item in left_items
            }
            right_values = {
                _text(item.value) for item in right_items
            }

            if len(left_values) != 1 or len(right_values) != 1:
                status, reason = "unknown", "multiple_values"

            elif left_values == right_values:
                status, reason = "unchanged", "same_value"

            else:
                status, reason = "different", "different_values"

        comparisons.append(CharacteristicComparison(
            name=name,
            left=left_items,
            right=right_items,
            status=status,
            reason=reason,
        ))

    return OccurrenceComparison(
        left_occurrence_iri=left_iri,
        right_occurrence_iri=right_iri,
        characteristics=tuple(comparisons),
    )