"""Verificări RDF pentru grafurile candidate."""

from rdflib import Graph, OWL, RDF, RDFS, URIRef


def validate_candidate(candidate: Graph, ontology: Graph) -> list[str]:
    issues: list[str] = []
    ontology_iris = {
        term for triple in ontology for term in triple if isinstance(term, URIRef)
    }
    known_individuals = set(ontology.subjects(RDF.type, OWL.NamedIndividual))

    prefix = f"{candidate.identifier}:instance:"
    subjects = set(candidate.subjects())
    generated = {
        iri for iri in subjects
        if isinstance(iri, URIRef) and str(iri).startswith(prefix)
    }

    predicates = set(candidate.predicates()) - {RDF.type, RDFS.label}
    for iri in sorted(predicates - ontology_iris):
        issues.append(f"Proprietate absentă din ontologie: {iri}")

    types = set(candidate.objects(None, RDF.type)) - {OWL.NamedIndividual}
    for term in sorted(types - ontology_iris):
        issues.append(f"Tip absent din ontologie: {term}")

    targets = {
        target for _, predicate, target in candidate
        if predicate != RDF.type and isinstance(target, URIRef)
    }
    for term in sorted((subjects | targets) - generated - known_individuals):
        issues.append(f"Individ fără IRI recunoscut în acest graf: {term}")

    return issues