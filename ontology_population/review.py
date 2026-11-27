"""Datele folosite de interfața de revizie a grafurilor candidate."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rdflib import Dataset, Graph, OWL, RDF, URIRef
from rdflib.util import guess_format
from rdflib.term import Node

from ontology.reader import OntologySource, read_ontology_source

from .validation import validate_candidate
import unicodedata

from ontology.catalog import build_ontology_catalog
from ontology.models import ConceptKind, OntologyConcept
from session_context.characteristics.selection import CharacteristicSelectionProposal
from session_context.identity.analysis import IdentityAnalysisProposal

REVIEW_REPORT_VERSION = 1

@dataclass(frozen=True)
class ReviewFrame:
    analysis_id: str
    frame_id: str
    image_path: Path | None
    observation: dict[str, Any]
    graph: Graph
    session_id: str
    image_sha256: str
    ontology_source_sha256: str
    entity_iris_by_source_id: dict[str, str]
    population_provenance: dict[str, Any]
    vocabulary_issues: tuple[str, ...] | None = None
    ontology_classes: tuple[OntologyConcept, ...] = ()
    characteristic_selection: dict[str, Any] | None = None
    identity_analysis: dict[str, Any] | None = None

@dataclass(frozen=True)
class ReviewOntology:
    source_sha256: str
    classes: tuple[OntologyConcept, ...]
    iris: frozenset[URIRef]
    named_individuals: frozenset[Node]


def prepare_review_ontology(source: OntologySource) -> ReviewOntology:
    catalog = build_ontology_catalog(source, include_individuals=False)
    return ReviewOntology(
        source_sha256=source.source_sha256,
        classes=tuple(
            concept for concept in catalog.concepts
            if ConceptKind.CLASS in concept.kinds
        ),
        iris=frozenset(
            term for triple in source.graph for term in triple
            if isinstance(term, URIRef)
        ),
        named_individuals=frozenset(
            source.graph.subjects(RDF.type, OWL.NamedIndividual)
        ),
    )


def load_review_frames(
    session_path: Path,
    report_path: Path,
    *,
    ontology_path: Path | None = None,
) -> list[ReviewFrame]:
    session = json.loads(session_path.read_text(encoding="utf-8-sig"))
    report = json.loads(report_path.read_text(encoding="utf-8-sig"))

    review_ontology = None
    if ontology_path is not None:
        rdf_format = guess_format(ontology_path.name)
        if rdf_format is None:
            raise ValueError("Formatul ontologiei nu poate fi dedus din extensie.")
        source = read_ontology_source(ontology_path, rdf_format=rdf_format)
        review_ontology = prepare_review_ontology(source)

    return build_review_frames(session, report, review_ontology=review_ontology)

def build_review_frames(
    session: dict[str, Any],
    report: dict[str, Any],
    *,
    review_ontology: ReviewOntology | None = None
) -> list[ReviewFrame]:
    if "review_version" in report:
        if report["review_version"] != REVIEW_REPORT_VERSION:
            raise ValueError("Versiune necunoscută a raportului de revizie.")
        if report["session_id"] != session["session_id"]:
            raise ValueError("Raportul de revizie aparține altei sesiuni.")

    if (
            review_ontology is not None
            and review_ontology.source_sha256 != report["ontology_source_sha256"]
    ):
        raise ValueError("Ontologia aleasă diferă de cea folosită la populare.")

    ontology_classes = review_ontology.classes if review_ontology is not None else ()

    observations = {
        observation["analysis_id"]: observation
        for frame in session["frames"]
        if (observation := frame["observation"]) is not None
    }
    image_paths = {
        frame["frame_id"]: Path(frame["image_path"])
        for frame in session["imported_frames"]
    }
    if (extraction := session.get("extraction")) is not None:
        output_dir = Path(extraction["output_dir"])
        image_paths.update({
            frame["frame_id"]: output_dir / frame["image_path"]
            for scene in extraction["scenes"]
            if scene["status"] == "success"
            for frame in scene["frames"]
        })

    sources = report["sources"]
    graphs = report["graphs"]
    if sources.keys() != graphs.keys():
        raise ValueError("Raportul are grafuri fără sursă sau surse fără graf.")

    frames = []
    batch_provenance = {
        key: report[key]
        for key in (
            "provider", "requested_model", "model", "prompt_version",
            "message_id", "ontology_turtle_sha256", "usage", "context_provenance",
        )
        if key in report
    }

    for analysis_id, candidate in graphs.items():
        source = sources[analysis_id]
        observation = observations.get(analysis_id)
        if (
            observation is None
            or observation["frame_id"] != source["frame_id"]
            or observation["image_sha256"] != source["image_sha256"]
        ):
            raise ValueError(f"Exportul nu corespunde observației {analysis_id}.")

        document = candidate["jsonld"]
        dataset = Dataset().parse(data=json.dumps(document), format="json-ld")
        graph = dataset.graph(URIRef(document["@id"]))
        issues = None
        if review_ontology is not None:
            issues = tuple(validate_candidate(
                graph,
                ontology_iris=review_ontology.iris,
                known_individuals=review_ontology.named_individuals,
            ))

        selection_document = candidate.get(
            "characteristic_selection"
        )
        selection = (
            CharacteristicSelectionProposal.model_validate(
                selection_document
            ).model_dump(mode="json")
            if selection_document is not None
            else None
        )

        identity_document = candidate.get("identity_analysis")
        identity_analysis = (
            IdentityAnalysisProposal.model_validate(
                identity_document
            ).model_dump(mode="json")
            if identity_document is not None
            else None
        )

        frames.append(ReviewFrame(
            analysis_id=analysis_id,
            frame_id=source["frame_id"],
            image_path=image_paths.get(source["frame_id"]),
            observation=observation["observation"],
            graph=graph,
            session_id=session["session_id"],
            image_sha256=source["image_sha256"],
            ontology_source_sha256=report["ontology_source_sha256"],
            entity_iris_by_source_id=candidate.get("entity_iris_by_source_id", {}),
            population_provenance=candidate.get(
                "population_provenance", batch_provenance
            ),
            vocabulary_issues=issues,
            ontology_classes=ontology_classes,
            characteristic_selection=selection,
            identity_analysis=identity_analysis,
        ))

    return frames


def individuals_by_class(graph: Graph) -> dict[URIRef, set[URIRef]]:
    groups: dict[URIRef, set[URIRef]] = {}
    for individual, class_iri in graph.subject_objects(RDF.type):
        if (
            isinstance(individual, URIRef)
            and isinstance(class_iri, URIRef)
            and class_iri != OWL.NamedIndividual
        ):
            groups.setdefault(class_iri, set()).add(individual)
    return groups

def search_classes(
    classes: tuple[OntologyConcept, ...], query: str
) -> list[OntologyConcept]:
    def normalize(text: str) -> str:
        return "".join(
            char for char in unicodedata.normalize("NFKD", text.casefold())
            if not unicodedata.combining(char)
        ).replace("_", " ").replace("-", " ")

    words = normalize(query).split()
    if not words:
        return []

    matches = []
    for concept in classes:
        names = [concept.iri, *(label.value for label in concept.labels)]
        names.extend(synonym.value for synonym in concept.synonyms)
        if any(all(word in name for word in words) for name in map(normalize, names)):
            matches.append(concept)

    return matches