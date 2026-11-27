"""Rezultatele evaluării păstrează incertitudinea și alternativele."""

import unittest

import tests.session_context.identity.test_frame_candidates as frame_fixtures
from session_context.identity.graph import (
    object_for_occurrence,
    record_identity_decision,
)
from session_context.identity.assessment import assess_frame_identity
from session_context.type_alignment import SessionTypeMapper
from tests.ontology.test_ontology_alignment import make_source


class IdentityAssessmentTest(unittest.TestCase):
    def setUp(self):
        self.base = frame_fixtures.FrameCandidatesTest()
        self.base.setUp()

        self.context = self.base.context
        self.identity = self.base.fixture
        self.a = self.base.a
        self.b = self.base.b

    def assess(self):
        before = set(
            self.context.dataset.quads((None, None, None, None))
        )

        results = assess_frame_identity(
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
        self.assertEqual(1, len(results))

        return results[0]

    def test_visual_concordance_does_not_automatically_establish_identity(self):
        result = self.assess()

        self.assertEqual("unresolved", result.action)
        self.assertIn(
            "identity_evidence_required",
            result.reasons,
        )
        self.assertEqual(1, len(result.selection.candidates))

    def test_unique_changed_candidate_requires_review(self):
        self.identity._set_characteristics(
            self.b,
            ("culoare", "roșu", False),
        )

        result = self.assess()

        self.assertEqual("confirmation", result.action)
        self.assertIn(
            "characteristic_difference",
            result.reasons,
        )

    def test_missing_or_uncertain_characteristic_does_not_request_confirmation(self):
        cases = (
            (),
            (("culoare", "roșu", True),),
        )

        for items in cases:
            with self.subTest(items=items):
                self.identity._set_characteristics(
                    self.b,
                    *items,
                )

                result = self.assess()

                self.assertEqual("unresolved", result.action)
                self.assertIn(
                    "insufficient_characteristics",
                    result.reasons,
                )
                self.assertNotIn(
                    "characteristic_difference",
                    result.reasons,
                )

    def test_changed_alternative_blocks_unique_candidate_result(self):
        self.base.add_occurrence(
            "frame-1",
            "other",
            "culoare",
            "roșu",
        )

        result = self.assess()

        self.assertEqual("unresolved", result.action)
        self.assertIn("multiple_candidates", result.reasons)
        self.assertIn(
            "characteristic_difference",
            result.reasons,
        )
        self.assertEqual(2, len(result.selection.candidates))

    def test_postponed_decision_does_not_trigger_another_confirmation(self):
        self.identity._set_characteristics(
            self.b,
            ("culoare", "roșu", False),
        )

        decision_iri = record_identity_decision(
            self.context,
            self.identity.decision(
                self.a, self.b, "unresolved"
            ),
        )

        result = self.assess()

        self.assertEqual("unresolved", result.action)
        self.assertIn(
            "previous_unresolved_decision",
            result.reasons,
        )
        self.assertIn(
            "characteristic_difference",
            result.reasons,
        )
        self.assertEqual(
            (decision_iri,),
            result.selection.candidates[0].unresolved_decisions,
        )

    def test_type_issues_are_explained_without_rejecting_the_candidate(self):
        cases = (
            (
                'ex:X a owl:Class ; rdfs:label "alt concept"@ro .',
                "unmapped_types",
            ),
            (
                """
                ex:A a owl:Class ; rdfs:label "element"@ro .
                ex:B a owl:Class ; rdfs:label "element"@ro .
                ex:C a owl:Class ;
                    rdfs:label "element finisat"@ro .
                """,
                "ambiguous_types",
            ),
            (
                """
                ex:A a owl:Class ; rdfs:label "element"@ro .
                ex:B a owl:Class ;
                    rdfs:label "element finisat"@ro .
                """,
                "unknown_type_relation",
            ),
            (
                """
                ex:A a owl:Class ;
                    rdfs:label "element"@ro ;
                    owl:disjointWith ex:B .
                ex:B a owl:Class ;
                    rdfs:label "element finisat"@ro .
                """,
                "declared_disjoint_types",
            ),
        )

        for body, expected_reason in cases:
            with self.subTest(reason=expected_reason):
                self.base.mapper = SessionTypeMapper(
                    make_source(body)
                )

                result = self.assess()

                self.assertEqual("unresolved", result.action)
                self.assertIn(expected_reason, result.reasons)
                self.assertEqual(
                    1,
                    len(result.selection.candidates),
                )
                self.assertEqual(
                    (),
                    result.selection.excluded_candidates,
                )

    def test_existing_identity_is_preserved_despite_observed_difference(self):
        self.identity._set_characteristics(
            self.b,
            ("culoare", "roșu", False),
        )
        self.identity.confirm(self.a, self.b)

        target = object_for_occurrence(
            self.context, self.b
        )
        result = self.assess()

        self.assertEqual("already_associated", result.action)
        self.assertEqual(
            ("existing_identity",),
            result.reasons,
        )
        self.assertEqual(
            target,
            result.selection.existing_object_iri,
        )


if __name__ == "__main__":
    unittest.main()