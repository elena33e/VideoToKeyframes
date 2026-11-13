"""Copia de lucru a unui graf și istoricul modificărilor."""

from rdflib import Graph, RDF, URIRef
from dataclasses import dataclass

Relation = tuple[URIRef, URIRef, URIRef]

@dataclass(frozen=True)
class RelationChange:
    removed: Relation
    added: Relation | None = None


class GraphRevision:
    def __init__(self, candidate: Graph) -> None:
        self.graph = Graph(identifier=candidate.identifier)
        self.graph += candidate
        self._history: list[RelationChange] = []

    @property
    def can_undo(self) -> bool:
        return bool(self._history)

    def remove_relation(self, relation: Relation) -> bool:
        return self._apply_relation_change(RelationChange(removed=relation))

    def replace_relation_target(self, relation: Relation, target: URIRef) -> bool:
        subject, predicate, _ = relation
        if not isinstance(target, URIRef) or not any(self.graph.objects(target, RDF.type)):
            return False

        return self._apply_relation_change(
            RelationChange(removed=relation, added=(subject, predicate, target))
        )

    def _apply_relation_change(self, change: RelationChange) -> bool:
        if change.removed[1] == RDF.type or change.removed not in self.graph:
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