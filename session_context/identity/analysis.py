"""Propuneri privind individuarea și păstrarea identității."""

from collections.abc import Collection
from typing import Annotated, Literal as LiteralType, Self
from unicodedata import normalize

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictBool,
    StringConstraints,
    model_validator,
)
from rdflib import (
    Graph,
    Literal,
    Namespace,
    RDF,
    URIRef,
    XSD,
)

from interpretation.config import OBSERVATION_NAMESPACE

from .models import AbsoluteIRI
from ..graph import entities_for_frame
from ..models import SessionContext


CTX = Namespace(OBSERVATION_NAMESPACE)

Text = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
    ),
]


class OntologyTextEvidence(BaseModel):
    """Fragment citat dintr-o valoare textuală a ontologiei."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    subject_iri: AbsoluteIRI
    predicate_iri: AbsoluteIRI
    quotation: Text
    language: Text | None


class IdentityConditionProposal(BaseModel):
    """Condiție candidată, fără confirmarea aplicabilității ei."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    description: Text
    scope_description: Text
    origin: LiteralType["ontology_text", "model_hypothesis"]
    justification: Text

    ontology_evidence: tuple[OntologyTextEvidence, ...]
    relevant_observation_iris: tuple[AbsoluteIRI, ...]
    required_evidence: tuple[Text, ...]
    uncertain: StrictBool

    @model_validator(mode="after")
    def validate_condition(self) -> Self:
        if not self.required_evidence:
            raise ValueError(
                "Precizează dovezile necesare examinării condiției."
            )

        if (
            self.origin == "ontology_text"
            and not self.ontology_evidence
        ):
            raise ValueError(
                "O condiție atribuită textului ontologiei "
                "necesită cel puțin un citat."
            )

        if (
            self.origin == "model_hypothesis"
            and not self.uncertain
        ):
            raise ValueError(
                "O ipoteză a modelului trebuie marcată ca incertă."
            )

        if len(self.relevant_observation_iris) != len(
            set(self.relevant_observation_iris)
        ):
            raise ValueError(
                "Referințele observaționale conțin duplicate."
            )

        return self


