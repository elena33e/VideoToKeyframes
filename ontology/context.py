"""Context RDF pentru interpretare vizuală; fără inferență sau apeluri AI."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.compare import to_canonical_graph
from rdflib.namespace import OWL, RDF, RDFS, SKOS, XSD

from ontology.catalog import (
    DEFINITION_PREDICATES,
    LABEL_PREDICATES,
    SYNONYM_PREDICATES,
)

from .reader import OntologySource, read_ontology_source


EXTRACTION_VERSION = "rdf-vocabulary-v2"

SWRL = Namespace("http://www.w3.org/2003/11/swrl#")
SWRL_NAMESPACES = (
    str(SWRL),
    "http://www.w3.org/2003/11/swrlb#",
    "http://swrl.stanford.edu/ontologies/3.3/swrla.owl#",
)

STANDARD_NAMESPACES = (
    str(RDF),
    str(RDFS),
    str(OWL),
    str(XSD),
    str(SKOS),
)

FORMATS = {
    ".rdf": "xml",
    ".owl": "xml",
    ".ttl": "turtle",
    ".nt": "nt",
}

# Relații structurale care pot avea ancora și în poziția de obiect.
TEXT_PREDICATES = {
    *LABEL_PREDICATES,
    *SYNONYM_PREDICATES,
    *DEFINITION_PREDICATES,
}

SIMPLE_RELATIONS = {
    RDFS.subClassOf,
    RDFS.subPropertyOf,
    RDFS.domain,
    RDFS.range,
    SKOS.broader,
    SKOS.narrower,
}

ENTITY_TYPES = {
    OWL.Class,
    RDFS.Class,
    OWL.ObjectProperty,
    OWL.DatatypeProperty,
    OWL.AnnotationProperty,
    OWL.NamedIndividual,
    RDF.Property,
    RDFS.Datatype,
    SKOS.Concept,
}

EXTERNAL_METADATA = {RDF.type, *TEXT_PREDICATES}

ADMINISTRATIVE = {
    OWL.imports,
    OWL.versionIRI,
    OWL.versionInfo,
    OWL.priorVersion,
    OWL.backwardCompatibleWith,
    OWL.incompatibleWith,
}


@dataclass(frozen=True)
class OntologyContext:
    turtle: str
    report: dict


def _is_swrl(term) -> bool:
    return (
        isinstance(term, URIRef)
        and str(term).startswith(SWRL_NAMESPACES)
    )


def _uris(graph: Graph) -> set[URIRef]:
    return {
        term
        for triple in graph
        for term in triple
        if isinstance(term, URIRef)
    }

def _keep_simple_statement(subject, predicate, obj) -> bool:
    if not isinstance(subject, URIRef):
        return False

    if predicate in TEXT_PREDICATES:
        return isinstance(obj, Literal) and bool(str(obj).strip())

    if not isinstance(obj, URIRef):
        return False

    if predicate == RDF.type:
        return (
            obj in ENTITY_TYPES
            or not str(obj).startswith(STANDARD_NAMESPACES)
        )

    return predicate in SIMPLE_RELATIONS


def _stable_turtle(graph: Graph, namespace: str) -> str:
    # Canonicalizarea elimină ID-urile aleatorii ale nodurilor anonime.
    stable = Graph(bind_namespaces="none")

    for prefix, ns in (
        ("local", namespace),
        ("rdf", RDF),
        ("rdfs", RDFS),
        ("owl", OWL),
        ("skos", SKOS),
        ("xsd", XSD),
    ):
        stable.bind(prefix, Namespace(str(ns)))

    for triple in to_canonical_graph(graph):
        stable.add(triple)

    # Alocăm prefixele suplimentare într-o ordine stabilă.
    for iri in sorted(_uris(stable), key=str):
        try:
            stable.namespace_manager.compute_qname(iri)
        except ValueError:
            pass

    return stable.serialize(format="turtle")


def extract_ontology_context(
    graph: Graph,
    namespace: str,
) -> OntologyContext:
    """Pregătește vocabularul domeniului pentru interpretarea imaginilor.

    Păstrează termeni locali, texte, tipuri și relații ierarhice simple.
    Omite expresiile OWL complexe; nu le transformă în relații directe.
    Nu efectuează inferență sau mapare și nu modifică graful sursă.
    """
    namespace = namespace.strip()

    if (
        not urlsplit(namespace).scheme
        or any(char.isspace() for char in namespace)
        or not namespace.endswith(("#", "/", ":"))
        or namespace in STANDARD_NAMESPACES
    ):
        raise ValueError(
            "Namespace-ul trebuie să fie un IRI absolut propriu, "
            "terminat cu #, / sau :."
        )

    ontology_nodes = set(
        graph.subjects(RDF.type, OWL.Ontology)
    )
    rule_nodes = set(
        graph.subjects(RDF.type, SWRL.Imp)
    )
    swrl_nodes = {
        subject
        for subject, kind in graph.subject_objects(RDF.type)
        if _is_swrl(kind)
    }
    excluded = ontology_nodes | swrl_nodes

    # Aplicăm excluderile înainte de parcurgerea structurilor anonime.
    eligible = Graph()

    for subject, predicate, obj in graph:
        if (
            subject in excluded
            or obj in excluded
            or predicate in ADMINISTRATIVE
            or any(
                _is_swrl(term)
                for term in (subject, predicate, obj)
            )
        ):
            continue

        eligible.add((subject, predicate, obj))

    anchors = {
        iri
        for iri in _uris(eligible)
        if str(iri).startswith(namespace)
    }

    if not anchors:
        raise ValueError(
            "Nu există ancore eligibile pentru namespace-ul "
            f"{namespace!r}."
        )

    context = Graph()

    for anchor in sorted(anchors, key=str):
        for predicate, obj in eligible.predicate_objects(anchor):
            if _keep_simple_statement(anchor, predicate, obj):
                context.add((anchor, predicate, obj))

        for subject, predicate in eligible.subject_predicates(anchor):
            if (
                predicate in SIMPLE_RELATIONS
                and _keep_simple_statement(subject, predicate, anchor)
            ):
                context.add((subject, predicate, anchor))

    def external_iris(current: Graph) -> set[URIRef]:
        return {
            iri
            for iri in _uris(current)
            if not str(iri).startswith(
                (namespace, *STANDARD_NAMESPACES)
            )
        }

    # Completare metadatele termenilor externi direct referiți
    # Nu parcurge restricții sau ierarhii externe
    for iri in sorted(external_iris(context), key=str):
        for predicate, obj in eligible.predicate_objects(iri):
            if (
                predicate in EXTERNAL_METADATA
                and _keep_simple_statement(iri, predicate, obj)
            ):
                context.add((iri, predicate, obj))

    external = external_iris(context)

    # Un termen poate exista numai într-o restricție omisă
    # Îl păstrăm în vocabular fără să inventăm declarații RDF
    vocabulary_only = sorted(
        str(iri) for iri in anchors - _uris(context)
    )

    without_labels = sorted(
        str(iri)
        for iri in anchors
        if not any(
            next(graph.objects(iri, predicate), None) is not None
            for predicate in LABEL_PREDICATES
        )
    )

    without_definitions = sorted(
        str(iri)
        for iri in anchors
        if not any(
            next(graph.objects(iri, predicate), None) is not None
            for predicate in DEFINITION_PREDICATES
        )
    )

    without_external_metadata = sorted(
        str(iri)
        for iri in external
        if not any(
            next(context.objects(iri, predicate), None) is not None
            for predicate in EXTERNAL_METADATA
        )
    )

    imports = sorted({
        str(iri)
        for iri in graph.objects(None, OWL.imports)
    })

    turtle = _stable_turtle(context, namespace)

    if vocabulary_only:
        turtle += "\n# Termeni locali fără afirmații simple selectate:\n"
        turtle += "".join(
            f"# <{iri}>\n" for iri in vocabulary_only
        )

    warnings = []

    if imports:
        warnings.append(
            "Importurile declarate nu au fost încărcate de modul."
        )

    if without_labels:
        warnings.append(
            "Unele ancore nu au etichete; IRI-urile sunt păstrate."
        )

    if without_definitions:
        warnings.append(
            "Unele ancore nu au definiții; nu generăm definiții."
        )

    if without_external_metadata:
        warnings.append(
            "Unele referințe externe nu au metadate în context."
        )

    if rule_nodes:
        warnings.append(
            "Regulile SWRL sunt excluse din context."
        )

    return OntologyContext(
        turtle=turtle,
        report={
            "extraction_version": EXTRACTION_VERSION,
            "context_kind": "vocabulary",
            "vocabulary_only_iris": vocabulary_only,
            "excluded_constructs": [
                "anonymous_owl_expressions",
                "logical_relations_outside_simple_selection",
                "swrl_rules",
                "administrative_metadata",
            ],
            "namespace": namespace,
            "source_triples": len(graph),
            "context_triples": len(context),
            "omitted_triples": len(graph) - len(context),
            "anchor_count": len(anchors),
            "anchor_iris": sorted(map(str, anchors)),
            "external_iris": sorted(map(str, external)),
            "anchors_without_labels": without_labels,
            "anchors_without_definitions": without_definitions,
            "external_without_metadata": without_external_metadata,
            "declared_imports": imports,
            "swrl_rules_excluded": len(rule_nodes),
            "characters": len(turtle),
            "utf8_bytes": len(turtle.encode("utf-8")),
            "context_sha256": sha256(
                turtle.encode("utf-8")
            ).hexdigest(),
            "warnings": warnings,
        },
    )


def build_ontology_context(
    path: str | Path,
    namespace: str,
    *,
    rdf_format: str | None = None,
) -> OntologyContext:
    """Încarcă sursa și pregătește contextul ontologic."""
    _, context = build_ontology_context_with_source(
        path,
        namespace,
        rdf_format=rdf_format,
    )
    return context


def build_ontology_context_with_source(
    path: str | Path,
    namespace: str,
    *,
    rdf_format: str | None = None,
    cached_source: OntologySource | None = None,
) -> tuple[OntologySource, OntologyContext]:
    """Pregătește contextul, reutilizând sursa când este actuală."""
    source = Path(path).expanduser().resolve(strict=True)

    selected_format = rdf_format or FORMATS.get(
        source.suffix.lower()
    )

    if selected_format not in FORMATS.values():
        raise ValueError(
            "Folosește RDF/XML, Turtle sau N-Triples."
        )

    loaded = read_ontology_source(
        source,
        rdf_format=selected_format,
        cached_source=cached_source,
    )

    context = build_context_from_source(
        loaded,
        namespace,
    )

    return loaded, context


def build_context_from_source(
    loaded: OntologySource,
    namespace: str,
) -> OntologyContext:
    """Pregătește contextul fără să recitească sau să reparseze sursa."""
    if loaded.rdf_format not in FORMATS.values():
        raise ValueError(
            "Folosește RDF/XML, Turtle sau N-Triples."
        )

    result = extract_ontology_context(
        loaded.graph,
        namespace,
    )

    return OntologyContext(
        turtle=result.turtle,
        report={
            **result.report,
            "source_path": str(loaded.path),
            "source_sha256": loaded.source_sha256,
            "rdf_format": loaded.rdf_format,
        },
    )