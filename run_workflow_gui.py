"""Punct de pornire pentru interfața unificată."""

import os
from pathlib import Path

from dotenv import load_dotenv

from interpretation.config import DEFAULT_MODEL
from gui.workflow_app_backup import launch_workflow_gui

def main():
    project_root = Path(__file__).resolve().parent

    load_dotenv(project_root / ".env", override=False)

    #Setup pt Openrouter API
    """launch_workflow_gui(
        api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        model=os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL),
        output_dir=project_root / "output",
    )"""

    # Setup pt Gemini API
    launch_workflow_gui(
        api_key=os.environ.get("GEMINI_API_KEY", ""),
        model=os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
        output_dir=project_root / "output",
    )


if __name__ == "__main__":
    main()
