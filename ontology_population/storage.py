"""Persistența locală a grafurilor revizuite."""

import json
from os import link
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from .review import REVIEW_REPORT_VERSION, ReviewFrame
from .revision import GraphRevision


def save_review_report(
    destination: Path,
    frames: list[ReviewFrame],
    revisions: dict[str, GraphRevision],
) -> str:
    if not frames:
        raise ValueError("Nu există grafuri de revizie de salvat.")

    session_id = frames[0].session_id
    ontology_hash = frames[0].ontology_source_sha256
    sources = {}
    graphs = {}

    for frame in frames:
        if (
            frame.session_id != session_id
            or frame.ontology_source_sha256 != ontology_hash
        ):
            raise ValueError(
                "Revizia trebuie să provină din aceeași sesiune și ontologie."
            )

        analysis_id = frame.analysis_id
        graph = revisions[analysis_id].graph

        sources[analysis_id] = {
            "frame_id": frame.frame_id,
            "image_path": str(frame.image_path) if frame.image_path else None,
            "image_sha256": frame.image_sha256,
        }
        graphs[analysis_id] = {
            "jsonld": {
                "@id": str(graph.identifier),
                "@graph": json.loads(graph.serialize(format="json-ld")),
            },
            "entity_iris_by_source_id": frame.entity_iris_by_source_id,
            "population_provenance": frame.population_provenance,
        }

    revision_id = uuid4().hex
    report = {
        "review_version": REVIEW_REPORT_VERSION,
        "revision_id": revision_id,
        "session_id": session_id,
        "ontology_source_sha256": ontology_hash,
        "sources": sources,
        "graphs": graphs,
    }
    content = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"

    temporary = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=".review_",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)

        link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    return revision_id