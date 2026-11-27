"""Proveniența propunerilor rezultate din popularea ontologiei."""

from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictStr,
    StringConstraints,
)

from .identity.models import AbsoluteIRI


Text = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
    ),
]

Sha256 = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^[0-9a-f]{64}$",
    ),
]


class PopulationProvenance(BaseModel):
    """Sursele unui rezultat al populării."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: Text
    observations_sha256: Sha256
    observations_turtle_sha256: Sha256
    identities_turtle_sha256: Sha256

    frame_id: Text
    analysis_id: Text
    population_graph_iri: AbsoluteIRI

    provider: Text
    model: Text
    prompt_version: Text
    message_id: StrictStr
    ontology_turtle_sha256: Sha256