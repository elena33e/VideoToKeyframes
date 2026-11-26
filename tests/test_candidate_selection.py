"""Selecția respectă identitățile și deciziile existente."""

import unittest

import test_frame_candidates as frame_fixtures
from session_context.identity_graph import (
    object_for_occurrence,
    record_identity_decision,
)
from session_context.matching import select_frame_candidates


class CandidateSelectionTest(unittest.TestCase):
    def setUp(self):
        self.base = frame_fixtures.FrameCandidatesTest()
        self.base.setUp()

        self.context = self.base.context
        self.identity = self.base.fixture
        self.a = self.base.a
        self.b = self.base.b
        self.c = self.identity.c

    def select(self):
        before = set(
            self.context.dataset.quads((None, None, None, None))
        )

        result = select_frame_candidates(
            self.context,
            "frame-1",
            "frame-2",
            mapper=self.base.mapper,
            criteria_by_occurrence={
                self.b: self.base.criteria,
            },
            language="ro",
        )

        self.assertEqual(
            before,
            set(self.context.dataset.quads(
                (None, None, None, None)
            )),
        )

        return result[self.b]

    def test_concordant_and_changed_alternatives_are_retained(self):
        other = self.base.add_occurrence(
            "frame-1",
            "other",
            "culoare",
            "roșu",
        )

        result = self.select()

        self.assertIsNone(result.existing_object_iri)
        self.assertEqual(
            {self.a, other},
            {candidate.key for candidate in result.candidates},
        )
        self.assertEqual((), result.excluded_candidates)
        self.assertEqual(
            {"consistent", "difference_detected"},
            {
                assessment.characteristics.status
                for candidate in result.candidates
                for assessment in candidate.assessments
            },
        )

    def test_direct_rejection_is_excluded_with_provenance(self):
        decision = self.identity.decision(
            self.a, self.b, "different_objects"
        )
        decision_iri = record_identity_decision(
            self.context, decision
        )

        result = self.select()

        self.assertEqual((), result.candidates)
        self.assertEqual(1, len(result.excluded_candidates))

        excluded = result.excluded_candidates[0]

        self.assertEqual(self.a, excluded.key)
        self.assertEqual(
            (decision_iri,),
            excluded.rejection_decisions,
        )
        self.assertEqual(1, len(excluded.assessments))

    def test_unresolved_decision_keeps_the_candidate(self):
        decision_iri = record_identity_decision(
            self.context,
            self.identity.decision(
                self.a, self.b, "unresolved"
            ),
        )

        result = self.select()

        self.assertEqual(1, len(result.candidates))
        self.assertEqual((), result.excluded_candidates)
        self.assertEqual(
            (decision_iri,),
            result.candidates[0].unresolved_decisions,
        )

    def test_decisions_apply_through_other_identity_members(self):
        for outcome in ("different_objects", "unresolved"):
            with self.subTest(outcome=outcome):
                self.setUp()

                self.identity.confirm(self.a, self.c)
                target = object_for_occurrence(
                    self.context, self.a
                )

                decision_iri = record_identity_decision(
                    self.context,
                    self.identity.decision(
                        self.c, self.b, outcome
                    ),
                )

                result = self.select()

                if outcome == "different_objects":
                    self.assertEqual((), result.candidates)
                    candidate = result.excluded_candidates[0]
                    self.assertEqual(
                        (decision_iri,),
                        candidate.rejection_decisions,
                    )
                else:
                    self.assertEqual(
                        (),
                        result.excluded_candidates,
                    )
                    candidate = result.candidates[0]
                    self.assertEqual(
                        (decision_iri,),
                        candidate.unresolved_decisions,
                    )

                self.assertEqual(target, candidate.key)

    def test_reference_appearances_of_same_identity_form_one_candidate(self):
        other = self.base.add_occurrence(
            "frame-1",
            "other-view",
            "culoare",
            "albastru",
        )
        self.identity.confirm(self.a, other)

        target = object_for_occurrence(
            self.context, self.a
        )
        result = self.select()

        self.assertEqual(1, len(result.candidates))

        candidate = result.candidates[0]

        self.assertEqual(target, candidate.key)
        self.assertEqual(target, candidate.object_iri)
        self.assertEqual(
            {self.a, other},
            {
                assessment.type_comparison.left.occurrence_iri
                for assessment in candidate.assessments
            },
        )

    def test_existing_identity_is_returned_without_new_candidates(self):
        self.identity.confirm(self.a, self.b)
        target = object_for_occurrence(
            self.context, self.b
        )

        result = self.select()

        self.assertEqual(target, result.existing_object_iri)
        self.assertEqual((), result.candidates)
        self.assertEqual((), result.excluded_candidates)


if __name__ == "__main__":
    unittest.main()