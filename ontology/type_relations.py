"""Relații între clase numite, fără decizii despre identitatea obiectelor."""

import re
from collections import defaultdict, deque
from dataclasses import dataclass

from rdflib import URIRef
from rdflib.namespace import OWL, RDFS

from .catalog import build_ontology_catalog
from .models import ConceptKind
from .reader import OntologySource


RELATIONS_VERSION = "named-class-paths-v1"

Statement = tuple[str, str, str]


@dataclass(frozen=True)
class RelationStep:
    statement: Statement
    reverse: bool = False

    @property
    def start(self) -> str:
        return (
            self.statement[2]
            if self.reverse
            else self.statement[0]
        )

    @property
    def end(self) -> str:
        return (
            self.statement[0]
            if self.reverse
            else self.statement[2]
        )


@dataclass(frozen=True)
class TypeRelationReport:
    left_iri: str
    right_iri: str
    left_known: bool
    right_known: bool
    left_to_right: tuple[RelationStep, ...] | None
    right_to_left: tuple[RelationStep, ...] | None
    declared_disjoint: tuple[Statement, ...]
    ontology_source: str
    ontology_source_sha256: str
    imports_not_loaded: tuple[str, ...]
    warnings: tuple[str, ...]
    relations_version: str = RELATIONS_VERSION

    @property
    def same_iri(self) -> bool:
        return self.left_iri == self.right_iri


class ClassRelationIndex:
    """Examinează relații între clasele numite recunoscute de catalog.

    Căile folosesc subClassOf înainte și equivalentClass în ambele sensuri.
    None înseamnă că nu s-a găsit o cale în fragmentul examinat.
    Calea goală reprezintă incluziunea reflexivă a unei clase recunoscute.

    declared_disjoint păstrează numai declarațiile binare directe.
    Nu implementează raționament OWL complet sau politica de identitate.
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

        edges: dict[str, set[RelationStep]] = defaultdict(set)
        disjoint: set[Statement] = set()
        ignored = 0

        for predicate in (
            RDFS.subClassOf,
            OWL.equivalentClass,
            OWL.disjointWith,
        ):
            for subject, obj in source.graph.subject_objects(
                predicate
            ):
                if (
                    not isinstance(subject, URIRef)
                    or not isinstance(obj, URIRef)
                    or str(subject) not in self._classes
                    or str(obj) not in self._classes
                ):
                    ignored += 1
                    continue

                statement = (
                    str(subject),
                    str(predicate),
                    str(obj),
                )

                if predicate == OWL.disjointWith:
                    disjoint.add(statement)
                    continue

                step = RelationStep(statement)
                edges[step.start].add(step)

                if predicate == OWL.equivalentClass:
                    reverse = RelationStep(
                        statement,
                        reverse=True,
                    )
                    edges[reverse.start].add(reverse)

        self._edges = {
            node: tuple(
                sorted(
                    steps,
                    key=lambda step: (
                        step.end,
                        step.statement,
                        step.reverse,
                    ),
                )
            )
            for node, steps in edges.items()
        }

        self._disjoint = frozenset(disjoint)

        if ignored:
            self._warnings += (
                f"{ignored} relații nu au fost parcurse: "
                "expresii anonime sau termeni nerecunoscuți "
                "drept clase numite de catalog.",
            )

    def _path(
        self,
        start: str,
        target: str,
    ) -> tuple[RelationStep, ...] | None:
        pending: deque[
            tuple[str, tuple[RelationStep, ...]]
        ] = deque([(start, ())])

        visited = {start}

        while pending:
            node, path = pending.popleft()

            if node == target:
                return path

            for step in self._edges.get(node, ()):
                if step.end not in visited:
                    visited.add(step.end)
                    pending.append(
                        (step.end, path + (step,))
                    )

        return None

    def inspect(
        self,
        left_iri: str,
        right_iri: str,
    ) -> TypeRelationReport:
        for iri in (left_iri, right_iri):
            if (
                not isinstance(iri, str)
                or not re.fullmatch(
                    r"[A-Za-z][A-Za-z0-9+.-]*:[^\s]+",
                    iri,
                )
            ):
                raise ValueError(
                    "Clasele trebuie indicate prin IRI-uri absolute."
                )

        left = str(left_iri)
        right = str(right_iri)

        left_known = left in self._classes
        right_known = right in self._classes
        both_known = left_known and right_known

        pairs = {
            (left, right),
            (right, left),
        }

        return TypeRelationReport(
            left_iri=left,
            right_iri=right,
            left_known=left_known,
            right_known=right_known,
            left_to_right=(
                self._path(left, right)
                if both_known
                else None
            ),
            right_to_left=(
                self._path(right, left)
                if both_known
                else None
            ),
            declared_disjoint=tuple(
                sorted(
                    statement
                    for statement in self._disjoint
                    if (
                        statement[0],
                        statement[2],
                    ) in pairs
                )
            ),
            ontology_source=self._source,
            ontology_source_sha256=self._source_sha256,
            imports_not_loaded=self._imports,
            warnings=self._warnings,
        )