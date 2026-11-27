"""Propuneri de interpretare și selecție a caracteristicilor observate."""

from collections.abc import Collection
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictBool,
    StringConstraints,
    model_validator,
)
from rdflib import Graph, OWL, RDF, RDFS, URIRef

from .comparison import characteristics_for_occurrence
from .graph import entities_for_frame
from .identity import AbsoluteIRI
from .models import SessionContext


Text = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
    ),
]

CharacteristicUse = Literal[
    "comparison",
    "state",
    "comparison_and_state",
    "not_selected",
    "unresolved",
]


class CharacteristicInterpretation(BaseModel):
    """Interpretarea unei caracteristici existente în observații.

    meaning și normalized_value sunt propuneri de normalizare.
    Valorile originale sunt păstrate în observația sursă.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    source_characteristic_iri: AbsoluteIRI

    meaning: Text | None
    normalized_value: Text | None

    target_kind: Literal["entity", "part", "unresolved"]
    part_name: Text | None

    use: CharacteristicUse
    reason: Text
    uncertain: StrictBool

    property_iri: AbsoluteIRI | None
    ontology_reference_iris: tuple[AbsoluteIRI, ...]

    @model_validator(mode="after")
    def validate_interpretation(self) -> Self:
        if self.target_kind == "part":
            if self.part_name is None:
                raise ValueError(
                    "Interpretarea unei părți necesită denumirea ei."
                )
        elif self.part_name is not None:
            raise ValueError(
                "Denumirea părții este permisă numai "
                "pentru target_kind='part'."
            )

        if self.use in {
            "comparison",
            "state",
            "comparison_and_state",
        }:
            if self.meaning is None:
                raise ValueError(
                    "O caracteristică selectată necesită "
                    "un sens interpretat."
                )

            if self.target_kind == "unresolved":
                raise ValueError(
                    "Ținta caracteristicii trebuie clarificată "
                    "înaintea selectării."
                )

        if (
            self.use == "unresolved"
            or self.target_kind == "unresolved"
        ) and not self.uncertain:
            raise ValueError(
                "O interpretare nerezolvată trebuie "
                "marcată ca incertă."
            )

        return self


class AppearanceCharacteristicSelection(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    occurrence_iri: AbsoluteIRI
    characteristics: tuple[CharacteristicInterpretation, ...]


class CharacteristicSelectionProposal(BaseModel):
    """Rezultatul propus de interpretare, fără acceptare implicită."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    status: Literal["proposal"] = "proposal"
    appearances: tuple[AppearanceCharacteristicSelection, ...]


def _property_iris(ontology: Graph) -> set[URIRef]:
    """Proprietăți declarate sau folosite în ontologia disponibilă."""
    properties = set(ontology.predicates())

    for kind in (
        RDF.Property,
        OWL.ObjectProperty,
        OWL.DatatypeProperty,
        OWL.AnnotationProperty,
    ):
        properties.update(ontology.subjects(RDF.type, kind))

    for predicate in (
        RDFS.domain,
        RDFS.range,
        RDFS.subPropertyOf,
    ):
        properties.update(ontology.subjects(predicate, None))

    properties.update(ontology.objects(None, RDFS.subPropertyOf))
    properties.update(ontology.objects(None, OWL.onProperty))

    return {
        term
        for term in properties
        if isinstance(term, URIRef)
    }


def check_selection_proposal(
    proposal: CharacteristicSelectionProposal,
    *,
    context: SessionContext,
    expected_occurrences: Collection[str | URIRef],
    ontology: Graph,
) -> CharacteristicSelectionProposal:
    """Verifică sursele și acoperirea rezultatului.

    Verificarea nu confirmă corectitudinea semantică a normalizării,
    relevanța aleasă sau identitatea obiectelor.
    Statutul rezultatului rămâne 'proposal'.
    """
    if isinstance(expected_occurrences, (str, bytes)):
        raise ValueError(
            "Aparițiile așteptate trebuie transmise ca o colecție."
        )

    expected = tuple(
        URIRef(occurrence)
        for occurrence in expected_occurrences
    )

    if len(expected) != len(set(expected)):
        raise ValueError("Lista aparițiilor conține duplicate.")

    known = {
        occurrence
        for frame_id in context.frame_iris
        for occurrence in entities_for_frame(context, frame_id)
    }

    if not set(expected).issubset(known):
        raise ValueError(
            "Unele apariții nu există în observațiile sesiunii."
        )

    actual = tuple(
        URIRef(appearance.occurrence_iri)
        for appearance in proposal.appearances
    )

    if len(actual) != len(set(actual)):
        raise ValueError(
            "Propunerea conține apariții duplicate."
        )

    if set(actual) != set(expected):
        raise ValueError(
            "Propunerea trebuie să acopere exact aparițiile cerute."
        )

    ontology_iris = {
        term
        for triple in ontology
        for term in triple
        if isinstance(term, URIRef)
    }
    properties = _property_iris(ontology)

    for appearance in proposal.appearances:
        occurrence = URIRef(appearance.occurrence_iri)

        sources = {
            characteristic.iri: characteristic
            for characteristic in characteristics_for_occurrence(
                context,
                occurrence,
            )
        }

        interpreted = tuple(
            URIRef(item.source_characteristic_iri)
            for item in appearance.characteristics
        )

        if len(interpreted) != len(set(interpreted)):
            raise ValueError(
                "O caracteristică apare de mai multe ori "
                "în interpretarea aceleiași apariții."
            )

        if set(interpreted) != set(sources):
            raise ValueError(
                "Interpretarea trebuie să acopere toate "
                "caracteristicile apariției, fără surse suplimentare."
            )

        for item in appearance.characteristics:
            source = sources[URIRef(
                item.source_characteristic_iri
            )]

            if source.uncertain is not False and not item.uncertain:
                raise ValueError(
                    "Incertitudinea observației sursă "
                    "nu poate fi eliminată prin interpretare."
                )

            if (
                item.property_iri is not None
                and URIRef(item.property_iri) not in properties
            ):
                raise ValueError(
                    "Proprietatea propusă nu este declarată "
                    "sau folosită în ontologia disponibilă."
                )

            references = {
                URIRef(iri)
                for iri in item.ontology_reference_iris
            }

            if not references.issubset(ontology_iris):
                raise ValueError(
                    "Interpretarea citează referințe absente "
                    "din ontologia disponibilă."
                )

    return proposal