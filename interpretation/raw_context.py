import hashlib
from dataclasses import dataclass
from pathlib import Path


RAW_CONTEXT_VERSION = "ontology-raw-file-v1"
DEFAULT_MAX_CHARACTERS = 300_000


@dataclass(frozen=True)
class RawOntologyContext:
    text: str
    source: str
    source_sha256: str
    byte_count: int
    encoding: str

    def to_metadata(self) -> dict:
        return {
            "version": RAW_CONTEXT_VERSION,
            "representation": "original_file_text",
            "source": self.source,
            "source_sha256": self.source_sha256,
            "context_sha256": hashlib.sha256(
                self.text.encode("utf-8")
            ).hexdigest(),
            "scope": "entire_selected_file",
            "encoding": self.encoding,
            "byte_count": self.byte_count,
            "character_count": len(self.text),
            "external_imports_loaded": False,
            "text": self.text,
        }


def load_raw_ontology_context(
    path: str | Path,
    *,
    encoding: str = "utf-8-sig",
    max_characters: int = DEFAULT_MAX_CHARACTERS,
) -> RawOntologyContext:
    """
    Citește ontologia ca text, fără parsare RDF sau extracție.

    Nu descarcă fișierele referite prin owl:imports.
    Limita este în caractere, nu în tokeni.
    """
    if type(max_characters) is not int or max_characters <= 0:
        raise ValueError(
            "max_characters trebuie să fie un întreg pozitiv."
        )

    source = Path(path).expanduser().resolve(strict=True)

    if not source.is_file():
        raise ValueError(
            f"Calea nu este un fișier: {source}"
        )

    raw = source.read_bytes()

    if not raw:
        raise ValueError("Fișierul ontologiei este gol.")

    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"Fișierul nu poate fi citit folosind {encoding}. "
            "Specifică explicit codificarea corectă."
        ) from exc

    if not text.strip():
        raise ValueError(
            "Fișierul ontologiei nu conține text."
        )

    if len(text) > max_characters:
        raise ValueError(
            f"Ontologia are {len(text):,} de caractere. "
            f"Limita locală este {max_characters:,}. "
            "Nu a fost trimis niciun apel API."
        )

    return RawOntologyContext(
        text=text,
        source=str(source),
        source_sha256=hashlib.sha256(raw).hexdigest(),
        byte_count=len(raw),
        encoding=encoding,
    )