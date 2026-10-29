import argparse
import json
import sys
from pathlib import Path

from interpretation.ontology import load_ontology


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Încarcă o ontologie și exportă catalogul "
            "de concepte în JSON."
        )
    )

    parser.add_argument(
        "ontology",
        type=Path,
        help="Calea fișierului ontologiei.",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/ontology_catalog.json"),
        help=(
            "Destinația catalogului JSON. "
            "Implicit: output/ontology_catalog.json. "
            "Un catalog existent la această cale va fi înlocuit."
        ),
    )

    parser.add_argument(
        "--format",
        dest="rdf_format",
        choices=("xml", "turtle", "n3", "nt", "json-ld"),
        default=None,
        help=(
            "Formatul RDF. Dacă lipsește, este ales "
            "după extensia fișierului."
        ),
    )

    args = parser.parse_args()

    try:
        if args.ontology.resolve() == args.output.resolve():
            raise ValueError(
                "Catalogul trebuie salvat într-un fișier "
                "diferit de ontologia sursă."
            )

        catalog = load_ontology(
            args.ontology,
            rdf_format=args.rdf_format,
        )

        destination = catalog.save_json(args.output)

    except (OSError, ValueError) as exc:
        print(f"Eroare: {exc}", file=sys.stderr)
        return 1

    print(f"\nOntologie: {catalog.source}")

    print("\nRaport:")
    print(
        json.dumps(
            catalog.summary(),
            ensure_ascii=False,
            indent=2,
        )
    )

    print("\nPrimele concepte:")

    for concept in catalog.concepts[:5]:
        kinds = ", ".join(
            kind.value for kind in concept.kinds
        )

        print(f"\n  {concept.preferred_label()}")
        print(f"    IRI: {concept.iri}")
        print(f"    Roluri: {kinds}")
        print(f"    Definiții: {len(concept.definitions)}")
        print(f"    Părinți: {len(concept.parents)}")

    print(f"\nCatalog salvat: {destination.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())