"""Tipuri și utilitare interne comune evaluării candidaților."""

from typing import Literal as StatusLiteral
from unicodedata import normalize

from rdflib import Namespace, URIRef

from interpretation.config import OBSERVATION_NAMESPACE
from session_context.models import SessionContext

CTX = Namespace(OBSERVATION_NAMESPACE)
AssociationAction = StatusLiteral[
    "automatic", "confirmation", "unresolved", "already_associated"
]


def _key(value: str) -> str:
    return " ".join(normalize("NFC", value).split()).casefold()


def _members(
    context: SessionContext, occurrence: URIRef, object_iri: URIRef | None
) -> set[URIRef]:
    if object_iri is None:
        return {occurrence}
    return set(context.identities.subjects(CTX.associatedObject, object_iri))
