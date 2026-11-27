"""Leagă aparițiile observate de propuneri lexicale și relații între clase."""

import re
from dataclasses import dataclass, replace

from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef, XSD

from interpretation.config import OBSERVATION_NAMESPACE
from ontology.alignment import ClassAligner, ClassAlignmentProposal
from ontology.reader import OntologySource
from ontology.type_relations import ClassRelationIndex, TypeRelationReport

from .graph import entities_for_frame
from .models import SessionContext


CTX = Namespace(OBSERVATION_NAMESPACE)
TYPE_ALIGNMENT_VERSION = "occurrence-type-proposals-v1"


@dataclass(frozen=True)
class OccurrenceTypeProposal:
    session_id: str
    observations_sha256: str
    frame_id: str
    occurrence_iri: URIRef
    observed_name: str
    uncertain: bool | None
    requested_language: str | None
    ontology_rdf_format: str
    alignment: ClassAlignmentProposal
    type_alignment_version: str = TYPE_ALIGNMENT_VERSION


@dataclass(frozen=True)
class OccurrenceTypeComparison:
    left: OccurrenceTypeProposal
    right: OccurrenceTypeProposal
    class_relations: tuple[TypeRelationReport, ...]


class SessionTypeMapper:
    """Produce dovezi pentru interpretare; nu clasifică definitiv obiectele.

    Construiește ambele indexuri din aceeași copie a grafului ontologiei.
    Nu modifică observațiile, identitățile sau graful sursă.
    """

    def __init__(self, source: OntologySource):
        graph = Graph()

        for triple in source.graph:
            graph.add(triple)

        snapshot = replace(source, graph=graph)
        self._ontology_graph = graph

        self._source = str(snapshot.path)
        self._source_sha256 = snapshot.source_sha256
        self._rdf_format = snapshot.rdf_format
        self._aligner = ClassAligner(snapshot)
        self._relations = ClassRelationIndex(snapshot)

    @property
    def ontology_graph(self) -> Graph:
        """Returnează o copie a ontologiei folosite de acest mapper."""
        result = Graph()
        for triple in self._ontology_graph:
            result.add(triple)
        return result

    def propose(
        self,
        context: SessionContext,
        occurrence_iri: str | URIRef,
        *,
        language: str | None = None,
    ) -> OccurrenceTypeProposal:
        if (
            not isinstance(occurrence_iri, str)
            or not re.fullmatch(
                r"[A-Za-z][A-Za-z0-9+.-]*:[^\s]+",
                occurrence_iri,
            )
        ):
            raise ValueError(
                "Apariția trebuie indicată printr-un IRI absolut."
            )

        occurrence = URIRef(occurrence_iri)
        graph = context.observations

        owners = [
            frame_id
            for frame_id in context.frame_iris
            if occurrence in entities_for_frame(context, frame_id)
        ]

        if (
            len(owners) != 1
            or (
                occurrence,
                RDF.type,
                CTX.EntityObservation,
            ) not in graph
        ):
            raise ValueError(
                "Apariția nu aparține unui singur cadru al sesiunii."
            )

        labels = set(graph.objects(occurrence, RDFS.label))

        if len(labels) != 1:
            raise ValueError(
                "Apariția trebuie să aibă un singur nume observat."
            )

        label = next(iter(labels))

        if (
            not isinstance(label, Literal)
            or not isinstance(label.toPython(), str)
            or not str(label).strip()
        ):
            raise ValueError(
                "Numele observat trebuie să fie text nevid."
            )

        markers = set(graph.objects(occurrence, CTX.uncertain))
        uncertain: bool | None = None

        if markers:
            marker = next(iter(markers))

            if (
                len(markers) != 1
                or not isinstance(marker, Literal)
                or marker.datatype != XSD.boolean
                or type(marker.toPython()) is not bool
            ):
                raise ValueError(
                    "Marcaj de incertitudine invalid."
                )

            uncertain = marker.toPython()

        name = str(label)
        alignment = self._aligner.propose(
            name,
            language=language,
        )

        return OccurrenceTypeProposal(
            session_id=context.session_id,
            observations_sha256=context.source_sha256,
            frame_id=owners[0],
            occurrence_iri=occurrence,
            observed_name=name,
            uncertain=uncertain,
            requested_language=language,
            ontology_rdf_format=self._rdf_format,
            alignment=alignment,
        )

    def compare(
        self,
        left: OccurrenceTypeProposal,
        right: OccurrenceTypeProposal,
    ) -> OccurrenceTypeComparison:
        if (
            left.session_id != right.session_id
            or left.observations_sha256
            != right.observations_sha256
        ):
            raise ValueError(
                "Propunerile provin din sesiuni sau versiuni "
                "diferite ale observațiilor."
            )

        for proposal in (left, right):
            if (
                proposal.alignment.ontology_source
                != self._source
                or proposal.alignment.ontology_source_sha256
                != self._source_sha256
                or proposal.ontology_rdf_format
                != self._rdf_format
            ):
                raise ValueError(
                    "Propunerea provine din altă sursă a ontologiei."
                )

        reports = tuple(
            self._relations.inspect(
                left_class.class_iri,
                right_class.class_iri,
            )
            for left_class in left.alignment.candidates
            for right_class in right.alignment.candidates
        )

        return OccurrenceTypeComparison(
            left=left,
            right=right,
            class_relations=reports,
        )