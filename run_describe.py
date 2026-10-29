import argparse
import os
import sys
from pathlib import Path
from uuid import uuid4
from dotenv import load_dotenv

from interpretation.describe import (
    DescriptionConfig,
    DescriptionError,
    OpenRouterImageDescriber,
)

def main() -> int:
    load_dotenv(
        dotenv_path=Path(__file__).resolve().parent / ".env",
        override=False,
    )

    # Restul funcției rămâne la fel.

    parser = argparse.ArgumentParser(
        description="Descrie un keyframe folosind un model vizual."
    )

    parser.add_argument(
        "image",
        type=Path,
        help="Calea imaginii JPEG, PNG sau WEBP.",
    )
    parser.add_argument(
        "--frame-id",
        default="frame_0001",
        help="Identificatorul cadrului.",
    )
    parser.add_argument(
        "--scene-index",
        type=int,
        default=None,
        help="Indicele scenei, dacă este cunoscut.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Fișierul JSON de ieșire; trebuie să fie nou.",
    )

    args = parser.parse_args()

    try:
        config = DescriptionConfig(
            api_key=os.environ.get("OPENROUTER_API_KEY", ""),
            model=os.environ.get(
                "OPENROUTER_MODEL",
                "qwen/qwen3.8-27b",
            ),
        )

        destination = args.output or (
            Path("output")
            / "interpretation"
            / f"observation_{uuid4().hex}.json"
        )

        if destination.resolve() == args.image.resolve():
            raise ValueError(
                "Rezultatul nu poate înlocui imaginea sursă."
            )

        if destination.exists():
            raise ValueError(
                f"Fișierul de ieșire există deja: {destination}"
            )

        describer = OpenRouterImageDescriber(config)

        result = describer.describe(
            args.image,
            frame_id=args.frame_id,
            scene_index=args.scene_index,
        )

        destination.parent.mkdir(parents=True, exist_ok=True)

        with destination.open("x", encoding="utf-8") as output:
            output.write(result.model_dump_json(indent=2))
            output.write("\n")

    except (OSError, ValueError, DescriptionError) as exc:
        print(f"Eroare: {exc}", file=sys.stderr)
        return 1

    print("\nDescriere:")
    print(result.observation.description)

    print(f"\nEntități: {len(result.observation.entities)}")
    print(f"Relații: {len(result.observation.relations)}")
    print(f"Incertitudini: {len(result.observation.uncertainties)}")
    print(f"Durata apelului: {result.elapsed_seconds:.2f} secunde")
    print(f"Rezultat: {destination.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())