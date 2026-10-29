from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class RelationObservation(ObservationModel):
    """O relație vizuală între două entități observate."""

    subject_id: NonEmptyText
    predicate: NonEmptyText
    object_id: NonEmptyText


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