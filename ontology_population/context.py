"""Înregistrarea selecțiilor din rapoartele de populare în context."""

from collections.abc import Mapping
from typing import Any

from rdflib import Literal, URIRef

from ontology.reader import OntologySource
from session_context.characteristics.graph import (
    CTX,
    record_characteristic_selection,
)
from session_context.characteristics.selection import (
    CharacteristicSelectionProposal,
)
from session_context.graph import snapshot_session_context
from session_context.models import SessionContext
from session_context.identity.analysis import IdentityAnalysisProposal
from session_context.identity.analysis_graph import (
    record_identity_analysis,
)
from session_context.population_provenance import PopulationProvenance


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
    """Verifică grupul și păstrează propunerile sale în context.

    Returnează identificatorii selecțiilor caracteristicilor, pentru
    compatibilitate cu apelanții existenți. Analizele identității
    pot fi enumerate prin read_identity_analyses().

    Rapoartele vechi fără propuneri nu creează înregistrări.
    Funcția trebuie apelată fără modificări concurente ale contextului.
    """
    records: dict[str, URIRef] = {}
    prepared_records: set[URIRef] = set()

    try:
        report = _mapping(report, "Raportul")

        if (
            report["ontology_source_sha256"]
            != ontology_source.source_sha256
        ):
            raise ValueError(
                "Ontologia raportului diferă de sursa încărcată."
            )

        if (
            "session_id" in report
            and report["session_id"] != context.session_id
        ):
            raise ValueError(
                "Raportul aparține altei sesiuni."
            )

        sources = _mapping(
            report["sources"],
            "Sursele raportului",
        )
        graphs = _mapping(
            report["graphs"],
            "Grafurile raportului",
        )

        if sources.keys() != graphs.keys():
            raise ValueError(
                "Raportul are grafuri fără sursă sau surse fără graf."
            )

        prepared = snapshot_session_context(context)

        for analysis_id, candidate in graphs.items():
            candidate = _mapping(
                candidate,
                "Rezultatul unei analize",
            )
            selection_document = candidate.get(
                "characteristic_selection"
            )
            identity_document = candidate.get(
                "identity_analysis"
            )

            # Rapoartele vechi pot să nu conțină aceste propuneri.
            if (
                selection_document is None
                and identity_document is None
            ):
                continue

            source = _mapping(
                sources[analysis_id],
                "Sursa unei analize",
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
                candidate["jsonld"],
                "Graful candidat",
            )

            provenance = PopulationProvenance(
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

            frame = prepared.frame_iris.get(
                provenance.frame_id
            )
            if frame is None:
                raise ValueError(
                    "Cadrul raportului nu există în context."
                )

            analyses = set(
                prepared.observations.objects(
                    frame,
                    CTX.observation,
                )
            )
            if len(analyses) != 1:
                raise ValueError(
                    "Cadrul trebuie să aibă o singură analiză."
                )

            analysis = next(iter(analyses))
            if (
                not isinstance(analysis, URIRef)
                or set(
                    prepared.observations.objects(
                        analysis,
                        CTX.imageSha256,
                    )
                ) != {Literal(source["image_sha256"])}
            ):
                raise ValueError(
                    "Imaginea sursă nu corespunde contextului."
                )

            if selection_document is not None:
                proposal = (
                    CharacteristicSelectionProposal.model_validate(
                        selection_document
                    )
                )
                record = record_characteristic_selection(
                    prepared,
                    proposal,
                    provenance=provenance,
                    ontology=ontology_source.graph,
                )
                records[analysis_id] = record
                prepared_records.add(record)

            if identity_document is not None:
                identity_proposal = (
                    IdentityAnalysisProposal.model_validate(
                        identity_document
                    )
                )
                record = record_identity_analysis(
                    prepared,
                    identity_proposal,
                    provenance=provenance,
                    ontology=ontology_source.graph,
                )
                prepared_records.add(record)

    except (KeyError, TypeError) as exc:
        raise ValueError(
            "Raportul nu conține toate datele necesare "
            "înregistrării propunerilor."
        ) from exc

    # Transferăm propunerile numai după verificarea întregului grup.
    for record in sorted(prepared_records, key=str):
        target = context.dataset.graph(record)
        for triple in prepared.dataset.graph(record):
            target.add(triple)

    return records