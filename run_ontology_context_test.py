"""Verifică și exportă separat contextul ontologic."""

import json
from pathlib import Path

from rdflib import Graph

from interpretation.ontology_context import build_ontology_context


SOURCE = Path(
    r"C:\Users\elena\OneDrive\Desktop"
    r"\Ontologie Incondeiere oua\Incondeiere_oua_ee.rdf"
)

NAMESPACE = (
    "http://www.semanticweb.org/creng/"
    "ontologies/2026/2/IncondeiereOua#"
)

OUTPUT_DIR = (
    Path(__file__).resolve().parent
    / "output"
    / "ontology_context_reference"
)


def main() -> None:
    first = build_ontology_context(SOURCE, NAMESPACE)
    second = build_ontology_context(SOURCE, NAMESPACE)

    # Două citiri independente trebuie să producă același context.
    if first.turtle != second.turtle:
        raise AssertionError(
            "Contextul diferă între două rulări."
        )

    if (
        first.report["context_sha256"]
        != second.report["context_sha256"]
    ):
        raise AssertionError(
            "Amprentele contextului diferă."
        )

    # Verificăm că exportul poate fi citit din nou ca Turtle.
    parsed = Graph().parse(
        data=first.turtle,
        format="turtle",
    )

    if len(parsed) != first.report["context_triples"]:
        raise AssertionError(
            "Numărul tripletelor exportate nu corespunde raportului."
        )

    if first.report["anchor_count"] == 0:
        raise AssertionError("Nu au fost identificate ancore.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    turtle_path = OUTPUT_DIR / "context.ttl"
    report_path = OUTPUT_DIR / "report.json"

    turtle_path.write_text(
        first.turtle,
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            first.report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    for key in (
        "source_triples",
        "context_triples",
        "omitted_triples",
        "anchor_count",
        "utf8_bytes",
        "swrl_rules_excluded",
    ):
        print(f"{key}: {first.report[key]}")

    for warning in first.report["warnings"]:
        print(f"Observație: {warning}")

    print("\nVerificări trecute: stabilitate și parsare Turtle.")
    print(f"Context: {turtle_path}")
    print(f"Raport:  {report_path}")


if __name__ == "__main__":
    main()