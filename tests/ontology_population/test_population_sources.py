"""Referințele originale ajung în aceeași cerere de populare.

Clientul este simulat; testele verifică traseul datelor și contractul,
nu calitatea semantică a selecției făcute de un model real.
"""

import json
import unittest
from copy import deepcopy
from dataclasses import replace
from unittest.mock import Mock

from interpretation.observations import FrameObservation
from ontology_population.strategies.base import GenerationResponse
from ontology_population.service import (
    PopulationError,
    populate_batch,
)
from ontology_population.session import _population_observation
from session_context.graph import build_session_context


ONTOLOGY = """
@prefix ex: <https://example.test/population#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .

ex:Item a owl:Class .
"""


def make_saved(frame_id, color="albastru", legacy=False):
    entity = {
        "id": "e1",
        "name": "element",
        "characteristics": [
            {
                "name": "culoare",
                "value": color,
                "uncertain": False,
            },
            {
                "name": "formă",
                "value": "ovală",
                "uncertain": False,
            },
        ],
        "location": "centru",
        "visibility": "partial",
        "uncertain": False,
    }

    if legacy:
        entity.pop("characteristics")
        entity["features"] = ["descriere vizuală veche"]

    return FrameObservation.model_validate({
        "schema_version": "1.0" if legacy else "1.2",
        "frame_id": frame_id,
        "scene_index": None,
        "image_sha256": "0" * 64,
        "created_at": "2026-01-01T00:00:00+00:00",
        "prompt_version": "test",
        "requested_model": "test",
        "resolved_model": "test",
        "provider": "test",
        "api_request_id": None,
        "elapsed_seconds": 0.0,
        "parameters": {},
        "usage": {},
        "observation": {
            "description": "Cadru sintetic.",
            "entities": [entity],
            "relations": [],
            "actions": [],
            "visible_text": [],
            "uncertainties": [],
        },
    }).to_jsonld()


