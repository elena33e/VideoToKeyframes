"""Înregistrarea selecțiilor din rapoartele de populare în context."""

from collections.abc import Mapping
from typing import Any

from rdflib import Literal, URIRef

from ontology.reader import OntologySource
from session_context.characteristics.graph import (
    CTX,
    SelectionProvenance,
    record_characteristic_selection,
)
from session_context.characteristics.selection import (
    CharacteristicSelectionProposal,
)
from session_context.graph import snapshot_session_context
from session_context.models import SessionContext


def _mapping(value: Any, label: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} trebuie să fie un obiect JSON.")
    return value


def record_population_report(
    context: SessionContext,
    report: Mapping[str, Any],
    *,
    ontology_source: OntologySource,
) -> dict[str, URIRef]:
    """Verifică grupul și înregistrează selecțiile sale.

    Returnează identificatorul înregistrării pentru fiecare analiză.
    Rapoartele vechi fără selecție nu creează înregistrări.

    Funcția trebuie apelată fără modificări concurente ale contextului.
    """
    records: dict[str, URIRef] = {}

    try:
        report = _mapping(report, "Raportul")

        if report["ontology_source_sha256"] != ontology_source.source_sha256:
            raise ValueError(
                "Ontologia raportului diferă de sursa încărcată."
            )

        if (
            "session_id" in report
            and report["session_id"] != context.session_id
        ):
            raise ValueError("Raportul aparține altei sesiuni.")

        sources = _mapping(report["sources"], "Sursele raportului")
        graphs = _mapping(report["graphs"], "Grafurile raportului")

        if sources.keys() != graphs.keys():
            raise ValueError(
                "Raportul are grafuri fără sursă sau surse fără graf."
            )

        prepared = snapshot_session_context(context)

        for analysis_id, candidate in graphs.items():
            candidate = _mapping(candidate, "Rezultatul unei analize")
            selection_document = candidate.get(
                "characteristic_selection"
            )

            # Compatibilitate cu rapoartele anterioare selecției.
            if selection_document is None:
                continue

            source = _mapping(
                sources[analysis_id], "Sursa unei analize"
            )
            metadata = _mapping(
                candidate.get("population_provenance", report),
                "Proveniența populării",
            )
            context_metadata = _mapping(
                metadata["context_provenance"],
                "Proveniența contextului",
            )
            document = _mapping(
                candidate["jsonld"], "Graful candidat"
            )

            provenance = SelectionProvenance(
                session_id=context_metadata["session_id"],
                observations_sha256=(
                    context_metadata["observations_sha256"]
                ),
                observations_turtle_sha256=(
                    context_metadata["observations_turtle_sha256"]
                ),
                identities_turtle_sha256=(
                    context_metadata["identities_turtle_sha256"]
                ),
                frame_id=source["frame_id"],
                analysis_id=analysis_id,
                population_graph_iri=document["@id"],
                provider=metadata["provider"],
                model=metadata["model"],
                prompt_version=metadata["prompt_version"],
                message_id=metadata["message_id"],
                ontology_turtle_sha256=(
                    metadata["ontology_turtle_sha256"]
                ),
            )

            frame = prepared.frame_iris.get(provenance.frame_id)
            if frame is None:
                raise ValueError(
                    "Cadrul raportului nu există în context."
                )

            analyses = set(prepared.observations.objects(
                frame, CTX.observation
            ))
            if len(analyses) != 1:
                raise ValueError(
                    "Cadrul trebuie să aibă o singură analiză."
                )

            analysis = next(iter(analyses))
            if (
                not isinstance(analysis, URIRef)
                or set(prepared.observations.objects(
                    analysis, CTX.imageSha256
                )) != {Literal(source["image_sha256"])}
            ):
                raise ValueError(
                    "Imaginea sursă nu corespunde contextului."
                )

            proposal = CharacteristicSelectionProposal.model_validate(
                selection_document
            )
            records[analysis_id] = record_characteristic_selection(
                prepared,
                proposal,
                provenance=provenance,
                ontology=ontology_source.graph,
            )

    except (KeyError, TypeError) as exc:
        raise ValueError(
            "Raportul nu conține toate datele necesare "
            "înregistrării selecției."
        ) from exc

    # Ajungem aici numai după verificarea întregului grup.
    for record in records.values():
        target = context.dataset.graph(record)
        for triple in prepared.dataset.graph(record):
            target.add(triple)

    return records