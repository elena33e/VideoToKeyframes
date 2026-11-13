"""Datele folosite de interfața de revizie a grafurilor candidate."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rdflib import Dataset, Graph, OWL, RDF, URIRef

from rdflib.util import guess_format

from ontology.reader import OntologySource, read_ontology_source

from .validation import validate_candidate
import unicodedata

from ontology.catalog import build_ontology_catalog
from ontology.models import ConceptKind, OntologyConcept


@dataclass(frozen=True)
class ReviewFrame:
    analysis_id: str
    frame_id: str
    image_path: Path | None
    observation: dict[str, Any]
    graph: Graph
    vocabulary_issues: tuple[str, ...] | None = None
    ontology_classes: tuple[OntologyConcept, ...] = ()


def load_review_frames(
    session_path: Path,
    report_path: Path,
    *,
    ontology_path: Path | None = None,
) -> list[ReviewFrame]:
    session = json.loads(session_path.read_text(encoding="utf-8-sig"))
    report = json.loads(report_path.read_text(encoding="utf-8-sig"))

    ontology_source = None
    if ontology_path is not None:
        rdf_format = guess_format(ontology_path.name)
        if rdf_format is None:
            raise ValueError("Formatul ontologiei nu poate fi dedus din extensie.")
        ontology_source = read_ontology_source(ontology_path, rdf_format=rdf_format)

    return build_review_frames(session, report, ontology_source=ontology_source)


def build_review_frames(
    session: dict[str, Any],
    report: dict[str, Any],
    *,
    ontology_source: OntologySource | None = None,
) -> list[ReviewFrame]:
    if (
        ontology_source is not None
        and ontology_source.source_sha256 != report["ontology_source_sha256"]
    ):
        raise ValueError("Ontologia aleasă diferă de cea folosită la populare.")

    ontology_classes: tuple[OntologyConcept, ...] = ()
    if ontology_source is not None:
        catalog = build_ontology_catalog(ontology_source, include_individuals=False)
        ontology_classes = tuple(
            concept for concept in catalog.concepts
            if ConceptKind.CLASS in concept.kinds
        )


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
        issues = (
            tuple(validate_candidate(graph, ontology_source.graph))
            if ontology_source is not None else None
        )
        frames.append(ReviewFrame(
            analysis_id=analysis_id,
            frame_id=source["frame_id"],
            image_path=image_paths.get(source["frame_id"]),
            observation=observation["observation"],
            graph=graph,
            vocabulary_issues=issues,
            ontology_classes=ontology_classes,
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