class AppearanceIdentityAnalysis(BaseModel):
    """Analiza propusă pentru o apariție.

    uncertain privește interpretarea entității și a unității urmărite.
    Fiecare condiție își păstrează separat incertitudinea.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    occurrence_iri: AbsoluteIRI

    entity_kind: Text | None
    entity_kind_reason: Text
    tracking_unit: Text
    granularity: Text
    ontology_reference_iris: tuple[AbsoluteIRI, ...]

    identity_conditions: tuple[IdentityConditionProposal, ...]
    compatible_changes: tuple[IdentityConditionProposal, ...]
    identity_boundaries: tuple[IdentityConditionProposal, ...]

    unresolved_questions: tuple[Text, ...]
    uncertain: StrictBool

    @model_validator(mode="after")
    def validate_analysis(self) -> Self:
        if self.entity_kind is None:
            if not self.uncertain:
                raise ValueError(
                    "Natura neclarificată a entității "
                    "trebuie marcată ca incertă."
                )
            if not self.unresolved_questions:
                raise ValueError(
                    "Precizează ce rămâne neclar despre entitate."
                )

        if (
            not self.identity_conditions
            and not self.unresolved_questions
        ):
            raise ValueError(
                "Lipsa condițiilor de identitate necesită "
                "explicarea întrebărilor rămase deschise."
            )

        if len(self.ontology_reference_iris) != len(
            set(self.ontology_reference_iris)
        ):
            raise ValueError(
                "Referințele ontologice conțin duplicate."
            )

        return self


class IdentityAnalysisProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: LiteralType["proposal"] = "proposal"
    appearances: tuple[AppearanceIdentityAnalysis, ...]


def _text(value: str) -> str:
    return " ".join(normalize("NFC", value).split())


def _observation_is_uncertain(
    context: SessionContext,
    node: URIRef,
) -> bool:
    """Citește incertitudinea conținutului observațional.

    Nodurile de proveniență, precum cadrul, nu au acest marcaj.
    Existența lor nu constituie o dovadă de continuitate.
    """
    graph = context.observations
    kinds = (
        CTX.EntityObservation,
        CTX.CharacteristicObservation,
        CTX.RelationObservation,
        CTX.ActionObservation,
    )
    if not any((node, RDF.type, kind) in graph for kind in kinds):
        return False

    markers = set(graph.objects(node, CTX.uncertain))
    if not markers:
        return True

    if len(markers) != 1:
        raise ValueError("Marcaje de incertitudine repetate.")

    marker = next(iter(markers))
    if (
        not isinstance(marker, Literal)
        or marker.datatype != XSD.boolean
        or type(marker.toPython()) is not bool
    ):
        raise ValueError("Marcaj de incertitudine invalid.")

    return marker.toPython()


def _check_ontology_text(
    evidence: OntologyTextEvidence,
    ontology: Graph,
) -> None:
    quotation = _text(evidence.quotation)
    expected_language = (
        evidence.language.lower()
        if evidence.language is not None
        else None
    )

    for value in ontology.objects(
        URIRef(evidence.subject_iri),
        URIRef(evidence.predicate_iri),
    ):
        if (
            not isinstance(value, Literal)
            or not isinstance(value.toPython(), str)
        ):
            continue

        language = (
            value.language.lower()
            if value.language is not None
            else None
        )
        if (
            language == expected_language
            and quotation in _text(str(value))
        ):
            return

    raise ValueError(
        "Citatul nu există în ontologie pentru "
        "subiectul, proprietatea și limba indicate."
    )


def check_identity_analysis_proposal(
    proposal: IdentityAnalysisProposal,
    *,
    context: SessionContext,
    expected_occurrences: Collection[str | URIRef],
    ontology: Graph,
) -> IdentityAnalysisProposal:
    """Verifică structura, acoperirea și existența surselor.

    Nu certifică relevanța citatelor, natura entității,
    condițiile de identitate sau satisfacerea lor în sesiune.
    """
    proposal = IdentityAnalysisProposal.model_validate(
        proposal.model_dump(mode="json")
    )

    if isinstance(expected_occurrences, (str, bytes)):
        raise ValueError(
            "Aparițiile așteptate trebuie transmise ca o colecție."
        )

    expected = tuple(
        URIRef(item) for item in expected_occurrences
    )
    if len(expected) != len(set(expected)):
        raise ValueError("Lista aparițiilor conține duplicate.")

    known_occurrences = {
        occurrence
        for frame_id in context.frame_iris
        for occurrence in entities_for_frame(context, frame_id)
    }
    if not set(expected).issubset(known_occurrences):
        raise ValueError(
            "Unele apariții nu există în contextul sesiunii."
        )

    actual = tuple(
        URIRef(item.occurrence_iri)
        for item in proposal.appearances
    )
    if (
        len(actual) != len(set(actual))
        or set(actual) != set(expected)
    ):
        raise ValueError(
            "Analiza trebuie să acopere exact aparițiile cerute, "
            "fără duplicate."
        )

    ontology_iris = {
        term
        for triple in ontology
        for term in triple
        if isinstance(term, URIRef)
    }
    observation_iris = {
        subject
        for subject in context.observations.subjects()
        if isinstance(subject, URIRef)
    }

    for appearance in proposal.appearances:
        occurrence = URIRef(appearance.occurrence_iri)
        if (
            occurrence,
            RDF.type,
            CTX.EntityObservation,
        ) not in context.observations:
            raise ValueError("Apariție observațională invalidă.")

        if (
            _observation_is_uncertain(context, occurrence)
            and not appearance.uncertain
        ):
            raise ValueError(
                "Incertitudinea entității observate "
                "nu poate fi eliminată prin analiză."
            )

        references = {
            URIRef(iri)
            for iri in appearance.ontology_reference_iris
        }
        if not references.issubset(ontology_iris):
            raise ValueError(
                "Analiza citează referințe absente din ontologie."
            )

        conditions = (
            appearance.identity_conditions
            + appearance.compatible_changes
            + appearance.identity_boundaries
        )
        for condition in conditions:
            for evidence in condition.ontology_evidence:
                _check_ontology_text(evidence, ontology)

            sources = {
                URIRef(iri)
                for iri in condition.relevant_observation_iris
            }
            if not sources.issubset(observation_iris):
                raise ValueError(
                    "Condiția citează surse absente "
                    "din observațiile originale."
                )

            if (
                not condition.uncertain
                and any(
                    _observation_is_uncertain(context, source)
                    for source in sources
                )
            ):
                raise ValueError(
                    "Incertitudinea sursei observaționale "
                    "nu poate fi eliminată din condiția propusă."
                )

    return proposal