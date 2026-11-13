"""Rulează un singur batch de populare pornind dintr-un export de sesiune."""

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv
from rdflib.util import guess_format

from ontology.reader import read_ontology_source
from ontology_population.claude import ClaudeClient
from ontology_population.config import (
    DEFAULT_CLAUDE_MODEL,
    DEFAULT_OPENAI_MODEL,
    MAX_BATCH_SIZE,
)
from ontology_population.generation import GenerationError
from ontology_population.openai import OpenAIClient
from ontology_population.session import iter_population_reports



def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, type=Path)
    parser.add_argument("--ontology", required=True, type=Path)
    parser.add_argument("--ontology-format")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument(
        "--batch-size",
        type=int,
        choices=range(1, MAX_BATCH_SIZE + 1),
        default=MAX_BATCH_SIZE,
    )
    parser.add_argument("--provider", choices=("openai", "claude"), default="openai")
    parser.add_argument("--model")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.offset < 0:
        parser.error("--offset trebuie să fie nenegativ.")
    if args.output is not None and args.output.exists():
        parser.error(f"Fișierul de ieșire există deja: {args.output}")

    rdf_format = args.ontology_format or guess_format(args.ontology.name)
    if rdf_format is None:
        parser.error("Specifică formatul sursei cu --ontology-format.")

    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
    if args.provider == "openai":
        client_type = OpenAIClient
        api_key = os.getenv("OPENAI_API_KEY", "")
        default_model = os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL
    else:
        client_type = ClaudeClient
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        default_model = os.getenv("ANTHROPIC_MODEL") or DEFAULT_CLAUDE_MODEL

    model = args.model or default_model

    try:
        client = client_type(api_key=api_key, model=model)

        session = json.loads(args.session.read_text(encoding="utf-8-sig"))

        ontology_source = read_ontology_source(args.ontology, rdf_format=rdf_format)

        report = next(iter_population_reports(
            session,
            ontology_source=ontology_source,
            client=client,
            provider=args.provider,
            requested_model=model,
            batch_size=args.batch_size,
            offset=args.offset,
        ))

        if args.output is None:
            print(json.dumps(report, indent=2))
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as handle:
                json.dump(report, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            print(f"{len(report['graphs'])} grafuri candidate salvate în {args.output}")
    except (OSError, ValueError, KeyError, GenerationError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()