"""Datele contextului unei sesiuni, independente de GUI și LLM."""

from dataclasses import dataclass

from rdflib import Dataset, Graph, URIRef


@dataclass(frozen=True)
class SessionContext:
    session_id: str
    source_sha256: str
    dataset: Dataset
    observations_iri: URIRef
    frame_iris: dict[str, URIRef]

    @property
    def observations(self) -> Graph:
        return self.dataset.graph(self.observations_iri)