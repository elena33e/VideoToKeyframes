from dataclasses import dataclass


# Identifică termenii utilizați pentru reprezentarea observațiilor.
OBSERVATION_NAMESPACE = "https://github.com/elena33e/VideoToKeyframes#"
# Baza identificatorilor pentru rezultatele analizelor.
OBSERVATION_BASE_IRI = (
    "https://github.com/elena33e/VideoToKeyframes/observations/"
)

# Baza identificatorilor pentru sesiunile complete.
SESSION_BASE_IRI = (
    "https://github.com/elena33e/VideoToKeyframes/sessions/"
)

# Configurația implicită pentru descrierea imaginilor.
DEFAULT_MODEL = "nvidia/nemotron-3.5-super-vl:free"
DEFAULT_LANGUAGE = "Romanian"

# Pentru descriere fără context de domeniu, folosește "".
DEFAULT_DOMAIN_CONTEXT = (
    "Traditional egg decorating (încondeierea ouălor)"
)

@dataclass(frozen=True)
class InterpretationConfig:
    """Setările sarcinii de interpretare, independente de API."""

    language: str = DEFAULT_LANGUAGE
    domain_context: str = DEFAULT_DOMAIN_CONTEXT

    max_output_tokens_per_image: int = 4096

    ontology_context: str = ""
    ontology_namespace: str = ""
    ontology_source_sha256: str = ""
    ontology_extraction_version: str = ""

    def __post_init__(self):
        if not self.language.strip():
            raise ValueError("Limba descrierilor lipsește.")

        if (
            type(self.max_output_tokens_per_image) is not int
            or self.max_output_tokens_per_image <= 0
        ):
            raise ValueError(
                "max_output_tokens_per_image trebuie să fie "
                "un întreg pozitiv."
            )