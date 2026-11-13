from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from urllib.parse import quote
from uuid import uuid4

from .config import OBSERVATION_BASE_IRI
from .jsonld_context import build_observation_context

NonEmptyText = Annotated[str, Field(min_length=1)]


class ObservationModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
    )


class EntityObservation(ObservationModel):
    """Un obiect sau element vizibil în imagine."""

    id: NonEmptyText
    name: NonEmptyText
    features: list[NonEmptyText]
    location: NonEmptyText
    visibility: Literal["clear", "partial", "unclear"]
    uncertain: bool | None = None


class RelationObservation(ObservationModel):
    """O relație vizuală între două entități observate."""

    subject_id: NonEmptyText
    predicate: NonEmptyText
    object_id: NonEmptyText
    uncertain: bool | None = None


class ActionObservation(ObservationModel):
    """O acțiune sau postură sugerată de cadrul static."""

    description: NonEmptyText
    entity_ids: list[NonEmptyText]
    uncertain: bool


class ImageObservation(ObservationModel):
    """Conținutul pe care îl solicităm modelului vizual."""

    description: NonEmptyText
    entities: list[EntityObservation]
    relations: list[RelationObservation]
    actions: list[ActionObservation]
    visible_text: list[NonEmptyText]
    uncertainties: list[NonEmptyText]

    @model_validator(mode="after")
    def validate_entity_references(self) -> Self:
        entity_ids = [entity.id for entity in self.entities]

        if len(entity_ids) != len(set(entity_ids)):
            raise ValueError(
                "Identificatorii entităților trebuie să fie unici."
            )

        known_ids = set(entity_ids)

        for relation in self.relations:
            references = {
                relation.subject_id,
                relation.object_id,
            }

            if not references.issubset(known_ids):
                raise ValueError(
                    "O relație face referire la o entitate inexistentă."
                )

        for action in self.actions:
            if not set(action.entity_ids).issubset(known_ids):
                raise ValueError(
                    "O acțiune face referire la o entitate inexistentă."
                )

        return self


class FrameObservation(ObservationModel):
    """
    Observația împreună cu proveniența ei.

    Identificatorii și metadatele sunt adăugate de aplicație,
    nu generate de model.
    """
    analysis_id: str = Field(
        default_factory=lambda: uuid4().hex,
        pattern=r"^[0-9a-f]{32}$",
    )
    schema_version: str
    frame_id: NonEmptyText
    scene_index: int | None
    image_sha256: str
    created_at: str
    prompt_version: str
    requested_model: str
    resolved_model: str
    provider: str | None
    api_request_id: str | None
    elapsed_seconds: float
    parameters: dict[str, Any]
    usage: dict[str, Any]
    observation: ImageObservation

    def to_jsonld(self) -> dict[str, Any]:
        """Construiește documentul JSON-LD fără să modifice observația."""
        base_iri = f"{OBSERVATION_BASE_IRI}{self.analysis_id}/"
        context = build_observation_context(base_iri=base_iri)

        # Lucrăm pe reprezentarea serializată, nu pe obiectul original.
        data = self.model_dump(mode="json")

        data["@context"] = context
        data["id"] = base_iri
        data["type"] = "FrameObservation"

        observation = data["observation"]
        observation["id"] = base_iri + "image"
        observation["type"] = "ImageObservation"

        # Asociem ID-urile locale cu identificatori absoluți.
        entity_iris = {
            entity["id"]: (
                base_iri
                + "entities/"
                + quote(entity["id"], safe="")
            )
            for entity in observation["entities"]
        }

        for entity in observation["entities"]:
            entity["id"] = entity_iris[entity["id"]]
            entity["type"] = "EntityObservation"

        for index, relation in enumerate(
            observation["relations"],
            start=1,
        ):
            relation["id"] = f"{base_iri}relations/{index}"
            relation["type"] = "RelationObservation"

            relation["subject_id"] = entity_iris[
                relation["subject_id"]
            ]
            relation["object_id"] = entity_iris[
                relation["object_id"]
            ]

        for index, action in enumerate(
            observation["actions"],
            start=1,
        ):
            action["id"] = f"{base_iri}actions/{index}"
            action["type"] = "ActionObservation"

            action["entity_ids"] = [
                entity_iris[entity_id]
                for entity_id in action["entity_ids"]
            ]

        return data


class BatchItem(BaseModel):
    """Observația generată pentru un cadru din grup."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    frame_id: str
    observation: ImageObservation


class BatchResponse(BaseModel):
    """Răspunsul complet generat pentru un grup de cadre."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    frames: list[BatchItem]

    @classmethod
    def vlm_json_schema(cls) -> dict[str, Any]:
        schema = cls.model_json_schema()
        for observation_type in (EntityObservation, RelationObservation):
            definition = schema["$defs"][observation_type.__name__]
            definition["properties"]["uncertain"] = {"type": "boolean"}
            definition["required"].append("uncertain")
        return schema

    @model_validator(mode="after")
    def validate_uncertainty_markers(self) -> Self:
        for frame in self.frames:
            observation = frame.observation
            if any(
                item.uncertain is None
                for item in (*observation.entities, *observation.relations)
            ):
                raise ValueError(
                    f"Cadrul {frame.frame_id!r} are obiecte sau relații fără "
                    "marcaj boolean de incertitudine."
                )
        return self