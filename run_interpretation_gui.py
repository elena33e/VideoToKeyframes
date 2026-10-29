"""Punct de pornire pentru interfața de test a interpretării."""

import os
from pathlib import Path

from dotenv import load_dotenv

from gui.interpretation_app import DEFAULT_FREE_MODEL, launch_interpretation_gui


def main():
    project_root = Path(__file__).resolve().parent
    load_dotenv(project_root / ".env", override=False)
    launch_interpretation_gui(
        api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        model=os.environ.get("OPENROUTER_MODEL", DEFAULT_FREE_MODEL),
        output_dir=project_root / "output" / "interpretation",
    )


if __name__ == "__main__":
    main()
