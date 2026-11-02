"""Punct de pornire pentru interfața unificată."""

import os
from pathlib import Path

from dotenv import load_dotenv

from gui.workflow_app import DEFAULT_MODEL, launch_workflow_gui


def main():
    project_root = Path(__file__).resolve().parent

    load_dotenv(project_root / ".env", override=False)

    launch_workflow_gui(
        api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        model=os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL),
        output_dir=project_root / "output",
    )


if __name__ == "__main__":
    main()