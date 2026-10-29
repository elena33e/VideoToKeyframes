from dataclasses import dataclass, field, asdict
from urllib.parse import unquote
from enum import StrEnum
from pathlib import Path


class ConceptKind(StrEnum):
    CLASS = "class"
    SKOS_CONCEPT = "skos_concept"
    INDIVIDUAL = "individual"


@dataclass(frozen=True)
class OntologyText:
    """Un text din ontologie, cu limba si proprietatea sursa"""
    value:str
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

    def preferred_label(
            self,
            languages: tuple[str, ...] = ("ro", "en"),
    ) -> str:
        for language in languages:
            requested = language.lower()

            for label in self.labels:
                if (label.language or "").lower() == requested:
                    return label.value

            for label in self.labels:
                actual = (label.language or "").lower()
                if actual.startswith(requested + "-"):
                    return label.value

        for label in self.labels:
            if label.language is None:
                return label.value

        if self.labels:
            return self.labels[0].value

        fragment = self.iri.rstrip("/").rsplit("#", 1)[-1]
        fragment = fragment.rsplit("/", 1)[-1]
        return unquote(fragment or self.iri)


@dataclass
class OntologyCatalog:
    source: str
    concepts: list[OntologyConcept] = field(default_factory=list)
    ontology_iris: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def save_json(self, path: str | Path) -> Path:
        import json

        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return destination

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
