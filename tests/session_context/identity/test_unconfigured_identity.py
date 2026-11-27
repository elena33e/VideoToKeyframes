"""Lipsa criteriilor nu blochează cadrul și nu șterge identități."""

import unittest

import tests.session_context.identity.test_frame_candidates as fixtures
from session_context.identity.graph import object_for_occurrence
from session_context.identity.assessment import assess_frame_identity


class UnconfiguredIdentityTest(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.FrameCandidatesTest()
        self.base.setUp()
        self.context = self.base.context

    def assess(self, criteria):
        before = set(
            self.context.dataset.quads((None, None, None, None))
        )

        results = assess_frame_identity(
            self.context,
            "frame-1",
            "frame-2",
            mapper=self.base.mapper,
            criteria_by_occurrence=criteria,
            language="ro",
        )

        self.assertEqual(
            before,
            set(self.context.dataset.quads(
                (None, None, None, None)
            )),
        )

        return {
            item.occurrence_iri: item
            for item in results
        }

    def test_unconfigured_appearance_remains_unresolved(self):
        result = self.assess({})[self.base.b]

        self.assertEqual("unresolved", result.action)
        self.assertEqual(
            ("criteria_not_configured",),
            result.reasons,
        )
        self.assertEqual((), result.selection.candidates)

    def test_configured_appearance_is_evaluated_in_partial_configuration(self):
        other = self.base.add_occurrence(
            "frame-2",
            "unconfigured",
            "culoare",
            "roșu",
        )

        results = self.assess({
            self.base.b: self.base.criteria,
        })

        self.assertEqual(
            {self.base.b, other},
            set(results),
        )
        self.assertEqual(
            1,
            len(results[self.base.b].selection.candidates),
        )
        self.assertNotIn(
            "criteria_not_configured",
            results[self.base.b].reasons,
        )
        self.assertEqual(
            ("criteria_not_configured",),
            results[other].reasons,
        )

    def test_existing_identity_is_preserved_without_criteria(self):
        self.base.fixture.confirm(
            self.base.a,
            self.base.b,
        )
        target = object_for_occurrence(
            self.context,
            self.base.b,
        )

        result = self.assess({})[self.base.b]

        self.assertEqual("already_associated", result.action)
        self.assertEqual(
            target,
            result.selection.existing_object_iri,
        )
        self.assertEqual(
            ("existing_identity",),
            result.reasons,
        )

    def test_criteria_for_another_frame_are_rejected(self):
        before = set(
            self.context.dataset.quads((None, None, None, None))
        )

        with self.assertRaises(ValueError):
            self.assess({
                self.base.a: self.base.criteria,
            })

        self.assertEqual(
            before,
            set(self.context.dataset.quads(
                (None, None, None, None)
            )),
        )


if __name__ == "__main__":
    unittest.main()