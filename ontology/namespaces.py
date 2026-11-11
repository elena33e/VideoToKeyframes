"""Propunerea namespace-urilor pe baza catalogului ontologiei."""

from collections import Counter

from .models import OntologyCatalog


def suggest_namespaces(catalog: OntologyCatalog) -> list[str]:
    candidates: Counter[str] = Counter()

    for concept in catalog.concepts:
        iri = concept.iri

        if "#" in iri:
            prefix = iri.rsplit("#", 1)[0] + "#"
        elif "/" in iri:
            prefix = iri.rsplit("/", 1)[0] + "/"
        else:
            continue

        if prefix.startswith(
            ("http://www.w3.org/", "https://www.w3.org/")
        ):
            continue

        candidates[prefix] += 1

    preferred = {
        iri.rstrip("#/") + suffix
        for iri in catalog.ontology_iris
        for suffix in ("#", "/")
    }

    return sorted(
        candidates,
        key=lambda namespace: (
            namespace not in preferred,
            -candidates[namespace],
            namespace,
        ),
    )