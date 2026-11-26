"""Propuneri lexicale de clase, fără decizii de identitate."""

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal as MatchLiteral
from unicodedata import normalize

from rdflib.namespace import SKOS

from .catalog import (
    LABEL_PREDICATES,
    OBO_IN_OWL,
    build_ontology_catalog,
)
from .models import ConceptKind
from .reader import OntologySource


ALIGNMENT_VERSION = "lexical-class-v1"

EXACT_SYNONYM_PREDICATES = {
    str(SKOS.altLabel),
    str(OBO_IN_OWL.hasExactSynonym),
}

MatchMethod = MatchLiteral[
    "iri",
    "label",
    "exact_synonym",
    "local_name",
]

ProposalStatus = MatchLiteral[
    "unmapped",
    "unique",
    "ambiguous",
]


def _text_key(value: str) -> str:
    return " ".join(normalize("NFC", value).split()).casefold()


@dataclass(frozen=True)
class AlignmentEvidence:
    method: MatchMethod
    value: str
    predicate: str | None = None
    language: str | None = None


@dataclass(frozen=True)
class ClassCandidate:
    class_iri: str
    evidence: tuple[AlignmentEvidence, ...]


@dataclass(frozen=True)
class ClassAlignmentProposal:
    query: str
    candidates: tuple[ClassCandidate, ...]
    ontology_source: str
    ontology_source_sha256: str
    imports_not_loaded: tuple[str, ...]
    warnings: tuple[str, ...]
    alignment_version: str = ALIGNMENT_VERSION

    @property
    def status(self) -> ProposalStatus:
        if not self.candidates:
            return "unmapped"

        if len(self.candidates) == 1:
            return "unique"

        return "ambiguous"


class ClassAligner:
    """Index local al claselor recunoscute de catalog.

    Potrivirea textuală folosește NFC, spații normalizate și casefold.
    IRI-urile complete se compară exact, fără normalizare.
    Un rezultat unic este o propunere lexicală, nu o clasificare validată.
    """

    def __init__(self, source: OntologySource):
        catalog = build_ontology_catalog(
            source,
            include_individuals=False,
        )

        self._source = str(source.path)
        self._source_sha256 = source.source_sha256
        self._imports = tuple(sorted(catalog.imports))
        self._warnings = tuple(catalog.warnings)

        self._classes = frozenset(
            concept.iri
            for concept in catalog.concepts
            if ConceptKind.CLASS in concept.kinds
        )

        self._terms: dict[
            str,
            list[tuple[str, AlignmentEvidence]],
        ] = defaultdict(list)

        label_predicates = {
            str(predicate)
            for predicate in LABEL_PREDICATES
        }

        for concept in catalog.concepts:
            if concept.iri not in self._classes:
                continue

            for text in concept.labels:
                if text.predicate in label_predicates:
                    self._add(
                        concept.iri,
                        AlignmentEvidence(
                            method="label",
                            value=text.value,
                            predicate=text.predicate,
                            language=text.language,
                        ),
                    )

            for text in concept.synonyms:
                if text.predicate in EXACT_SYNONYM_PREDICATES:
                    self._add(
                        concept.iri,
                        AlignmentEvidence(
                            method="exact_synonym",
                            value=text.value,
                            predicate=text.predicate,
                            language=text.language,
                        ),
                    )

            # Fallback-ul lexical folosit de prompt pentru clase fără etichete.
            # Nu decodăm sau interpretăm sensul identificatorului.
            if not concept.labels:
                local = (
                    concept.iri
                    .rsplit("#", 1)[-1]
                    .rsplit("/", 1)[-1]
                    .rsplit(":", 1)[-1]
                )

                if local:
                    self._add(
                        concept.iri,
                        AlignmentEvidence(
                            method="local_name",
                            value=local,
                        ),
                    )

    def _add(
        self,
        class_iri: str,
        evidence: AlignmentEvidence,
    ) -> None:
        self._terms[_text_key(evidence.value)].append(
            (class_iri, evidence)
        )

    def propose(
        self,
        query: str,
        *,
        language: str | None = None,
    ) -> ClassAlignmentProposal:
        """language este un tag de limbă, de exemplu ro sau en.

        Când limba este specificată, sunt admise textele cu acel tag exact
        și textele fără tag. Fără filtru, păstrăm toate limbile.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError(
                "Denumirea pentru aliniere trebuie să fie text nevid."
            )

        if language is not None and (
            not isinstance(language, str)
            or not language.strip()
        ):
            raise ValueError(
                "Limba trebuie să fie un tag nevid sau None."
            )

        raw = query.strip()

        matches: dict[
            str,
            list[AlignmentEvidence],
        ] = defaultdict(list)

        if raw in self._classes:
            matches[raw].append(
                AlignmentEvidence(
                    method="iri",
                    value=raw,
                )
            )

        elif not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9+.-]*:[^\s]+",
            raw,
        ):
            requested = (
                language.strip().casefold()
                if language is not None
                else None
            )

            for class_iri, evidence in self._terms.get(
                _text_key(raw),
                (),
            ):
                if (
                    requested is None
                    or evidence.language is None
                    or evidence.language.casefold() == requested
                ):
                    matches[class_iri].append(evidence)

        candidates = tuple(
            ClassCandidate(
                class_iri=class_iri,
                evidence=tuple(
                    dict.fromkeys(matches[class_iri])
                ),
            )
            for class_iri in sorted(matches)
        )

        return ClassAlignmentProposal(
            query=query,
            candidates=candidates,
            ontology_source=self._source,
            ontology_source_sha256=self._source_sha256,
            imports_not_loaded=self._imports,
            warnings=self._warnings,
        )