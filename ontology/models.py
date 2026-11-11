"""Structurile catalogului ontologiei."""

from dataclasses import dataclass, field
from enum import StrEnum


class ConceptKind(StrEnum):
    CLASS = "class"
    SKOS_CONCEPT = "skos_concept"
    INDIVIDUAL = "individual"


@dataclass(frozen=True)
class OntologyText:
    """Un text din ontologie, cu limba și proprietatea sursă."""

    value: str
    language: str | None = None
    predicate: str = ""


@dataclass
class OntologyConcept:
    iri: str
    kinds: list[ConceptKind] = field(default_factory=list)
    labels: list[OntologyText] = field(default_factory=list)
    synonyms: list[OntologyText] = field(default_factory=list)
    definitions: list[OntologyText] = field(default_factory=list)
    parents: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)


@dataclass
class OntologyCatalog:
    source: str
    concepts: list[OntologyConcept] = field(default_factory=list)
    ontology_iris: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "total_concepts": len(self.concepts),
            "by_kind": {
                kind.value: sum(
                    kind in concept.kinds
                    for concept in self.concepts
                )
                for kind in ConceptKind
            },
            "without_labels": sum(
                not concept.labels for concept in self.concepts
            ),
            "without_definitions": sum(
                not concept.definitions for concept in self.concepts
            ),
            "imports_not_loaded": len(self.imports),
            "warnings": list(self.warnings),
        }