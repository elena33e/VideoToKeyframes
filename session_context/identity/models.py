"""Modele pentru identitatea aparițiilor dintr-o sesiune."""

from datetime import (
    datetime,
    timezone,
)
from typing import (
    Annotated,
    Literal,
    Self,
)
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


NonEmptyText = Annotated[str, Field(min_length=1)]

LocalID = Annotated[
    str,
    Field(pattern=r"^[0-9a-f]{32}$"),
]

AbsoluteIRI = Annotated[
    str,
    StringConstraints(
        strip_whitespace=False,
        pattern=r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$",
    ),
]

IdentityOutcome = Literal[
    "same_object",
    "different_objects",
    "unresolved",
]


class IdentityRecord(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    session_id: NonEmptyText
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "Momentul înregistrării trebuie să includă fusul orar."
            )

        return value.astimezone(timezone.utc)


class TrackedObject(IdentityRecord):
    object_id: LocalID = Field(
        default_factory=lambda: uuid4().hex
    )


class IdentityDecision(IdentityRecord):
    decision_id: LocalID = Field(
        default_factory=lambda: uuid4().hex
    )

    left_occurrence_iri: AbsoluteIRI
    right_occurrence_iri: AbsoluteIRI
    outcome: IdentityOutcome

    object_id: LocalID | None = None
    decided_by: NonEmptyText
    justification: NonEmptyText

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        if self.left_occurrence_iri == self.right_occurrence_iri:
            raise ValueError(
                "Decizia trebuie să privească două apariții distincte."
            )

        if self.outcome == "same_object" and self.object_id is None:
            raise ValueError(
                "Confirmarea identității necesită object_id."
            )

        if self.outcome != "same_object" and self.object_id is not None:
            raise ValueError(
                "object_id este permis numai pentru "
                "outcome='same_object'."
            )

        return self