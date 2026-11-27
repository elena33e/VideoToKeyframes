"""Criterii explicite pentru evaluarea caracteristicilor de identitate."""

from dataclasses import dataclass
from typing import (
    Annotated,
    Literal,
    Self,
)
from unicodedata import normalize

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
    field_validator,
    model_validator,
)

from ..characteristics.comparison import OccurrenceComparison
from .models import AbsoluteIRI

CRITERIA_EVALUATOR_VERSION = "characteristic-criteria-v1"

Text = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
    ),
]

AssessmentStatus = Literal[
    "consistent",
    "difference_detected",
    "insufficient_evidence",
]


def _name(value: str) -> str:
    return " ".join(normalize("NFC", value).split()).casefold()

SHA256 = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^[0-9a-f]{64}$",
    ),
]


class IdentityRequirements(BaseModel):
    """Domeniul de aplicare al criteriilor de identitate.

    Clasele sunt declarate explicit.
    Etichetele și ierarhia nu stabilesc automat aplicabilitatea.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    identity_scope_iri: AbsoluteIRI
    applicable_class_iris: tuple[AbsoluteIRI, ...]
    justification: Text

    @field_validator("applicable_class_iris")
    @classmethod
    def validate_class_iris(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not value:
            raise ValueError(
                "Specifică cel puțin o clasă."
            )

        if len(value) != len(set(value)):
            raise ValueError(
                "Lista conține clase duplicate."
            )

        return value

class IdentityCriteria(BaseModel):
    """Criterii configurate explicit pentru entitățile urmărite.

    scope_description documentează domeniul de aplicare.
    Alegerea criteriilor potrivite unei apariții se face separat.

    required_characteristics trebuie să fie toate concordante.
    O diferență în oricare dintre characteristics trebuie examinată.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    criteria_id: Text
    version: Text
    scope_description: Text
    justification: Text
    validated_by: Text

    characteristics: tuple[Text, ...]
    required_characteristics: tuple[Text, ...]
    identity_requirements: IdentityRequirements | None = None

    @field_validator(
        "characteristics",
        "required_characteristics",
    )
    @classmethod
    def normalize_names(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not value:
            raise ValueError(
                "Lista de caracteristici nu poate fi goală."
            )

        names = tuple(_name(name) for name in value)

        if len(names) != len(set(names)):
            raise ValueError(
                "Lista conține caracteristici duplicate "
                "după normalizarea numelor."
            )

        return names

    @model_validator(mode="after")
    def validate_required_characteristics(self) -> Self:
        unknown = (
            set(self.required_characteristics)
            - set(self.characteristics)
        )

        if unknown:
            raise ValueError(
                "Caracteristicile obligatorii trebuie să aparțină "
                "listei urmărite de criterii."
            )

        return self


@dataclass(frozen=True)
class CharacteristicAssessment:
    criteria: IdentityCriteria
    comparison: OccurrenceComparison
    status: AssessmentStatus
    different_characteristics: tuple[str, ...]
    unknown_required_characteristics: tuple[str, ...]
    evaluator_version: str = CRITERIA_EVALUATOR_VERSION


def assess_identity_characteristics(
    comparison: OccurrenceComparison,
    *,
    criteria: IdentityCriteria,
) -> CharacteristicAssessment:
    """Evaluează comparația fără să stabilească identitatea.

    Comparația trebuie produsă pentru exact caracteristicile
    specificate în criterii.

    Diferențele sunt diferențe între descrieri, nu schimbări fizice
    demonstrate. Dovezile originale rămân accesibile în comparison.
    """
    rows = {}

    for item in comparison.characteristics:
        name = _name(item.name)

        if name in rows:
            raise ValueError(
                "Comparația conține caracteristici duplicate."
            )

        if item.status not in {
            "unchanged",
            "different",
            "unknown",
        }:
            raise ValueError(
                "Comparația conține un statut necunoscut."
            )

        rows[name] = item

    if set(rows) != set(criteria.characteristics):
        raise ValueError(
            "Comparația trebuie să acopere exact "
            "caracteristicile specificate în criterii."
        )

    different = tuple(
        name
        for name in criteria.characteristics
        if rows[name].status == "different"
    )

    unknown_required = tuple(
        name
        for name in criteria.required_characteristics
        if rows[name].status == "unknown"
    )

    status: AssessmentStatus

    if different:
        status = "difference_detected"
    elif unknown_required:
        status = "insufficient_evidence"
    else:
        status = "consistent"

    return CharacteristicAssessment(
        criteria=criteria,
        comparison=comparison,
        status=status,
        different_characteristics=different,
        unknown_required_characteristics=unknown_required,
    )