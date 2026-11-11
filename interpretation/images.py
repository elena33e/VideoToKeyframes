"""Citirea și validarea imaginilor acceptate pentru descriere."""

from io import BytesIO
from pathlib import Path

from PIL import Image


SUPPORTED_IMAGE_FORMATS = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}


def read_validated_image(path: Path) -> tuple[bytes, str]:
    """Returnează conținutul original și MIME-ul stabilit din imagine."""
    raw = path.read_bytes()

    if not raw:
        raise ValueError(f"Imaginea este goală: {path.name}")

    try:
        with Image.open(BytesIO(raw)) as image:
            mime_type = SUPPORTED_IMAGE_FORMATS.get(image.format)

            if mime_type is None:
                raise ValueError(
                    f"Format nesuportat pentru {path.name}. "
                    "Folosește JPEG, PNG sau WEBP."
                )

            image.verify()

        # verify() nu decodează complet pixelii în toate formatele.
        # Redeschidem imaginea pentru a verifica și decodarea.
        with Image.open(BytesIO(raw)) as image:
            image.load()

    except (OSError, SyntaxError) as exc:
        raise ValueError(
            f"Imagine invalidă sau deteriorată: {path.name}"
        ) from exc

    return raw, mime_type