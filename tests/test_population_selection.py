"""Selecția este produsă și verificată în același apel cu mini-grafurile."""

import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path

import test_population_sources as fixtures
from ontology_population.review import build_review_frames
from ontology_population.revision import GraphRevision
from ontology_population.service import PopulationError
from ontology_population.session import _population_observation
from ontology_population.storage import save_review_report


class PopulationSelectionTest(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.PopulationSourcesTest()
        self.base.setUp()

    def alter_response(self, change):
        def respond(**request):
            response = self.base.respond(**request)
            document = json.loads(response.text)
            change(document)
            return replace(
                response,
                text=json.dumps(document),
            )

        self.base.client.generate.side_effect = respond

    def test_selection_and_context_are_used_in_one_request(self):
        observation = self.base.observation("frame-1")

        result = self.base.populate([observation])

        self.assertEqual(
            1,
            self.base.client.generate.call_count,
        )
        self.assertIn(
            "session_context",
            self.base.requests[0],
        )

        selection = result.graphs[
            observation.analysis_id
        ].characteristic_selection

        self.assertEqual("proposal", selection["status"])
        self.assertEqual(
            2,
            len(selection["appearances"][0]["characteristics"]),
        )
        self.assertEqual(
            "population-sources-test",
            result.context_provenance["session_id"],
        )

    def test_omitted_characteristic_or_accepted_status_is_rejected(self):
        observation = self.base.observation("frame-1")

        def omit(document):
            document["characteristic_selection"][
                "appearances"
            ][0]["characteristics"].pop()

        def accept(document):
            document["characteristic_selection"]["status"] = "accepted"

        for change in (omit, accept):
            with self.subTest(change=change.__name__):
                self.base.client.generate.reset_mock()
                self.alter_response(change)

                with self.assertRaises(PopulationError):
                    self.base.populate([observation])

                self.assertEqual(
                    1,
                    self.base.client.generate.call_count,
                )

    def test_foreign_characteristic_reference_is_rejected_before_request(self):
        first = self.base.observation("frame-1")
        second = self.base.observation("frame-2")

        invalid = replace(
            first,
            characteristic_iris_by_source_id={
                "e1": (
                    second.characteristic_iris_by_source_id["e1"][0],
                    first.characteristic_iris_by_source_id["e1"][1],
                ),
            },
        )

        with self.assertRaises(PopulationError):
            self.base.populate([invalid])

        self.base.client.generate.assert_not_called()

    def test_selection_survives_review_save_and_legacy_reports_remain_readable(self):
        observation = self.base.observation("frame-1")
        result = self.base.populate([observation])
        session = self.base.session_document()
        saved = self.base.saved[observation.analysis_id]

        report = {
            "ontology_source_sha256": "0" * 64,
            "sources": {
                observation.analysis_id: {
                    "frame_id": saved["frame_id"],
                    "image_path": None,
                    "image_sha256": saved["image_sha256"],
                },
            },
            **asdict(result),
        }

        frames = build_review_frames(session, report)
        expected = frames[0].characteristic_selection

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "review.json"
            save_review_report(
                destination,
                frames,
                {
                    frame.analysis_id: GraphRevision(frame.graph)
                    for frame in frames
                },
            )
            restored_report = json.loads(
                destination.read_text(encoding="utf-8")
            )

        restored = build_review_frames(
            session,
            restored_report,
        )

        self.assertEqual(
            expected,
            restored[0].characteristic_selection,
        )
        self.assertEqual("proposal", expected["status"])

        legacy = deepcopy(report)
        legacy["graphs"][observation.analysis_id].pop(
            "characteristic_selection"
        )

        self.assertIsNone(
            build_review_frames(session, legacy)[0]
            .characteristic_selection
        )


if __name__ == "__main__":
    unittest.main()