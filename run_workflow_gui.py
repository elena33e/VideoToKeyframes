"""Punct de pornire pentru interfața unificată."""

import os
from pathlib import Path

from dotenv import load_dotenv

from gui.workflow_app import launch_workflow_gui


def main():
    project_root = Path(__file__).resolve().parent

    load_dotenv(
        project_root / ".env",
        override=False,
    )

    api_keys = {
        "gemini": os.environ.get("GEMINI_API_KEY", ""),
        "openrouter": os.environ.get("OPENROUTER_API_KEY", ""),
        "openai": os.environ.get("OPENAI_API_KEY", ""),
    }

    model_defaults = {
        "gemini": os.environ.get(
            "GEMINI_MODEL",
            "gemini-3.6-flash",
        ),
        "openrouter": os.environ.get(
            "OPENROUTER_MODEL",
            "nvidia/nemotron-3.5-super-vl:free",
        ),
        "openai": os.environ.get(
            "OPENAI_MODEL",
            "gpt-6.1-sol",
        ),
    }

    initial_provider = os.environ.get(
        "VLM_PROVIDER",
        "openrouter",
    ).strip().lower()

    if initial_provider not in api_keys:
        raise ValueError(
            "VLM_PROVIDER trebuie să fie "
            "'gemini', 'openrouter' sau 'openai'."
        )

    launch_workflow_gui(
        api_keys=api_keys,
        model_defaults=model_defaults,
        initial_provider=initial_provider,
        output_dir=project_root / "output",
    )


if __name__ == "__main__":
    main()