"""Selecția este produsă și verificată în același apel cu mini-grafurile."""

import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import (
    asdict,
    replace,
)
from pathlib import Path

import tests.ontology_population.test_population_sources as fixtures
from ontology_population.review import build_review_frames
from ontology_population.revision import GraphRevision
from ontology_population.service import PopulationError
from ontology_population.session import _population_observation
from ontology_population.storage import save_review_report
from unittest.mock import patch
from rdflib import RDFS

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

        analysis = result.graphs[
            observation.analysis_id
        ].identity_analysis

        self.assertEqual("proposal", analysis["status"])
        self.assertEqual(
            observation.occurrence_iris_by_source_id["e1"],
            analysis["appearances"][0]["occurrence_iri"],
        )
        self.assertEqual(
            [], analysis["appearances"][0]["identity_conditions"]
        )

    def test_identity_analysis_is_required_and_remains_a_proposal(self):
        observation = self.base.observation("frame-1")

        def omit_component(document):
            document.pop("identity_analysis")

        def accept(document):
            document["identity_analysis"]["status"] = "accepted"

        def omit_appearance(document):
            document["identity_analysis"]["appearances"].clear()

        for change in (
            omit_component,
            accept,
            omit_appearance,
        ):
            with self.subTest(change=change.__name__):
                self.base.client.generate.reset_mock()
                self.alter_response(change)

                with self.assertRaises(PopulationError):
                    self.base.populate([observation])

                self.assertEqual(
                    1, self.base.client.generate.call_count
                )

    def test_identity_analysis_cannot_use_another_groups_appearance(self):
        first = self.base.observation("frame-1")
        second = self.base.observation("frame-2")

        def replace_occurrence(document):
            document["identity_analysis"]["appearances"][0][
                "occurrence_iri"
            ] = second.occurrence_iris_by_source_id["e1"]

        self.alter_response(replace_occurrence)

        with self.assertRaises(PopulationError):
            self.base.populate([first])

    def test_identity_analysis_checks_quoted_ontology_text(self):
        observation = self.base.observation("frame-1")
        subject = "https://example.test/population#Item"
        note = (
            "Identity requires continuity of the same physical body."
        )
        ontology_turtle = (
            fixtures.ONTOLOGY
            + f'\n<{subject}> <{RDFS.comment}> "{note}"@en .\n'
        )

        for quotation, valid in (
            ("continuity of the same physical body", True),
            ("Un citat care nu există în ontologie.", False),
        ):
            with self.subTest(quotation=quotation):
                def add_condition(document):
                    appearance = document[
                        "identity_analysis"
                    ]["appearances"][0]
                    appearance["identity_conditions"] = [{
                        "description": "Continuitatea corpului fizic.",
                        "scope_description": "Scenariul sintetic de test.",
                        "origin": "ontology_text",
                        "justification": (
                            "Interpretare propusă a textului citat."
                        ),
                        "ontology_evidence": [{
                            "subject_iri": subject,
                            "predicate_iri": str(RDFS.comment),
                            "quotation": quotation,
                            "language": "en",
                        }],
                        "relevant_observation_iris": [
                            appearance["occurrence_iri"]
                        ],
                        "required_evidence": [
                            "Dovezi privind continuitatea corpului."
                        ],
                        "uncertain": True,
                    }]

                self.alter_response(add_condition)
                self.base.client.generate.reset_mock()

                with patch.object(
                    fixtures, "ONTOLOGY", ontology_turtle
                ):
                    if valid:
                        result = self.base.populate([observation])
                        self.assertEqual(
                            "proposal",
                            result.graphs[
                                observation.analysis_id
                            ].identity_analysis["status"],
                        )
                    else:
                        with self.assertRaises(PopulationError):
                            self.base.populate([observation])

                self.assertEqual(
                    1, self.base.client.generate.call_count
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
            "provider": "test",
            "requested_model": "test-model",
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
        self.assertEqual(1, len(frames))

        expected_selection = deepcopy(
            frames[0].characteristic_selection
        )
        expected_identity = deepcopy(
            frames[0].identity_analysis
        )

        self.assertIsNotNone(expected_selection)
        self.assertIsNotNone(expected_identity)

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

        self.assertEqual(1, len(restored))
        self.assertEqual(
            expected_selection,
            restored[0].characteristic_selection,
        )
        self.assertEqual(
            expected_identity,
            restored[0].identity_analysis,
        )
        self.assertEqual(
            "proposal",
            restored[0].characteristic_selection["status"],
        )
        self.assertEqual(
            "proposal",
            restored[0].identity_analysis["status"],
        )

        # Rapoartele vechi nu conțineau aceste două componente.
        legacy = deepcopy(report)
        legacy_candidate = legacy["graphs"][
            observation.analysis_id
        ]
        legacy_candidate.pop("characteristic_selection")
        legacy_candidate.pop("identity_analysis")

        legacy_frames = build_review_frames(
            session,
            legacy,
        )

        self.assertEqual(1, len(legacy_frames))
        self.assertIsNone(
            legacy_frames[0].characteristic_selection
        )
        self.assertIsNone(
            legacy_frames[0].identity_analysis
        )


if __name__ == "__main__":
    unittest.main()