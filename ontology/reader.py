"""Citirea sursei RDF și păstrarea metadatelor fișierului."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from rdflib import Graph


@dataclass(frozen=True)
class OntologySource:
    path: Path
    graph: Graph
    rdf_format: str
    source_sha256: str


def read_ontology_source(
    path: str | Path,
    *,
    rdf_format: str,
    cached_source: OntologySource | None = None,
) -> OntologySource:
    source = Path(path).expanduser().resolve(strict=True)

    if not source.is_file():
        raise ValueError(f"Nu este un fișier: {source}")

    raw = source.read_bytes()

    if not raw:
        raise ValueError(f"Fișierul ontologiei este gol: {source}")

    source_hash = sha256(raw).hexdigest()

    if (
        cached_source is not None
        and cached_source.path == source
        and cached_source.rdf_format == rdf_format
        and cached_source.source_sha256 == source_hash
    ):
        return cached_source

    graph = Graph()

    try:
        graph.parse(
            data=raw,
            format=rdf_format,
            publicID=source.as_uri(),
        )
    except Exception as exc:
        raise ValueError(
            f"Ontologia nu poate fi citită ca {rdf_format}: "
            f"{source}. Detalii: {exc}"
        ) from exc

    return OntologySource(
        path=source,
        graph=graph,
        rdf_format=rdf_format,
        source_sha256=source_hash,
    )