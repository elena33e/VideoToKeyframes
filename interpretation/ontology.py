from collections import defaultdict
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS

from .models import (
    ConceptKind,
    OntologyCatalog,
    OntologyConcept,
    OntologyText,
)


OBO = Namespace("http://purl.obolibrary.org/obo/")
OBO_IN_OWL = Namespace(
    "http://www.geneontology.org/formats/oboInOwl#"
)

LABEL_PREDICATES = (
    SKOS.prefLabel,
    RDFS.label,
)

SYNONYM_PREDICATES = (
    SKOS.altLabel,
    OBO_IN_OWL.hasExactSynonym,
    OBO_IN_OWL.hasRelatedSynonym,
    OBO_IN_OWL.hasBroadSynonym,
    OBO_IN_OWL.hasNarrowSynonym,
)

DEFINITION_PREDICATES = (
    SKOS.definition,
    OBO.IAO_0000115,
    DCTERMS.description,
    RDFS.comment,
)

FORMATS_BY_SUFFIX = {
    ".owl": "xml",
    ".rdf": "xml",
    ".xml": "xml",
    ".ttl": "turtle",
    ".n3": "n3",
    ".nt": "nt",
    ".jsonld": "json-ld",
    ".json-ld": "json-ld",
}

BUILTIN_CLASSES = {
    OWL.Thing,
    OWL.Nothing,
    RDFS.Resource,
}


def _extract_texts(
    graph: Graph,
    subject: URIRef,
    predicates: tuple[URIRef, ...],
) -> list[OntologyText]:
    """Păstrează limba și proprietatea din care provine fiecare text."""

    texts = []
    seen = set()

    for predicate in predicates:
        values = [
            value
            for value in graph.objects(subject, predicate)
            if isinstance(value, Literal)
            and str(value).strip()
        ]

        # Ordine stabilă pentru exporturi reproductibile.
        values.sort(
            key=lambda value: (
                value.language or "",
                str(value),
                str(value.datatype or ""),
            )
        )

        for value in values:
            text = OntologyText(
                value=str(value),
                language=value.language,
                predicate=str(predicate),
            )
            if text not in seen:
                seen.add(text)
                texts.append(text)

    return texts


def _find_concept_kinds(
    graph: Graph,
    include_individuals: bool,
) -> dict[URIRef, set[ConceptKind]]:
    kinds = defaultdict(set)

    for class_type in (OWL.Class, RDFS.Class):
        for subject in graph.subjects(RDF.type, class_type):
            if isinstance(subject, URIRef):
                kinds[subject].add(ConceptKind.CLASS)

    # Recunoaștem și clasele folosite în ierarhie,
    # chiar dacă nu au declarația explicită owl:Class.
    for child, parent in graph.subject_objects(RDFS.subClassOf):
        for node in (child, parent):
            if isinstance(node, URIRef):
                kinds[node].add(ConceptKind.CLASS)

    for subject in graph.subjects(RDF.type, SKOS.Concept):
        if isinstance(subject, URIRef):
            kinds[subject].add(ConceptKind.SKOS_CONCEPT)

    for predicate in (SKOS.broader, SKOS.narrower):
        for first, second in graph.subject_objects(predicate):
            for node in (first, second):
                if isinstance(node, URIRef):
                    kinds[node].add(ConceptKind.SKOS_CONCEPT)

    for iri in BUILTIN_CLASSES:
        kinds.pop(iri, None)

    if include_individuals:
        known_classes = {
            iri
            for iri, roles in kinds.items()
            if ConceptKind.CLASS in roles
        }

        for subject, declared_type in graph.subject_objects(RDF.type):
            if not isinstance(subject, URIRef):
                continue

            if (
                declared_type == OWL.NamedIndividual
                or declared_type in known_classes
            ):
                kinds[subject].add(ConceptKind.INDIVIDUAL)

    return dict(kinds)


def _extract_parents(
    graph: Graph,
    subject: URIRef,
) -> list[str]:
    parents = set()

    for predicate in (RDFS.subClassOf, SKOS.broader):
        for parent in graph.objects(subject, predicate):
            if isinstance(parent, URIRef):
                parents.add(str(parent))

    # A skos:narrower B exprimă că A este mai general decât B.
    for parent in graph.subjects(SKOS.narrower, subject):
        if isinstance(parent, URIRef):
            parents.add(str(parent))

    return sorted(parents)


def load_ontology(
    path: str | Path,
    *,
    rdf_format: str | None = None,
    include_individuals: bool = True,
) -> OntologyCatalog:
    """
    Încarcă o ontologie locală și construiește catalogul.

    Pentru .owl se presupune RDF/XML. Dacă fișierul conține Turtle,
    transmite rdf_format="turtle".

    Nu încarcă automat owl:imports și nu execută inferență.
    Expresiile OWL anonime nu sunt transformate în concepte.
    """

    source = Path(path).expanduser().resolve()

    if not source.is_file():
        raise FileNotFoundError(
            f"Fișierul ontologiei nu există: {source}"
        )

    if source.stat().st_size == 0:
        raise ValueError(
            f"Fișierul ontologiei este gol: {source}"
        )

    selected_format = rdf_format or FORMATS_BY_SUFFIX.get(
        source.suffix.lower()
    )

    if selected_format is None:
        raise ValueError(
            f"Extensie nerecunoscută: {source.suffix}. "
            "Specifică explicit rdf_format. "
            "Fișierele OBO și OWL/XML necesită conversie în RDF."
        )

    graph = Graph()

    try:
        graph.parse(
            source=str(source),
            format=selected_format,
        )
    except Exception as exc:
        raise ValueError(
            f"Ontologia nu a putut fi citită ca "
            f"{selected_format}: {source}. Detalii: {exc}"
        ) from exc

    concept_kinds = _find_concept_kinds(
        graph,
        include_individuals,
    )

    concepts = []

    for iri in sorted(concept_kinds, key=str):
        concepts.append(
            OntologyConcept(
                iri=str(iri),
                kinds=sorted(
                    concept_kinds[iri],
                    key=lambda kind: kind.value,
                ),
                labels=_extract_texts(
                    graph, iri, LABEL_PREDICATES
                ),
                synonyms=_extract_texts(
                    graph, iri, SYNONYM_PREDICATES
                ),
                definitions=_extract_texts(
                    graph, iri, DEFINITION_PREDICATES
                ),
                parents=_extract_parents(graph, iri),
                types=sorted({
                    str(value)
                    for value in graph.objects(iri, RDF.type)
                    if isinstance(value, URIRef)
                }),
            )
        )

    ontology_iris = sorted({
        str(subject)
        for subject in graph.subjects(RDF.type, OWL.Ontology)
        if isinstance(subject, URIRef)
    })

    imports = sorted({
        str(value)
        for value in graph.objects(None, OWL.imports)
        if isinstance(value, URIRef)
    })

    warnings = []

    if not concepts:
        warnings.append(
            "Nu au fost identificate concepte numite "
            "prin declarațiile și relațiile suportate."
        )

    if imports:
        warnings.append(
            "Ontologia declară owl:imports. Catalogul include "
            "doar informațiile din fișierul încărcat."
        )

    if any(
        not isinstance(parent, URIRef)
        for _, parent in graph.subject_objects(RDFS.subClassOf)
    ):
        warnings.append(
            "Există superclase anonime, de exemplu restricții OWL. "
            "Acestea nu sunt incluse în lista parents."
        )

    return OntologyCatalog(
        source=str(source),
        concepts=concepts,
        ontology_iris=ontology_iris,
        imports=imports,
        warnings=warnings,
    )