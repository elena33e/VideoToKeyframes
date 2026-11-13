"""Copia de lucru a unui graf și istoricul modificărilor."""

from dataclasses import dataclass

from rdflib import Graph, OWL, RDF, URIRef


Relation = tuple[URIRef, URIRef, URIRef]


@dataclass(frozen=True)
class TripleChange:
    removed: Relation
    added: Relation | None = None


class GraphRevision:
    def __init__(
        self,
        candidate: Graph,
        *,
        allowed_classes: frozenset[URIRef] = frozenset(),
    ) -> None:
        self.allowed_classes = allowed_classes
        self.graph = Graph(identifier=candidate.identifier)
        self.graph += candidate
        self._history: list[TripleChange] = []

    @property
    def can_undo(self) -> bool:
        return bool(self._history)

    def remove_relation(self, relation: Relation) -> bool:
        if relation[1] == RDF.type:
            return False
        return self._apply_change(TripleChange(removed=relation))

    def replace_relation_target(self, relation: Relation, target: URIRef) -> bool:
        subject, predicate, _ = relation
        if (
            predicate == RDF.type
            or not isinstance(target, URIRef)
            or not any(self.graph.objects(target, RDF.type))
        ):
            return False

        return self._apply_change(
            TripleChange(removed=relation, added=(subject, predicate, target))
        )

    def replace_type(
        self, individual: URIRef, old_class: URIRef, new_class: URIRef
    ) -> bool:
        if old_class == OWL.NamedIndividual or new_class not in self.allowed_classes:
            return False

        return self._apply_change(TripleChange(
            removed=(individual, RDF.type, old_class),
            added=(individual, RDF.type, new_class),
        ))

    def _apply_change(self, change: TripleChange) -> bool:
        if change.removed not in self.graph:
            return False
        if change.added is not None and change.added in self.graph:
            return False

        self.graph.remove(change.removed)
        if change.added is not None:
            self.graph.add(change.added)
        self._history.append(change)
        return True

    def undo(self) -> bool:
        if not self._history:
            return False

        change = self._history[-1]
        if change.added is not None:
            self.graph.remove(change.added)
        self.graph.add(change.removed)
        self._history.pop()
        return True