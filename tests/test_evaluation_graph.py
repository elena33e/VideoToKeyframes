"""Evaluările se păstrează separat de identitățile acceptate."""

import tempfile
import unittest
from pathlib import Path

from rdflib import Literal

import test_frame_candidates as fixtures
from session_context.evaluation_graph import (
    CTX,
    identity_evaluation_is_current,
    read_identity_evaluation,
    record_frame_identity_evaluation,
)
from session_context.persistence import (
    load_session_context,
    save_session_context,
)


class EvaluationGraphTest(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.FrameCandidatesTest()
        self.base.setUp()
        self.context = self.base.context

    def record(self, context=None):
        if context is None:
            context = self.context

        return record_frame_identity_evaluation(
            context,
            "frame-1",
            "frame-2",
            mapper=self.base.mapper,
            criteria_by_occurrence={
                self.base.b: self.base.criteria,
            },
            language="ro",
        )

    def test_record_preserves_observations_identities_and_evidence(self):
        observations = set(self.context.observations)
        identities = set(self.context.identities)

        record, assessments = self.record()
        data = read_identity_evaluation(
            self.context, record
        )

        self.assertEqual(
            observations,
            set(self.context.observations),
        )
        self.assertEqual(
            identities,
            set(self.context.identities),
        )
        self.assertEqual("unresolved", assessments[0].action)

        candidate = (
            data["assessments"][0]["selection"]["candidates"][0]
        )
        pair = candidate["assessments"][0]

        self.assertEqual(
            str(self.base.a),
            pair["type_comparison"]["left"]["occurrence_iri"],
        )
        self.assertEqual(
            self.base.criteria.criteria_id,
            pair["characteristics"]["criteria"]["criteria_id"],
        )
        self.assertTrue(
            identity_evaluation_is_current(
                self.context, record
            )
        )

    def test_repeated_evaluation_does_not_duplicate_data(self):
        first, _ = self.record()
        before = set(
            self.context.dataset.quads((None, None, None, None))
        )

        second, _ = self.record()

        self.assertEqual(first, second)
        self.assertEqual(
            before,
            set(self.context.dataset.quads(
                (None, None, None, None)
            )),
        )

    def test_save_reload_preserves_record_and_details(self):
        record, _ = self.record()
        expected = read_identity_evaluation(
            self.context, record
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "context.trig"
            save_session_context(self.context, path)
            restored = load_session_context(path)

        self.assertEqual(
            expected,
            read_identity_evaluation(restored, record),
        )
        self.assertTrue(
            identity_evaluation_is_current(restored, record)
        )

        repeated, _ = self.record(restored)
        self.assertEqual(record, repeated)

    def test_new_decision_keeps_old_evaluation_as_history(self):
        old_record, _ = self.record()

        self.base.fixture.confirm(
            self.base.a,
            self.base.b,
        )

        self.assertFalse(
            identity_evaluation_is_current(
                self.context, old_record
            )
        )

        new_record, assessments = self.record()

        self.assertNotEqual(old_record, new_record)
        self.assertEqual(
            "already_associated",
            assessments[0].action,
        )
        self.assertEqual(
            "unresolved",
            read_identity_evaluation(
                self.context, old_record
            )["assessments"][0]["action"],
        )

    def test_modified_rdf_summary_is_rejected(self):
        record, _ = self.record()
        graph = self.context.dataset.graph(record)
        result = graph.value(record, CTX.assessments)

        graph.set((
            result,
            CTX.assessmentAction,
            Literal("automatic"),
        ))

        with self.assertRaises(ValueError):
            read_identity_evaluation(
                self.context, record
            )

    def test_invalid_request_leaves_no_partial_evaluation(self):
        before = set(
            self.context.dataset.quads((None, None, None, None))
        )

        with self.assertRaises(ValueError):
            record_frame_identity_evaluation(
                self.context,
                "frame-1",
                "unknown",
                mapper=self.base.mapper,
                criteria_by_occurrence={
                    self.base.b: self.base.criteria,
                },
            )

        self.assertEqual(
            before,
            set(self.context.dataset.quads(
                (None, None, None, None)
            )),
        )


if __name__ == "__main__":
    unittest.main()