class PopulationSourcesTest(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.generate.side_effect = self.respond
        self.requests = []
        self.saved = {}

    def observation(self, frame_id, **options):
        """Păstrează raportul original separat de intrarea normalizată."""
        saved = make_saved(frame_id, **options)
        self.saved[saved["analysis_id"]] = saved
        return _population_observation(saved)

    def session_document(self):
        return {
            "session_id": "population-sources-test",
            "imported_frames": [],
            "frames": [
                {
                    "frame_id": saved["frame_id"],
                    "selected": True,
                    "description_status": "completed",
                    "observation": saved,
                }
                for saved in self.saved.values()
            ],
        }

    def respond(self, **request):
        """Produce un răspuns simulat conform contractului nou."""
        payload = json.loads(request["user_prompt"])
        self.requests.append(payload)

        appearances = []

        for entry in payload["observations"]:
            for entity in entry["observation"]["entities"]:
                reference = entry[
                    "source_references_by_source_id"
                ][entity["id"]]

                characteristics = [
                    {
                        "source_characteristic_iri": iri,
                        "meaning": characteristic["name"],
                        "normalized_value": characteristic["value"],
                        "target_kind": "entity",
                        "part_name": None,
                        "use": "comparison_and_state",
                        "reason": "Interpretare simulată pentru test.",
                        "uncertain": characteristic["uncertain"],
                        "property_iri": None,
                        "ontology_reference_iris": [],
                    }
                    for characteristic, iri in zip(
                        entity["characteristics"],
                        reference["characteristic_iris"],
                        strict=True,
                    )
                ]

                appearances.append({
                    "occurrence_iri": reference["occurrence_iri"],
                    "characteristics": characteristics,
                })

        document = {
            "graphs": {
                "@graph": [
                    {
                        "@id": entry["graph_iri"],
                        "@graph": [],
                    }
                    for entry in payload["observations"]
                ],
            },
            "characteristic_selection": {
                "status": "proposal",
                "appearances": appearances,
            },
        }

        return GenerationResponse(
            text=json.dumps(document, ensure_ascii=False),
            message_id="test-request",
            model="test-model",
            usage={"total_tokens": 10},
        )

    def populate(self, observations):
        context = build_session_context(
            self.session_document()
        )

        return populate_batch(
            observations,
            ontology_turtle=ONTOLOGY,
            context=context,
            client=self.client,
        )

    def test_conversion_preserves_references_without_mutating_report(self):
        saved = make_saved("frame-1")
        before = deepcopy(saved)

        observation = _population_observation(saved)
        entity = saved["observation"]["entities"][0]

        self.assertEqual(
            {"e1": entity["id"]},
            observation.occurrence_iris_by_source_id,
        )
        self.assertEqual(
            {
                "e1": tuple(
                    characteristic["id"]
                    for characteristic in entity["characteristics"]
                ),
            },
            observation.characteristic_iris_by_source_id,
        )
        self.assertEqual(before, saved)

    def test_same_local_ids_keep_distinct_sources_in_one_request(self):
        first = self.observation("frame-1")
        second = self.observation(
            "frame-2",
            color="roșu",
        )

        result = self.populate([first, second])

        self.assertEqual(1, self.client.generate.call_count)
        self.assertEqual(2, len(result.graphs))

        entries = self.requests[0]["observations"]
        first_refs = entries[0][
            "source_references_by_source_id"
        ]["e1"]
        second_refs = entries[1][
            "source_references_by_source_id"
        ]["e1"]

        self.assertNotEqual(
            first_refs["occurrence_iri"],
            second_refs["occurrence_iri"],
        )
        self.assertEqual(
            list(first.characteristic_iris_by_source_id["e1"]),
            first_refs["characteristic_iris"],
        )
        self.assertEqual(
            list(second.characteristic_iris_by_source_id["e1"]),
            second_refs["characteristic_iris"],
        )
        self.assertNotEqual(
            first_refs["occurrence_iri"],
            entries[0]["entity_iris_by_source_id"]["e1"],
        )

    def test_invalid_references_are_rejected_before_generation(self):
        observation = self.observation("frame-1")
        iris = observation.characteristic_iris_by_source_id["e1"]

        invalid = (
            replace(
                observation,
                occurrence_iris_by_source_id={},
            ),
            replace(
                observation,
                characteristic_iris_by_source_id={"e1": ()},
            ),
            replace(
                observation,
                characteristic_iris_by_source_id={
                    "e1": ("relative-name", iris[1]),
                },
            ),
        )

        for item in invalid:
            with self.subTest(item=item):
                with self.assertRaises(PopulationError):
                    self.populate([item])

                self.client.generate.assert_not_called()

    def test_duplicate_occurrence_reference_is_rejected(self):
        first = self.observation("frame-1")
        second = self.observation("frame-2")

        invalid_second = replace(
            second,
            occurrence_iris_by_source_id=(
                first.occurrence_iris_by_source_id
            ),
        )

        with self.assertRaises(PopulationError):
            self.populate([first, invalid_second])

        self.client.generate.assert_not_called()

    def test_duplicate_characteristic_reference_is_rejected(self):
        observation = self.observation("frame-1")
        iri = observation.characteristic_iris_by_source_id["e1"][0]

        invalid = replace(
            observation,
            characteristic_iris_by_source_id={
                "e1": (iri, iri),
            },
        )

        with self.assertRaises(PopulationError):
            self.populate([invalid])

        self.client.generate.assert_not_called()

    def test_legacy_features_do_not_gain_characteristic_references(self):
        observation = self.observation(
            "legacy-frame",
            legacy=True,
        )

        self.populate([observation])
        entry = self.requests[0]["observations"][0]

        self.assertEqual(
            [],
            entry["source_references_by_source_id"]["e1"][
                "characteristic_iris"
            ],
        )
        self.assertEqual(
            ["descriere vizuală veche"],
            entry["observation"]["entities"][0]["features"],
        )
        self.assertEqual(
            [],
            entry["observation"]["entities"][0]["characteristics"],
        )


if __name__ == "__main__":
    unittest.main()