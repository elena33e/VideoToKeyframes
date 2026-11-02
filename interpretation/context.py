import hashlib
import json
from collections.abc import Collection
from dataclasses import dataclass

from .models import OntologyCatalog, OntologyText


CONTEXT_VERSION = "ontology-context-v1"
DEFAULT_MAX_CHARACTERS = 50_000


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _texts(values: list[OntologyText]) -> list[dict]:
    unique = {
        (item.value.strip(), item.language or "")
        for item in values
        if item.value.strip()
    }

    return [
        {"text": value, "language": language or None}
        for value, language in sorted(unique)
    ]


@dataclass(frozen=True)
class OntologyContext:
    text: str
    concept_iris: tuple[str, ...]
    source: str
    catalog_sha256: str
    scope: str
    warnings: tuple[str, ...]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            self.text.encode("utf-8")
        ).hexdigest()

    def to_metadata(self) -> dict:
        return {
            "version": CONTEXT_VERSION,
            "source": self.source,
            "catalog_sha256": self.catalog_sha256,
            "context_sha256": self.sha256,
            "scope": self.scope,
            "concept_iris": list(self.concept_iris),
            "concept_count": len(self.concept_iris),
            "character_count": len(self.text),
            "warnings": list(self.warnings),
            "text": self.text,
        }


def build_ontology_context(
    catalog: OntologyCatalog,
    *,
    concept_iris: Collection[str] | None = None,
    max_characters: int = DEFAULT_MAX_CHARACTERS,
) -> OntologyContext:
    """
    Construiește contextul din catalog sau dintr-o selecție explicită.

    Limita este în caractere, nu în tokeni.
    Nu trunchiază definiții și nu execută inferență OWL.
    Conceptele-părinte nu sunt adăugate automat la selecție.
    """
    if type(max_characters) is not int or max_characters <= 0:
        raise ValueError(
            "max_characters trebuie să fie un întreg pozitiv."
        )

    by_iri = {
        concept.iri: concept
        for concept in catalog.concepts
    }

    if len(by_iri) != len(catalog.concepts):
        raise ValueError(
            "Catalogul conține IRI-uri duplicate."
        )

    if concept_iris is None:
        selected = set(by_iri)
        scope = "all_catalog_concepts"
    else:
        if isinstance(concept_iris, str):
            raise ValueError(
                "concept_iris trebuie să fie o colecție de IRI-uri."
            )

        selected = set(concept_iris)

        if selected - by_iri.keys():
            raise ValueError(
                "Selecția conține concepte inexistente în catalog."
            )

        scope = "explicit_selection"

    if not selected:
        raise ValueError(
            "Contextul ontologic trebuie să conțină concepte."
        )

    records = []

    for iri in sorted(selected):
        concept = by_iri[iri]

        records.append({
            "iri": iri,
            "kinds": sorted(
                kind.value for kind in concept.kinds
            ),
            "labels": _texts(concept.labels) or [{
                "text": concept.preferred_label(),
                "language": None,
            }],
            "synonyms": _texts(concept.synonyms),
            "definitions": _texts(concept.definitions),
            "parents": sorted(set(concept.parents)),
            "types": sorted(set(concept.types)),
        })

    text = _json({"concepts": records})

    if len(text) > max_characters:
        raise ValueError(
            f"Contextul are {len(text):,} de caractere și "
            f"depășește limita locală de {max_characters:,}. "
            "Selectează mai puține concepte în tabelul ontologiei "
            "sau mărește explicit limita din context.py. "
            "Nu a fost trimis niciun apel către model."
        )

    catalog_sha256 = hashlib.sha256(
        _json(catalog.to_dict()).encode("utf-8")
    ).hexdigest()

    return OntologyContext(
        text=text,
        concept_iris=tuple(sorted(selected)),
        source=catalog.source,
        catalog_sha256=catalog_sha256,
        scope=scope,
        warnings=tuple(catalog.warnings),
    )